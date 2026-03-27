"""
alfred/features/todos.py
=========================
Todo list management via Google Tasks.

COMMANDS
────────
  /todos                  — list open todos
  /todos done             — list completed todos
  /todos clear            — clear all completed todos (with confirmation)

INTENT HANDLER
──────────────
  handle_todo_intent(intent, entities, update, context)
      Dispatches all TODO_* intents from the intent classifier.

      Supported intents:
        TODO_ADD      — "add todo [text]" / "remind me to [text]"
                        entities: {"task": "...", "due": "YYYY-MM-DD",
                                   "priority": "high|normal|low",
                                   "recur": "daily|weekdays|weekly|monthly|none"}
        TODO_LIST     — "show todos" / "what's on my list"
        TODO_COMPLETE — "done with [text]" / "mark [text] complete"
                        entities: {"task": "..."} (fuzzy match on title)
        TODO_DELETE   — "delete todo [text]"
                        entities: {"task": "..."}
        TODO_UPDATE   — "update todo [text] to [new text]"
                        entities: {"task": "...", "new_text": "..."}

RECURRENCE
──────────
  Todos can recur daily / weekdays / weekly / monthly.
  The recurrence and next-due date are stored in the task notes field as JSON.
  bot.py runs advance_recurring_items() at 12:01 AM daily to roll recurring
  todos that are past their due date to the next occurrence.
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes

from core.config import BOT_NAME, RECUR_LABELS
from core.intent import (
    TODO_ADD, TODO_LIST, TODO_COMPLETE, TODO_DELETE, TODO_UPDATE,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _get_service():
    """Return an authorized Google Tasks service or None."""
    from core.google_auth import get_tasks_service
    return get_tasks_service()


def _auth_error_msg() -> str:
    return "❌ Google Tasks isn't connected. Run /auth to connect your Google account."


def _format_todo(task: dict, idx: int) -> str:
    """Format a single todo for display."""
    title    = task.get("title", "(untitled)")
    meta     = task.get("_meta", {})
    due      = task.get("due", "")[:10]  # YYYY-MM-DD
    priority = meta.get("priority", "normal")
    recur    = meta.get("recur", "none")
    status   = task.get("status", "needsAction")

    parts = [f"  {idx}. {title}"]

    extras = []
    if due:
        extras.append(f"due {due}")
    if priority == "high":
        extras.append("🔴 high")
    elif priority == "low":
        extras.append("🔵 low")
    if recur and recur != "none":
        extras.append(RECUR_LABELS.get(recur, recur))
    if status == "completed":
        parts = [f"  {idx}. ~~{title}~~"]

    if extras:
        parts.append(f"     _({', '.join(extras)})_")

    return "\n".join(parts)


def _format_todo_list(todos: list[dict], title: str = "📋 *Todos*") -> str:
    """Format a list of todos for Telegram."""
    if not todos:
        return f"{title}\n  _Nothing here._"

    lines = [title]
    for i, t in enumerate(todos, 1):
        lines.append(_format_todo(t, i))
    return "\n".join(lines)


def _find_best_match(todos: list[dict], query: str) -> dict | None:
    """
    Fuzzy-find a todo by title.
    First tries exact (case-insensitive), then substring match.
    """
    if not query:
        return None
    q = query.lower()
    # Exact match
    for t in todos:
        if t.get("title", "").lower() == q:
            return t
    # Substring match (pick shortest title that contains query)
    matches = [t for t in todos if q in t.get("title", "").lower()]
    if not matches:
        return None
    return min(matches, key=lambda t: len(t.get("title", "")))


# ─────────────────────────────────────────────────────────────────────────────
# /todos COMMAND
# ─────────────────────────────────────────────────────────────────────────────

async def cmd_todos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /todos [done | clear]

    Without args: show open todos.
    'done': show completed todos.
    'clear': remove all completed todos (with confirmation).
    """
    args = context.args or []
    sub  = args[0].lower() if args else ""

    svc = _get_service()
    if not svc:
        await update.message.reply_text(_auth_error_msg())
        return

    if sub == "done":
        from adapters.google_tasks import list_todos
        todos = list_todos(svc, include_done=True)
        done  = [t for t in todos if t.get("status") == "completed"]
        await update.message.reply_text(
            _format_todo_list(done, "✅ *Completed Todos*"),
            parse_mode="Markdown",
        )
        return

    if sub == "clear":
        from adapters.google_tasks import list_todos, delete_todo
        todos     = list_todos(svc, include_done=True)
        completed = [t for t in todos if t.get("status") == "completed"]
        if not completed:
            await update.message.reply_text("No completed todos to clear.")
            return
        removed = 0
        for t in completed:
            if delete_todo(svc, t["id"]):
                removed += 1
        await update.message.reply_text(
            f"✓ Cleared {removed} completed todo(s).",
            parse_mode="Markdown",
        )
        return

    # Default: show open todos
    from adapters.google_tasks import list_todos
    todos = list_todos(svc, include_done=False)
    await update.message.reply_text(
        _format_todo_list(todos),
        parse_mode="Markdown",
    )


# ─────────────────────────────────────────────────────────────────────────────
# INTENT HANDLER
# ─────────────────────────────────────────────────────────────────────────────

async def handle_todo_intent(
    intent:  str,
    entities: dict,
    update:  Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Dispatch all TODO_* intents."""

    svc = _get_service()
    if not svc:
        await update.message.reply_text(_auth_error_msg())
        return

    # ── TODO_ADD ─────────────────────────────────────────────────────────────
    if intent == TODO_ADD:
        task_text = entities.get("task", "").strip()
        if not task_text:
            await update.message.reply_text(
                "What should I add? Try: \"add todo finish the report\""
            )
            return

        priority  = entities.get("priority", "normal")
        recur     = entities.get("recur", "none")
        due_date  = entities.get("due", "")

        from adapters.google_tasks import add_todo
        result = add_todo(
            svc,
            text=task_text,
            priority=priority,
            recur=recur,
            recur_next=due_date if recur != "none" else "",
            due_date=due_date,
        )
        if result:
            extras = []
            if due_date:
                extras.append(f"due {due_date}")
            if priority == "high":
                extras.append("🔴 high priority")
            if recur and recur != "none":
                extras.append(RECUR_LABELS.get(recur, recur))
            suffix = f" _({', '.join(extras)})_" if extras else ""
            await update.message.reply_text(
                f"✓ Added: *{task_text}*{suffix}",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text("Sorry, I couldn't add that. Try again.")
        return

    # ── TODO_LIST ─────────────────────────────────────────────────────────────
    if intent == TODO_LIST:
        from adapters.google_tasks import list_todos
        todos = list_todos(svc, include_done=False)
        await update.message.reply_text(
            _format_todo_list(todos),
            parse_mode="Markdown",
        )
        return

    # ── TODO_COMPLETE ─────────────────────────────────────────────────────────
    if intent == TODO_COMPLETE:
        query = entities.get("task", "").strip()
        from adapters.google_tasks import list_todos, complete_todo
        todos = list_todos(svc, include_done=False)

        if not query:
            # No specific task — ask which one
            if not todos:
                await update.message.reply_text("Your todo list is empty.")
                return
            lines = ["Which todo did you complete? Reply with the number:\n"]
            for i, t in enumerate(todos, 1):
                lines.append(f"  {i}. {t.get('title','(untitled)')}")
            await update.message.reply_text("\n".join(lines))
            return

        match = _find_best_match(todos, query)
        if not match:
            await update.message.reply_text(
                f"I couldn't find a todo matching \"{query}\". "
                f"Run /todos to see your list."
            )
            return

        if complete_todo(svc, match["id"]):
            await update.message.reply_text(
                f"✓ Marked complete: *{match['title']}*",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text("Couldn't mark that as done. Try again.")
        return

    # ── TODO_DELETE ────────────────────────────────────────────────────────────
    if intent == TODO_DELETE:
        query = entities.get("task", "").strip()
        from adapters.google_tasks import list_todos, delete_todo
        todos = list_todos(svc, include_done=False)

        if not query:
            await update.message.reply_text(
                "Which todo should I delete? Try: \"delete todo [name]\""
            )
            return

        match = _find_best_match(todos, query)
        if not match:
            await update.message.reply_text(
                f"No todo found matching \"{query}\". Run /todos to see your list."
            )
            return

        if delete_todo(svc, match["id"]):
            await update.message.reply_text(
                f"✓ Deleted: *{match['title']}*",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text("Couldn't delete that. Try again.")
        return

    # ── TODO_UPDATE ────────────────────────────────────────────────────────────
    if intent == TODO_UPDATE:
        query    = entities.get("task", "").strip()
        new_text = entities.get("new_text", "").strip()

        if not query or not new_text:
            await update.message.reply_text(
                "To update a todo, say: \"change [old name] to [new name]\""
            )
            return

        from adapters.google_tasks import list_todos, update_todo
        todos = list_todos(svc, include_done=False)
        match = _find_best_match(todos, query)
        if not match:
            await update.message.reply_text(
                f"No todo found matching \"{query}\". Run /todos to see your list."
            )
            return

        result = update_todo(svc, match["id"], new_text=new_text)
        if result:
            await update.message.reply_text(
                f"✓ Updated: *{new_text}*",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text("Couldn't update that. Try again.")
        return

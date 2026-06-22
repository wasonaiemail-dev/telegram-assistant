"""
alfred/features/sync_tasks.py
==============================
Google Tasks sync summary — /synctasks command + auto_sync_tasks scheduled job.

Alfred stores all todos, shopping lists, and gifts directly in Google Tasks.
That means anything you add on Alfred shows up immediately in the Google Tasks
phone app, and anything you add or check off on your phone is instantly
reflected the next time Alfred reads a list. No traditional "sync" is needed.

What this module adds:
  • /synctasks  — On-demand consolidated view of all Alfred Google Tasks lists.
                   Shows todo count + high-priority items, each shopping list with
                   items, and gift ideas count. Useful after you have been adding
                   things from your phone and want to see what Alfred sees.
  • auto_sync_tasks  — Scheduled job at 7:05 AM (5 min after briefing). Sends
                       the same summary automatically each morning so you know
                       what's on your lists without having to ask.

COMMAND
───────
  /synctasks               — show full list summary right now

SCHEDULED JOB
─────────────
  auto_sync_tasks(context) — called by bot.py scheduler at 7:05 AM daily
"""

import logging
import datetime

from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _get_service():
    """Return an authorized Google Tasks service or None."""
    try:
        from core.google_auth import get_tasks_service
        return get_tasks_service()
    except Exception as e:
        logger.error(f"sync_tasks: could not get Tasks service: {e}")
        return None


def _priority_label(task: dict) -> str:
    """Return '🔴' for high priority tasks, '' otherwise."""
    try:
        import json
        meta = json.loads(task.get("notes", "") or "{}")
        if meta.get("priority") == "high":
            return "🔴 "
    except Exception:
        pass
    return ""


def _is_overdue(task: dict) -> bool:
    """Return True if this task has a due date in the past."""
    due_raw = task.get("due", "")
    if not due_raw:
        return False
    try:
        due_date = datetime.date.fromisoformat(str(due_raw)[:10])
        return due_date < datetime.date.today()
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# CORE: BUILD SUMMARY TEXT
# ─────────────────────────────────────────────────────────────────────────────

def build_sync_summary() -> str:
    """
    Read all Alfred Google Tasks lists and return a formatted summary string.

    Returns a human-readable Markdown string covering:
      - Open todos (total, overdue, high-priority)
      - Each shopping list (item count + first 5 items)
      - Gift ideas (total count)

    Returns an error message string on failure — never raises.
    """
    svc = _get_service()
    if not svc:
        return "❌ Google Tasks isn't connected. Run /auth to reconnect."

    sections = []

    # ── TODOS ─────────────────────────────────────────────────────────────────
    try:
        from adapters.google_tasks import list_todos
        todos = list_todos(svc, include_done=False)

        overdue  = [t for t in todos if _is_overdue(t)]
        high_pri = [t for t in todos if _priority_label(t)]
        count    = len(todos)

        lines = [f"✅ *Todos* ({count} open)"]
        if overdue:
            lines.append(f"  ⚠️ {len(overdue)} overdue:")
            for t in overdue[:3]:
                lines.append(f"    • {_priority_label(t)}{t.get('title', '(untitled)')}")
            if len(overdue) > 3:
                lines.append(f"    …and {len(overdue) - 3} more")

        if high_pri and not overdue:
            lines.append(f"  🔴 {len(high_pri)} high priority:")
            for t in high_pri[:3]:
                lines.append(f"    • {t.get('title', '(untitled)')}")
            if len(high_pri) > 3:
                lines.append(f"    …and {len(high_pri) - 3} more")

        if count == 0:
            lines.append("  Nothing on the list. 🎉")
        elif not overdue and not high_pri:
            # Show first few todos
            for t in todos[:5]:
                lines.append(f"  • {t.get('title', '(untitled)')}")
            if count > 5:
                lines.append(f"  …and {count - 5} more")

        sections.append("\n".join(lines))
    except Exception as e:
        logger.warning(f"sync_tasks: todos section error: {e}")
        sections.append("✅ *Todos*\n  _(unable to load)_")

    # ── SHOPPING LISTS ────────────────────────────────────────────────────────
    try:
        from core.config import GTASKS_SHOPPING_LISTS
        from adapters.google_tasks import list_shopping

        shopping_lines = ["🛒 *Shopping*"]
        any_items = False

        for key, list_name in GTASKS_SHOPPING_LISTS.items():
            items = list_shopping(svc, key, include_done=False)
            # Use the Google Tasks list name (e.g. "Shopping: Grocery") but strip the prefix
            label = list_name.replace("Shopping: ", "").replace("Shopping:", "").strip() or key.title()
            if items:
                any_items = True
                shopping_lines.append(f"  *{label}* ({len(items)})")
                for item in items[:5]:
                    shopping_lines.append(f"    • {item.get('title', '(untitled)')}")
                if len(items) > 5:
                    shopping_lines.append(f"    …and {len(items) - 5} more")
            else:
                shopping_lines.append(f"  *{label}*: empty")

        if not any_items:
            shopping_lines.append("  All lists are empty.")

        sections.append("\n".join(shopping_lines))
    except Exception as e:
        logger.warning(f"sync_tasks: shopping section error: {e}")
        sections.append("🛒 *Shopping*\n  _(unable to load)_")

    # ── GIFTS ─────────────────────────────────────────────────────────────────
    try:
        from adapters.google_tasks import list_gifts
        gifts = list_gifts(svc)
        count = len(gifts)
        if count:
            sections.append(f"🎁 *Gifts* — {count} idea{'s' if count != 1 else ''} saved (run /gifts to view)")
        else:
            sections.append("🎁 *Gifts* — no ideas saved yet")
    except Exception as e:
        logger.warning(f"sync_tasks: gifts section error: {e}")

    # ── HEADER + FOOTER ───────────────────────────────────────────────────────
    now = datetime.datetime.now().strftime("%-I:%M %p")
    header = f"📋 *Alfred Lists — Synced with Google Tasks*\n_Last updated: {now}_\n"
    footer = "\n_All changes made on your phone or here stay in sync automatically._"

    return header + "\n\n".join(sections) + footer


# ─────────────────────────────────────────────────────────────────────────────
# /synctasks COMMAND
# ─────────────────────────────────────────────────────────────────────────────

async def cmd_synctasks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /synctasks — Show a consolidated view of all Alfred Google Tasks lists.

    Reads todos, all shopping lists, and gift ideas from Google Tasks and
    returns a formatted summary. Use this after adding items on your phone
    to confirm Alfred sees them, or anytime you want a full picture of your lists.
    """
    await update.message.reply_text(
        build_sync_summary(),
        parse_mode="Markdown",
    )


# ─────────────────────────────────────────────────────────────────────────────
# SCHEDULED JOB — auto_sync_tasks (7:05 AM daily)
# ─────────────────────────────────────────────────────────────────────────────

async def auto_sync_tasks(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Scheduled job — fires at 7:05 AM (5 minutes after the morning briefing).

    Sends the user a consolidated Google Tasks summary so they start the day with
    a clear picture of everything on their lists, including anything they added
    from their phone the night before.
    """
    try:
        from core.config import ALLOWED_USER_ID
        summary = build_sync_summary()
        await context.bot.send_message(
            chat_id=ALLOWED_USER_ID,
            text=summary,
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"auto_sync_tasks error: {e}")

"""
marvin/features/undo.py
========================
Undo last deletion for Marvin.

WHAT CAN BE UNDONE
───────────────────
  • Deleted todo      → recreated in Google Tasks "Marvin Todos"
  • Deleted note      → recreated in Google Tasks "Marvin Notes"
  • Deleted shopping  → recreated in the appropriate Google Tasks shopping list
  • Deleted expense   → restored to userdata.json["expenses"]
  • Deleted mood      → restored to userdata.json["mood_log"]

HOW IT WORKS
─────────────
Before any delete, the calling feature calls record_deletion() which saves
the deleted item to userdata.json["_last_deleted"] (stores up to 5 items).

"undo" / "undo that" triggers the UNDO intent which pops the stack,
recreates the item via the appropriate API or JSON restore, and confirms.

TRIGGERS
─────────
  "undo"           → undo last action
  "undo that"      → undo last action
  "take it back"   → undo last action
  "never mind"     → undo last action (if a deletion was recorded)

NOTE ON TODOS/NOTES IN GOOGLE TASKS
─────────────────────────────────────
Because todos and notes live in Google Tasks (not local JSON), undo recreates
them as NEW items (same title). The original Google Tasks ID is gone after
deletion. Undo effectively says "add this back" rather than restoring an exact
snapshot.
"""

from __future__ import annotations

import logging

from core.marvin_context import MarvinContext
from core.data import load_data, save_data

logger = logging.getLogger(__name__)

# Max deletions to remember
_STACK_MAX = 5


# ════════════════════════════════════════════════════════════════════════════
# PUBLIC — called by feature delete handlers BEFORE the actual delete
# ════════════════════════════════════════════════════════════════════════════

def record_deletion(
    data:      dict,
    item_type: str,
    title:     str = "",
    list_key:  str = "",
    expense:   dict | None = None,
    mood:      dict | None = None,
) -> None:
    """
    Push a deletable snapshot onto _last_deleted before actually deleting.

    Args:
        data:       current userdata dict (will be mutated + saved by caller)
        item_type:  "todo" | "note" | "shopping" | "expense" | "mood"
        title:      item title text (for todo/note/shopping)
        list_key:   shopping list key (only for item_type="shopping")
        expense:    full expense dict (only for item_type="expense")
        mood:       full mood entry dict (only for item_type="mood")
    """
    entry = {"type": item_type}
    if item_type in ("todo", "note"):
        entry["title"] = title
    elif item_type == "shopping":
        entry["title"]    = title
        entry["list_key"] = list_key
    elif item_type == "expense":
        entry["expense"] = expense or {}
    elif item_type == "mood":
        entry["mood"] = mood or {}

    stack = data.setdefault("_last_deleted", [])
    stack.append(entry)
    data["_last_deleted"] = stack[-_STACK_MAX:]  # keep last N


# ════════════════════════════════════════════════════════════════════════════
# INTENT HANDLER
# ════════════════════════════════════════════════════════════════════════════

async def handle_undo_intent(ctx: MarvinContext) -> None:
    """Pop the last deletion and recreate it."""
    data  = load_data()
    stack = data.get("_last_deleted", [])

    if not stack:
        await ctx.reply("Nothing to undo — I haven't deleted anything recently.")
        return

    entry = stack.pop()
    data["_last_deleted"] = stack
    save_data(data)

    item_type = entry.get("type", "")

    # ── Undo todo ─────────────────────────────────────────────────────────
    if item_type == "todo":
        title = entry.get("title", "")
        try:
            from core.google_auth import get_tasks_service
            from adapters.google_tasks import add_todo
            svc = get_tasks_service()
            if svc and add_todo(svc, title):
                await ctx.reply_markdown(f"↩️ Restored todo: *{title}*")
            else:
                await ctx.reply("Couldn't restore that todo — Google Tasks unavailable.")
        except Exception as e:
            logger.error(f"undo todo: {e}")
            await ctx.reply("Something went wrong restoring that todo.")

    # ── Undo note ─────────────────────────────────────────────────────────
    elif item_type == "note":
        title = entry.get("title", "")
        try:
            from core.google_auth import get_tasks_service
            from adapters.google_tasks import add_note
            svc = get_tasks_service()
            if svc and add_note(svc, title):
                await ctx.reply_markdown(f"↩️ Restored note: _{title[:60]}_")
            else:
                await ctx.reply("Couldn't restore that note — Google Tasks unavailable.")
        except Exception as e:
            logger.error(f"undo note: {e}")
            await ctx.reply("Something went wrong restoring that note.")

    # ── Undo shopping item ────────────────────────────────────────────────
    elif item_type == "shopping":
        title    = entry.get("title", "")
        list_key = entry.get("list_key", "grocery")
        try:
            from core.google_auth import get_tasks_service
            from adapters.google_tasks import add_shopping_item
            from core.config import SHOPPING_LISTS
            svc   = get_tasks_service()
            label = SHOPPING_LISTS.get(list_key, list_key.title())
            if svc and add_shopping_item(svc, list_key, title):
                await ctx.reply_markdown(f"↩️ Restored *{title}* to *{label}*.")
            else:
                await ctx.reply("Couldn't restore that shopping item.")
        except Exception as e:
            logger.error(f"undo shopping: {e}")
            await ctx.reply("Something went wrong restoring that shopping item.")

    # ── Undo expense ──────────────────────────────────────────────────────
    elif item_type == "expense":
        exp = entry.get("expense", {})
        if not exp:
            await ctx.reply("No expense data to restore.")
            return
        try:
            # Reload fresh to avoid overwrite races
            data2 = load_data()
            data2.setdefault("expenses", []).append(exp)
            save_data(data2)
            cat  = exp.get("category", "other")
            amt  = exp.get("amount", 0.0)
            await ctx.reply_markdown(f"↩️ Restored expense: *${amt:.2f}* ({cat})")
        except Exception as e:
            logger.error(f"undo expense: {e}")
            await ctx.reply("Something went wrong restoring that expense.")

    # ── Undo mood ─────────────────────────────────────────────────────────
    elif item_type == "mood":
        mood = entry.get("mood", {})
        if not mood:
            await ctx.reply("No mood data to restore.")
            return
        try:
            # Reload fresh to avoid overwrite races
            data2 = load_data()
            log = data2.setdefault("mood_log", [])
            # Drop any current entry for that date, then restore the snapshot
            target_date = mood.get("date")
            data2["mood_log"] = [e for e in log if e.get("date") != target_date]
            data2["mood_log"].append(mood)
            save_data(data2)
            rating = mood.get("rating", 0)
            await ctx.reply_markdown(f"↩️ Restored mood entry for *{target_date}*: {rating}/10")
        except Exception as e:
            logger.error(f"undo mood: {e}")
            await ctx.reply("Something went wrong restoring that mood entry.")

    else:
        await ctx.reply("I'm not sure what to undo.")

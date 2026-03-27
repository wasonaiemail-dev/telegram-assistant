"""
alfred/features/reminders.py
==============================
Reminders — timed and recurring alerts stored in userdata.json.

COMMANDS
────────
  /reminders              — list active reminders
  /reminders done [#]     — mark reminder as done
  /reminders delete [#]   — delete a reminder

INTENT HANDLER
──────────────
  handle_reminder_intent(intent, entities, update, context)

  Supported intents:
    REMINDER_ADD    — "remind me to call mom at 3pm"
                      entities: {"text": "...", "due": "YYYY-MM-DDTHH:MM" or "YYYY-MM-DD",
                                 "recur": "daily|weekdays|weekly|monthly|none"}
    REMINDER_LIST   — "show reminders" / "what reminders do I have"
    REMINDER_DONE   — "done with reminder 2" / "mark reminder as done"
                      entities: {"number": 2} or {"text": "..."}
    REMINDER_DELETE — "delete reminder 2"
                      entities: {"number": 2} or {"text": "..."}

FIRE CHECK
──────────
  check_and_fire_reminders(context, chat_id)
      Called every 60 seconds by the reminder_check job in bot.py.
      Sends a Telegram message for any reminder whose due time has arrived.
      Marks fired reminders as done (or advances them if recurring).

GET DUE TODAY
─────────────
  get_due_today() → list[dict]
      Returns reminders due today. Used by the morning briefing.

REMINDER SCHEMA
───────────────
  {
    "id":         int,
    "text":       str,
    "due":        "YYYY-MM-DDTHH:MM" | "YYYY-MM-DD" | null,
    "done":       bool,
    "recur":      "daily"|"weekdays"|"weekly"|"monthly"|"none",
    "recur_next": "YYYY-MM-DD" | null,
    "added":      "YYYY-MM-DDTHH:MM"
  }
"""

import logging
import datetime
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import ContextTypes

from core.config import BOT_NAME, TIMEZONE, RECUR_LABELS
from core.intent import (
    REMINDER_ADD, REMINDER_LIST, REMINDER_DONE, REMINDER_DELETE,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# DATA HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _now_local() -> datetime.datetime:
    return datetime.datetime.now(ZoneInfo(TIMEZONE))


def _next_id(reminders: list) -> int:
    if not reminders:
        return 1
    return max(r.get("id", 0) for r in reminders) + 1


def _load_reminders() -> tuple[dict, list]:
    """Return (data, reminders_list)."""
    from core.data import load_data
    data = load_data()
    return data, data.get("reminders", [])


def _save_reminders(data: dict) -> None:
    from core.data import save_data
    save_data(data)


def _parse_due(due_str: str | None) -> str | None:
    """
    Normalize a due string to 'YYYY-MM-DDTHH:MM' or 'YYYY-MM-DD'.
    Returns None if the string is empty or unparseable.
    """
    if not due_str:
        return None
    due_str = due_str.strip()

    # Already correct format
    if len(due_str) == 16 and "T" in due_str:  # YYYY-MM-DDTHH:MM
        return due_str
    if len(due_str) == 10 and due_str[4] == "-":  # YYYY-MM-DD
        return due_str

    # Try parsing with datetime
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.datetime.strptime(due_str[:16], fmt)
            if len(due_str) <= 10:
                return dt.strftime("%Y-%m-%d")
            return dt.strftime("%Y-%m-%dT%H:%M")
        except ValueError:
            continue
    return None


def _reminder_due_datetime(reminder: dict) -> datetime.datetime | None:
    """Return the due datetime (localized) or None."""
    due = reminder.get("due") or reminder.get("recur_next")
    if not due:
        return None
    try:
        if "T" in due:
            dt = datetime.datetime.fromisoformat(due)
        else:
            # Date only — treat as midnight local
            d  = datetime.date.fromisoformat(due[:10])
            dt = datetime.datetime(d.year, d.month, d.day, 9, 0)  # default 9 AM
        # Attach local timezone if naive
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo(TIMEZONE))
        return dt
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC: get_due_today  (used by briefing.py)
# ─────────────────────────────────────────────────────────────────────────────

def get_due_today() -> list[dict]:
    """Return active reminders due today (date match only, not time-precise)."""
    _, reminders = _load_reminders()
    today = _now_local().date()
    result = []
    for r in reminders:
        if r.get("done"):
            continue
        due = r.get("due") or r.get("recur_next")
        if not due:
            continue
        try:
            d = datetime.date.fromisoformat(due[:10])
            if d == today:
                result.append(r)
        except ValueError:
            pass
    return result


# ─────────────────────────────────────────────────────────────────────────────
# DISPLAY HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _format_reminder(r: dict, idx: int) -> str:
    """Format a single reminder for display."""
    text  = r.get("text", "(no text)")
    due   = r.get("due") or r.get("recur_next") or ""
    recur = r.get("recur", "none")

    parts = [f"  {idx}. {text}"]
    extras = []

    if due:
        if "T" in due:
            dt_str = due.replace("T", " ")
        else:
            dt_str = due[:10]
        extras.append(f"📅 {dt_str}")

    if recur and recur != "none":
        extras.append(f"🔁 {RECUR_LABELS.get(recur, recur)}")

    if extras:
        parts.append(f"     _({', '.join(extras)})_")

    return "\n".join(parts)


def _format_reminder_list(reminders: list[dict]) -> str:
    """Format active reminders for Telegram."""
    active = [r for r in reminders if not r.get("done")]
    if not active:
        return "⏰ *Reminders*\n  _No active reminders._"
    lines = [f"⏰ *Reminders* ({len(active)})"]
    for i, r in enumerate(active, 1):
        lines.append(_format_reminder(r, i))
    return "\n".join(lines)


def _find_reminder(reminders: list[dict], query: str | None, number: int | None) -> dict | None:
    """Find a reminder by number (1-based among active) or text match."""
    active = [r for r in reminders if not r.get("done")]

    if number is not None:
        try:
            idx = int(number) - 1
            if 0 <= idx < len(active):
                return active[idx]
        except (TypeError, ValueError):
            pass

    if query:
        q = query.lower()
        for r in active:
            if q in r.get("text", "").lower():
                return r

    return None


# ─────────────────────────────────────────────────────────────────────────────
# /reminders COMMAND
# ─────────────────────────────────────────────────────────────────────────────

async def cmd_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /reminders [done # | delete #]
    """
    args = context.args or []
    data, reminders = _load_reminders()

    if not args:
        await update.message.reply_text(
            _format_reminder_list(reminders),
            parse_mode="Markdown",
        )
        return

    sub = args[0].lower()

    if sub in ("done", "complete"):
        if len(args) < 2:
            await update.message.reply_text("Usage: /reminders done [number]")
            return
        try:
            num = int(args[1])
        except ValueError:
            await update.message.reply_text("Please provide a number, e.g. /reminders done 2")
            return
        r = _find_reminder(reminders, None, num)
        if not r:
            await update.message.reply_text(f"Reminder #{num} not found.")
            return
        r["done"] = True
        _save_reminders(data)
        await update.message.reply_text(
            f"✓ Done: _{r['text']}_",
            parse_mode="Markdown",
        )
        return

    if sub == "delete":
        if len(args) < 2:
            await update.message.reply_text("Usage: /reminders delete [number]")
            return
        try:
            num = int(args[1])
        except ValueError:
            await update.message.reply_text("Please provide a number, e.g. /reminders delete 2")
            return
        active = [r for r in reminders if not r.get("done")]
        if not (1 <= num <= len(active)):
            await update.message.reply_text(f"Reminder #{num} not found.")
            return
        r = active[num - 1]
        data["reminders"] = [x for x in reminders if x.get("id") != r.get("id")]
        _save_reminders(data)
        await update.message.reply_text(
            f"✓ Deleted: _{r['text']}_",
            parse_mode="Markdown",
        )
        return

    await update.message.reply_text(
        "Usage:\n"
        "  /reminders — list reminders\n"
        "  /reminders done [#] — mark done\n"
        "  /reminders delete [#] — delete"
    )


# ─────────────────────────────────────────────────────────────────────────────
# FIRE CHECK  (called every 60s by bot.py job)
# ─────────────────────────────────────────────────────────────────────────────

async def check_and_fire_reminders(context, chat_id: int) -> None:
    """
    Check all active reminders. Fire any whose due time has passed.
    Marks them done or advances recurring ones.
    """
    from core.data import compute_next_recur_date

    now  = _now_local()
    data, reminders = _load_reminders()

    fired_any = False
    for r in reminders:
        if r.get("done"):
            continue
        due_dt = _reminder_due_datetime(r)
        if due_dt is None:
            continue
        if now >= due_dt:
            # Fire the reminder
            recur = r.get("recur", "none")
            text  = r.get("text", "(reminder)")

            recur_label = RECUR_LABELS.get(recur, "") if recur != "none" else ""
            suffix      = f" _(🔁 {recur_label})_" if recur_label else ""

            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"⏰ *Reminder:* {text}{suffix}",
                    parse_mode="Markdown",
                )
            except Exception as e:
                logger.warning(f"check_and_fire_reminders: send failed: {e}")

            if recur and recur != "none":
                # Advance to next occurrence
                from_date = due_dt.date()
                next_date = compute_next_recur_date(recur, from_date=from_date)
                if next_date:
                    r["recur_next"] = next_date
                    # Keep time component if original had one
                    if "T" in (r.get("due") or ""):
                        time_part = r["due"].split("T")[1] if "T" in r["due"] else "09:00"
                        r["due"]  = f"{next_date}T{time_part}"
                    else:
                        r["due"] = next_date
                else:
                    r["done"] = True
            else:
                r["done"] = True

            fired_any = True

    if fired_any:
        _save_reminders(data)


# ─────────────────────────────────────────────────────────────────────────────
# INTENT HANDLER
# ─────────────────────────────────────────────────────────────────────────────

async def handle_reminder_intent(
    intent:   str,
    entities: dict,
    update:   Update,
    context:  ContextTypes.DEFAULT_TYPE,
) -> None:
    """Dispatch all REMINDER_* intents."""

    data, reminders = _load_reminders()

    # ── REMINDER_ADD ──────────────────────────────────────────────────────────
    if intent == REMINDER_ADD:
        text  = entities.get("text", "").strip()
        if not text:
            await update.message.reply_text(
                "What should I remind you about? Try: \"remind me to call mom tomorrow at 3pm\""
            )
            return

        raw_due = entities.get("due", "")
        due     = _parse_due(raw_due)
        recur   = entities.get("recur") or "none"
        now_str = _now_local().strftime("%Y-%m-%dT%H:%M")

        new_r = {
            "id":         _next_id(reminders),
            "text":       text,
            "due":        due,
            "done":       False,
            "recur":      recur,
            "recur_next": due[:10] if due else None,
            "added":      now_str,
        }
        data.setdefault("reminders", []).append(new_r)
        _save_reminders(data)

        extras = []
        if due:
            if "T" in due:
                extras.append(f"📅 {due.replace('T', ' ')}")
            else:
                extras.append(f"📅 {due}")
        if recur and recur != "none":
            extras.append(f"🔁 {RECUR_LABELS.get(recur, recur)}")

        suffix = f" _({', '.join(extras)})_" if extras else ""
        await update.message.reply_text(
            f"⏰ Reminder set: *{text}*{suffix}",
            parse_mode="Markdown",
        )
        return

    # ── REMINDER_LIST ─────────────────────────────────────────────────────────
    if intent == REMINDER_LIST:
        await update.message.reply_text(
            _format_reminder_list(reminders),
            parse_mode="Markdown",
        )
        return

    # ── REMINDER_DONE ─────────────────────────────────────────────────────────
    if intent == REMINDER_DONE:
        number = entities.get("number")
        text   = entities.get("text", "").strip()
        r      = _find_reminder(reminders, text or None, number)

        if not r:
            active = [x for x in reminders if not x.get("done")]
            if not active:
                await update.message.reply_text("No active reminders.")
                return
            await update.message.reply_text(
                "Which reminder is done? Try: \"done with reminder 2\"\n"
                "Run /reminders to see your list."
            )
            return

        r["done"] = True
        _save_reminders(data)
        await update.message.reply_text(
            f"✓ Done: _{r['text']}_",
            parse_mode="Markdown",
        )
        return

    # ── REMINDER_DELETE ────────────────────────────────────────────────────────
    if intent == REMINDER_DELETE:
        number = entities.get("number")
        text   = entities.get("text", "").strip()
        r      = _find_reminder(reminders, text or None, number)

        if not r:
            await update.message.reply_text(
                "Which reminder should I delete? "
                "Try: \"delete reminder 2\" or run /reminders to see your list."
            )
            return

        data["reminders"] = [x for x in reminders if x.get("id") != r.get("id")]
        _save_reminders(data)
        await update.message.reply_text(
            f"✓ Deleted: _{r['text']}_",
            parse_mode="Markdown",
        )
        return

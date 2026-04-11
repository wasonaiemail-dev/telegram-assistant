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

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from core.alfred_context import AlfredContext
from core.config import BOT_NAME, TIMEZONE, RECUR_LABELS
from core.intent import (
    REMINDER_ADD, REMINDER_LIST, REMINDER_DONE, REMINDER_DELETE,
)

# HP1: day-of-week name lookup (Mon=0 … Sun=6)
_DOW_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# DATA HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _now_local() -> datetime.datetime:
    return datetime.datetime.now(ZoneInfo(TIMEZONE))


def _next_id(reminders: list) -> int:
    if not reminders:
        return 1
    max_id = 0
    for r in reminders:
        try:
            max_id = max(max_id, int(r.get("id", 0)))
        except (ValueError, TypeError):
            pass
    return max_id + 1


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
    due_str = str(due_str).strip()

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
    due = str(due)
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
            d = datetime.date.fromisoformat(str(due)[:10])
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
        recur_label = RECUR_LABELS.get(recur, recur)
        # HP1: show "every Monday" instead of generic "weekly" for day-specific recurrences
        recur_day = r.get("recur_day")
        if recur == "weekly" and recur_day is not None:
            recur_label = f"every {_DOW_NAMES[int(recur_day)]}"
        extras.append(f"🔁 {recur_label}")

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
    Attaches a Snooze inline button (HP2) using the configured snooze duration.
    """
    from core.data import compute_next_recur_date, load_data, get_reminder_settings

    now  = _now_local()
    data, reminders = _load_reminders()

    # HP2: get configured snooze duration
    snooze_mins = get_reminder_settings(load_data()).get("snooze_minutes", 10)

    fired_any = False
    for r in reminders:
        if r.get("done"):
            continue
        due_dt = _reminder_due_datetime(r)
        if due_dt is None:
            continue
        if now >= due_dt:
            # Fire the reminder
            recur     = r.get("recur", "none")
            recur_day = r.get("recur_day")   # HP1: day-of-week (0=Mon…6=Sun)
            text      = r.get("text", "(reminder)")

            # HP1: show "every Monday" label for day-specific weekly recurrences
            if recur != "none":
                if recur == "weekly" and recur_day is not None:
                    recur_label = f"every {_DOW_NAMES[int(recur_day)]}"
                else:
                    recur_label = RECUR_LABELS.get(recur, recur)
                suffix = f" _(🔁 {recur_label})_"
            else:
                suffix = ""

            # HP2: snooze button on the fired message
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"💤 Snooze {snooze_mins}min",
                    callback_data=f"rem_snooze_{r['id']}_{snooze_mins}",
                ),
                InlineKeyboardButton("✓ Done", callback_data=f"rem_done_{r['id']}"),
            ]])

            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"⏰ *Reminder:* {text}{suffix}",
                    parse_mode="Markdown",
                    reply_markup=keyboard,
                )
            except Exception as e:
                logger.warning(f"check_and_fire_reminders: send failed: {e}")

            if recur and recur != "none":
                # HP1: advance to next occurrence, passing recur_day for day-specific weekly
                from_date = due_dt.date()
                next_date = compute_next_recur_date(
                    recur, from_date=from_date, recur_day=recur_day
                )
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


async def handle_reminder_callback(update, context) -> None:
    """
    Handle inline button callbacks from fired reminder messages.
    Patterns:
      rem_snooze_<id>_<minutes>  — postpone reminder by <minutes>
      rem_done_<id>              — mark reminder done
    HP2: snooze callback.
    """
    query = update.callback_query
    await query.answer()
    cb = query.data or ""

    data, reminders = _load_reminders()
    now = _now_local()

    if cb.startswith("rem_snooze_"):
        # rem_snooze_<id>_<minutes>
        parts = cb.split("_")
        try:
            rem_id    = int(parts[2])
            snooze_m  = int(parts[3]) if len(parts) > 3 else 10
        except (ValueError, IndexError):
            await query.edit_message_text("Couldn't parse snooze request.")
            return

        r = next((x for x in reminders if x.get("id") == rem_id), None)
        if not r:
            await query.edit_message_text("Reminder not found.")
            return

        new_due = now + datetime.timedelta(minutes=snooze_m)
        new_due_str = new_due.strftime("%Y-%m-%dT%H:%M")
        r["due"]        = new_due_str
        r["recur_next"] = new_due_str[:10]
        r["done"]       = False
        _save_reminders(data)
        await query.edit_message_text(
            f"💤 Snoozed _{r['text']}_ for {snooze_m} minutes.",
            parse_mode="Markdown",
        )

    elif cb.startswith("rem_done_"):
        try:
            rem_id = int(cb.split("_")[2])
        except (ValueError, IndexError):
            await query.edit_message_text("Couldn't parse done request.")
            return

        r = next((x for x in reminders if x.get("id") == rem_id), None)
        if not r:
            await query.edit_message_text("Reminder not found.")
            return

        r["done"] = True
        _save_reminders(data)
        await query.edit_message_text(
            f"✓ Done: _{r['text']}_",
            parse_mode="Markdown",
        )


# ─────────────────────────────────────────────────────────────────────────────
# INTENT HANDLER
# ─────────────────────────────────────────────────────────────────────────────

async def handle_reminder_intent(
    intent:   str,
    entities: dict,
    ctx:      AlfredContext,
) -> None:
    """Dispatch all REMINDER_* intents."""

    data, reminders = _load_reminders()

    # ── REMINDER_ADD ──────────────────────────────────────────────────────────
    if intent == REMINDER_ADD:
        text  = entities.get("text", "").strip()
        if not text:
            await ctx.reply('What should I remind you about? Try: "remind me to call mom tomorrow at 3pm"')
            return

        raw_due   = entities.get("due", "")
        due       = _parse_due(raw_due)
        recur     = entities.get("recur") or "none"
        # HP1: day-of-week specific weekly recurrence (0=Mon…6=Sun)
        recur_day_raw = entities.get("recur_day")
        recur_day = int(recur_day_raw) if recur_day_raw is not None else None

        # HP1: if recur_day given without explicit recur, default to weekly
        if recur_day is not None and recur == "none":
            recur = "weekly"

        # HP1: if no due date set and recur_day given, auto-set first occurrence
        if due is None and recur_day is not None:
            from core.data import compute_next_recur_date as _cnrd
            import datetime as _dt
            tz_now = _now_local()
            # Find next occurrence starting from today (inclusive)
            candidate = tz_now.date()
            if candidate.weekday() == recur_day:
                # Today is the right day — use today (if no time specified, 9am)
                first_date = candidate.isoformat()
            else:
                first_date = _cnrd("weekly", from_date=candidate - _dt.timedelta(days=1), recur_day=recur_day)
            due = first_date

        now_str = _now_local().strftime("%Y-%m-%dT%H:%M")

        new_r = {
            "id":         _next_id(reminders),
            "text":       text,
            "due":        due,
            "done":       False,
            "recur":      recur,
            "recur_day":  recur_day,   # HP1: day-of-week (0=Mon…6=Sun) or None
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
            # HP1: show "every Monday" label for day-specific recurrences
            if recur == "weekly" and recur_day is not None:
                extras.append(f"🔁 every {_DOW_NAMES[recur_day]}")
            else:
                extras.append(f"🔁 {RECUR_LABELS.get(recur, recur)}")

        suffix = f" _({', '.join(extras)})_" if extras else ""
        await ctx.reply_markdown(f"⏰ Reminder set: *{text}*{suffix}")
        return

    # ── REMINDER_LIST ─────────────────────────────────────────────────────────
    if intent == REMINDER_LIST:
        await ctx.reply_markdown(_format_reminder_list(reminders))
        return

    # ── REMINDER_DONE ─────────────────────────────────────────────────────────
    if intent == REMINDER_DONE:
        number = entities.get("number")
        text   = entities.get("text", "").strip()
        r      = _find_reminder(reminders, text or None, number)

        if not r:
            active = [x for x in reminders if not x.get("done")]
            if not active:
                await ctx.reply("No active reminders.")
                return
            await ctx.reply('Which reminder is done? Try: "done with reminder 2"\nRun /reminders to see your list.')
            return

        r["done"] = True
        _save_reminders(data)
        await ctx.reply_markdown(f"✓ Done: _{r['text']}_")
        return

    # ── REMINDER_DELETE ────────────────────────────────────────────────────────
    if intent == REMINDER_DELETE:
        number = entities.get("number")
        text   = entities.get("text", "").strip()
        r      = _find_reminder(reminders, text or None, number)

        if not r:
            await ctx.reply('Which reminder should I delete? Try: "delete reminder 2" or run /reminders to see your list.')
            return

        data["reminders"] = [x for x in reminders if x.get("id") != r.get("id")]
        _save_reminders(data)
        await ctx.reply_markdown(f"✓ Deleted: _{r['text']}_")
        return

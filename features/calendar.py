"""
alfred/features/calendar.py
============================
Calendar view and event management via Google Calendar.

COMMANDS
────────
  /cal                      — today's events
  /cal week                 — this week's events
  /cal [N]days              — next N days (e.g. /cal 3days)

INTENT HANDLER
──────────────
  handle_calendar_intent(intent, entities, update, context)

  Supported intents:
    CAL_VIEW    — "what's on my calendar" / "show my schedule"
                  entities: {"range": "today|week|tomorrow|N days"}
    CAL_ADD     — "add a meeting with John on Friday at 2pm"
                  entities: {"title": "...", "start": "YYYY-MM-DDTHH:MM",
                             "end": "YYYY-MM-DDTHH:MM", "location": "...",
                             "description": "...", "recur": "..."}
    CAL_DELETE  — "cancel my 3pm meeting"
                  entities: {"title": "...", "date": "YYYY-MM-DD"}
    CAL_UPDATE  — "move the 3pm meeting to 4pm"
                  entities: {"title": "...", "new_start": "...", "new_end": "..."}

QUICK ADD
─────────
  When entities are sparse (e.g. only a title with no time), Alfred falls
  back to Google Calendar's Quick Add API, which parses natural language
  like "Team standup tomorrow at 9am for 30 minutes".
"""

import logging
import datetime
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import ContextTypes

from core.config import BOT_NAME, TIMEZONE
from core.intent import CAL_VIEW, CAL_ADD, CAL_DELETE, CAL_UPDATE

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _get_service():
    from core.google_auth import get_calendar_service
    return get_calendar_service()


def _auth_error_msg() -> str:
    return "❌ Google Calendar isn't connected. Run /auth to connect your Google account."


def _now_local() -> datetime.datetime:
    return datetime.datetime.now(ZoneInfo(TIMEZONE))


def _parse_range(raw: str | None) -> tuple[datetime.datetime, datetime.datetime]:
    """
    Parse a range string into (start_dt, end_dt).
    Supported: "today", "tomorrow", "week", "N days" (e.g. "3 days").
    Defaults to today.
    """
    import pytz
    tz    = pytz.timezone(TIMEZONE)
    now   = datetime.datetime.now(tz)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    raw = (raw or "today").lower().strip()

    if raw == "today" or not raw:
        end = start + datetime.timedelta(days=1)
    elif raw == "tomorrow":
        start = start + datetime.timedelta(days=1)
        end   = start + datetime.timedelta(days=1)
    elif raw == "week":
        end = start + datetime.timedelta(days=7)
    else:
        # Try "N days"
        try:
            n   = int(raw.replace("days", "").replace("day", "").strip())
            end = start + datetime.timedelta(days=max(1, n))
        except ValueError:
            end = start + datetime.timedelta(days=1)

    return start, end


def _format_range_label(raw: str | None) -> str:
    raw = (raw or "today").lower().strip()
    if raw == "today":
        return "Today"
    if raw == "tomorrow":
        return "Tomorrow"
    if raw == "week":
        return "This Week"
    return f"Next {raw}"


# ─────────────────────────────────────────────────────────────────────────────
# /cal COMMAND
# ─────────────────────────────────────────────────────────────────────────────

async def cmd_cal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /cal [today | tomorrow | week | Ndays] — alias for cmd_calendar
    """
    await cmd_calendar(update, context)


async def cmd_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /calendar [today | tomorrow | week | Ndays]
    """
    args = context.args or []
    raw  = " ".join(args).strip() if args else "today"

    svc = _get_service()
    if not svc:
        await update.message.reply_text(_auth_error_msg())
        return

    await _send_calendar_view(update.message.reply_text, svc, raw)


async def _send_calendar_view(reply_fn, svc, raw_range: str) -> None:
    """Fetch and format events for a given range string."""
    from adapters.google_calendar import get_events_range, format_event_brief

    try:
        start, end = _parse_range(raw_range)
        events     = get_events_range(svc, start, end)
    except Exception as e:
        logger.error(f"_send_calendar_view: {e}")
        await reply_fn("Sorry, I couldn't load your calendar right now.")
        return

    label = _format_range_label(raw_range)

    if not events:
        await reply_fn(
            f"📅 *{label}*\n  No events.",
            parse_mode="Markdown",
        )
        return

    lines = [f"📅 *{label}* ({len(events)} event(s))"]
    for ev in events:
        lines.append(f"  • {format_event_brief(ev)}")

    await reply_fn("\n".join(lines), parse_mode="Markdown")


# ─────────────────────────────────────────────────────────────────────────────
# INTENT HANDLER
# ─────────────────────────────────────────────────────────────────────────────

async def handle_calendar_intent(
    intent:   str,
    entities: dict,
    update:   Update,
    context:  ContextTypes.DEFAULT_TYPE,
) -> None:
    """Dispatch all CAL_* intents."""

    svc = _get_service()
    if not svc:
        await update.message.reply_text(_auth_error_msg())
        return

    # ── CAL_VIEW ──────────────────────────────────────────────────────────────
    if intent == CAL_VIEW:
        raw_range = entities.get("range", "today")
        await _send_calendar_view(update.message.reply_text, svc, raw_range)
        return

    # ── CAL_ADD ───────────────────────────────────────────────────────────────
    if intent == CAL_ADD:
        title       = entities.get("title", "").strip()
        start_str   = entities.get("start", "").strip()
        end_str     = entities.get("end", "").strip()
        location    = entities.get("location", "")
        description = entities.get("description", "")
        recur       = entities.get("recur", "")

        if not title:
            await update.message.reply_text(
                "What's the event title? Try: \"add [title] on [date] at [time]\""
            )
            return

        # Use Quick Add if we don't have a clean start time
        if not start_str:
            from adapters.google_calendar import quick_add_event
            result = quick_add_event(svc, title)
            if result:
                from adapters.google_calendar import format_event_brief
                await update.message.reply_text(
                    f"✅ Added: *{format_event_brief(result)}*",
                    parse_mode="Markdown",
                )
            else:
                await update.message.reply_text(
                    f"Sorry, I couldn't add that event. Try being more specific:\n"
                    f"\"add [title] on [date] at [time]\""
                )
            return

        # We have a start time — use create_event
        try:
            import pytz
            tz        = pytz.timezone(TIMEZONE)
            start_dt  = datetime.datetime.fromisoformat(start_str)
            if start_dt.tzinfo is None:
                start_dt = tz.localize(start_dt)

            if end_str:
                end_dt = datetime.datetime.fromisoformat(end_str)
                if end_dt.tzinfo is None:
                    end_dt = tz.localize(end_dt)
            else:
                end_dt = start_dt + datetime.timedelta(hours=1)  # default 1h

        except ValueError as e:
            await update.message.reply_text(
                f"I couldn't parse that date/time. Try: \"[title] on March 15 at 2pm\""
            )
            return

        kwargs = {"location": location, "description": description}
        if recur:
            from adapters.google_calendar import create_recurring_event
            result = create_recurring_event(
                svc, title, start_dt, end_dt, recur, **kwargs
            )
        else:
            from adapters.google_calendar import create_event
            result = create_event(svc, title, start_dt, end_dt, **kwargs)

        if result:
            from adapters.google_calendar import format_event_brief
            await update.message.reply_text(
                f"✅ Added: *{format_event_brief(result)}*",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text("Couldn't create that event. Please try again.")
        return

    # ── CAL_DELETE ────────────────────────────────────────────────────────────
    if intent == CAL_DELETE:
        title     = entities.get("title", "").strip()
        date_str  = entities.get("date", "")

        if not title:
            await update.message.reply_text(
                "Which event should I cancel? Try: \"cancel my 3pm meeting\""
            )
            return

        from adapters.google_calendar import find_event_by_title, delete_event, format_event_brief

        # Search within a reasonable window (today ± 7 days)
        now    = _now_local()
        start  = now - datetime.timedelta(days=1)
        end    = now + datetime.timedelta(days=7)

        match = find_event_by_title(svc, title, start=start, end=end)
        if not match:
            await update.message.reply_text(
                f"I couldn't find an event matching \"{title}\". "
                f"Run /cal week to see upcoming events."
            )
            return

        brief  = format_event_brief(match)
        cal_id = match.get("_calendar_id", "primary")
        if delete_event(svc, match["id"], calendar_id=cal_id):
            await update.message.reply_text(
                f"✅ Cancelled: *{brief}*",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text("Couldn't cancel that event. Try again.")
        return

    # ── CAL_UPDATE ────────────────────────────────────────────────────────────
    if intent == CAL_UPDATE:
        title     = entities.get("title", "").strip()
        new_start = entities.get("new_start", "").strip()
        new_end   = entities.get("new_end", "").strip()

        if not title:
            await update.message.reply_text(
                "Which event should I update? Try: \"move my 3pm meeting to 4pm\""
            )
            return

        from adapters.google_calendar import find_event_by_title, update_event, format_event_brief

        now   = _now_local()
        start = now - datetime.timedelta(days=1)
        end   = now + datetime.timedelta(days=7)

        match = find_event_by_title(svc, title, start=start, end=end)
        if not match:
            await update.message.reply_text(
                f"I couldn't find an event matching \"{title}\". "
                f"Run /cal week to see upcoming events."
            )
            return

        update_fields: dict = {}
        try:
            import pytz
            tz = pytz.timezone(TIMEZONE)
            if new_start:
                ns = datetime.datetime.fromisoformat(new_start)
                if ns.tzinfo is None:
                    ns = tz.localize(ns)
                update_fields["start"] = ns
            if new_end:
                ne = datetime.datetime.fromisoformat(new_end)
                if ne.tzinfo is None:
                    ne = tz.localize(ne)
                update_fields["end"] = ne
        except ValueError:
            await update.message.reply_text(
                "I couldn't parse the new time. Try: \"move [title] to [time]\""
            )
            return

        if not update_fields:
            await update.message.reply_text(
                "What should I change? I can update the start time, end time, "
                "title, or location. Try: \"move [event] to [new time]\""
            )
            return

        cal_id = match.get("_calendar_id", "primary")
        result = update_event(svc, match["id"], calendar_id=cal_id, **update_fields)
        if result:
            await update.message.reply_text(
                f"✅ Updated: *{format_event_brief(result)}*",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text("Couldn't update that event. Try again.")
        return

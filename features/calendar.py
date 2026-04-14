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

from core.alfred_context import AlfredContext
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


def _try_parse_specific_date(
    raw: str,
    now: datetime.datetime,
    tz,
) -> datetime.datetime | None:
    """
    Try to parse a specific date string like "May 10", "May 10th", "2026-05-10".
    Returns a timezone-aware midnight datetime, or None if it can't be parsed.
    """
    import re
    # Strip ordinal suffixes: "10th" → "10", "3rd" → "3"
    clean = re.sub(r"(\d+)(?:st|nd|rd|th)\b", r"\1", raw.strip())

    # ISO date: "2026-05-10"
    try:
        d = datetime.datetime.strptime(clean, "%Y-%m-%d")
        return tz.localize(d)
    except ValueError:
        pass

    # "Month D" or "Month DD": "May 10", "january 3"
    for fmt in ("%B %d", "%b %d"):
        try:
            d = datetime.datetime.strptime(clean.title(), fmt)
            d = d.replace(year=now.year)
            # If the date is already past this year, assume next year
            if d.date() < now.date():
                d = d.replace(year=now.year + 1)
            return tz.localize(d)
        except ValueError:
            pass

    # "Month DD YYYY": "May 10 2026"
    for fmt in ("%B %d %Y", "%b %d %Y"):
        try:
            d = datetime.datetime.strptime(clean.title(), fmt)
            return tz.localize(d)
        except ValueError:
            pass

    return None


def _parse_range(raw: str | None) -> tuple[datetime.datetime, datetime.datetime]:
    """
    Parse a range string into (start_dt, end_dt).
    Supported: "today", "tomorrow", "week", "weekend", "restofday", "N days",
               specific dates ("May 10", "may 10th", "2026-05-10").
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
    elif raw == "weekend":
        # Next Saturday and Sunday from today
        days_to_sat = (5 - now.weekday()) % 7
        if days_to_sat == 0 and now.weekday() == 5:
            days_to_sat = 0  # today is Saturday
        sat   = start + datetime.timedelta(days=days_to_sat)
        start = sat
        end   = sat + datetime.timedelta(days=2)  # Sat + Sun
    elif raw == "restofday":
        # From right now until midnight
        start = now
        end   = now.replace(hour=23, minute=59, second=59, microsecond=0)
    else:
        # Try "N days" first
        try:
            n   = int(raw.replace("days", "").replace("day", "").strip())
            end = start + datetime.timedelta(days=max(1, n))
        except ValueError:
            # Try specific date ("May 10", "2026-05-10", etc.)
            parsed = _try_parse_specific_date(raw, now, tz)
            if parsed:
                start = parsed.replace(hour=0, minute=0, second=0, microsecond=0)
                end   = start + datetime.timedelta(days=1)
            else:
                end = start + datetime.timedelta(days=1)

    return start, end


def _format_range_label(raw: str | None) -> str:
    import pytz, re
    raw = (raw or "today").lower().strip()
    if raw == "today":
        return "Today"
    if raw == "tomorrow":
        return "Tomorrow"
    if raw == "week":
        return "This Week"
    if raw == "weekend":
        return "This Weekend"
    if raw == "restofday":
        return "Rest of Today"
    # N days: "7days" → "Next 7 Days"
    days_match = re.fullmatch(r"(\d+)\s*days?", raw)
    if days_match:
        n = int(days_match.group(1))
        return f"Next {n} Day{'s' if n != 1 else ''}"
    # Specific date: try to parse and format nicely ("May 10" → "Saturday May 10")
    try:
        tz  = pytz.timezone(TIMEZONE)
        now = datetime.datetime.now(tz)
        dt  = _try_parse_specific_date(raw, now, tz)
        if dt:
            return dt.strftime("%A, %B %-d")
    except Exception:
        pass
    return raw.title()


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
    ctx:      AlfredContext,
) -> None:
    """Dispatch all CAL_* intents."""

    svc = _get_service()
    if not svc:
        await ctx.reply(_auth_error_msg())
        return

    # ── CAL_VIEW ──────────────────────────────────────────────────────────────
    if intent == CAL_VIEW:
        # Accept both "range" (new) and legacy "period" key from GPT/keyword paths
        raw_range = entities.get("range") or entities.get("period", "today")
        await _send_calendar_view(ctx.reply, svc, raw_range)
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
            await ctx.reply("What's the event title? Try: \"add [title] on [date] at [time]\"")
            return

        # Use Quick Add if we don't have a clean start time
        if not start_str:
            from adapters.google_calendar import quick_add_event
            result = quick_add_event(svc, title)
            if result:
                from adapters.google_calendar import format_event_brief
                await ctx.reply(f"✅ Added: *{format_event_brief(result)}*",
                    parse_mode="Markdown",
                )
            else:
                await ctx.reply(f"Sorry, I couldn't add that event. Try being more specific:\n"
                    f"\"add [title] on [date] at [time]\"")
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
            await ctx.reply(f"I couldn't parse that date/time. Try: \"[title] on March 15 at 2pm\"")
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
            await ctx.reply(f"✅ Added: *{format_event_brief(result)}*",
                parse_mode="Markdown",
            )
        else:
            await ctx.reply("Couldn't create that event. Please try again.")
        return

    # ── CAL_DELETE ────────────────────────────────────────────────────────────
    if intent == CAL_DELETE:
        title     = entities.get("title", "").strip()
        date_str  = entities.get("date", "")

        if not title:
            await ctx.reply("Which event should I cancel? Try: \"cancel my 3pm meeting\"")
            return

        from adapters.google_calendar import find_event_by_title, delete_event, format_event_brief

        # Search within a reasonable window (today ± 7 days)
        now    = _now_local()
        start  = now - datetime.timedelta(days=1)
        end    = now + datetime.timedelta(days=7)

        match = find_event_by_title(svc, title, start=start, end=end)
        if not match:
            await ctx.reply(f"I couldn't find an event matching \"{title}\". "
                f"Run /cal week to see upcoming events.")
            return

        brief  = format_event_brief(match)
        cal_id = match.get("_calendar_id", "primary")
        if delete_event(svc, match["id"], calendar_id=cal_id):
            await ctx.reply_markdown(f"✅ Cancelled: *{brief}*")
        else:
            await ctx.reply("Couldn't cancel that event. Try again.")
        return

    # ── CAL_UPDATE ────────────────────────────────────────────────────────────
    if intent == CAL_UPDATE:
        title     = entities.get("title", "").strip()
        new_start = entities.get("new_start", "").strip()
        new_end   = entities.get("new_end", "").strip()

        if not title:
            await ctx.reply("Which event should I update? Try: \"move my 3pm meeting to 4pm\"")
            return

        from adapters.google_calendar import find_event_by_title, update_event, format_event_brief

        now   = _now_local()
        start = now - datetime.timedelta(days=1)
        end   = now + datetime.timedelta(days=7)

        match = find_event_by_title(svc, title, start=start, end=end)
        if not match:
            await ctx.reply(f"I couldn't find an event matching \"{title}\". "
                f"Run /cal week to see upcoming events.")
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
            await ctx.reply("I couldn't parse the new time. Try: \"move [title] to [time]\"")
            return

        if not update_fields:
            await ctx.reply("What should I change? I can update the start time, end time, "
                "title, or location. Try: \"move [event] to [new time]\"")
            return

        cal_id = match.get("_calendar_id", "primary")
        result = update_event(svc, match["id"], calendar_id=cal_id, **update_fields)
        if result:
            await ctx.reply(f"✅ Updated: *{format_event_brief(result)}*",
                parse_mode="Markdown",
            )
        else:
            await ctx.reply("Couldn't update that event. Try again.")
        return

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

from core.config import BOT_NAME, TIMEZONE, CALENDAR_NAMES
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


def _parse_datetime_flexible(raw: str, reference: datetime.datetime | None = None) -> datetime.datetime | None:
    """
    Parse a datetime string that may be ISO, a natural-language time like "4pm",
    or a relative expression like "tomorrow at 3pm".

    Returns a timezone-aware datetime in TIMEZONE, or None on failure.
    Uses dateutil.parser with today's date as the default so bare times like
    "4pm" resolve to today-at-4pm rather than erroring.
    """
    if not raw:
        return None
    import pytz
    from dateutil import parser as _du_parser
    from dateutil.parser import ParserError

    tz = pytz.timezone(TIMEZONE)
    now = reference or datetime.datetime.now(tz)

    # Strip common NL prefixes ("to ", "at ", "on ") so dateutil doesn't choke
    clean = raw.strip()

    try:
        # dateutil handles ISO strings, "4pm", "4:30 PM", "Monday at 2pm", etc.
        # default= sets the date component when only a time is given (e.g. "4pm")
        default_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if default_dt.tzinfo is None:
            default_dt = tz.localize(default_dt)
        parsed = _du_parser.parse(clean, default=default_dt.replace(tzinfo=None))
        if parsed.tzinfo is None:
            parsed = tz.localize(parsed)
        else:
            parsed = parsed.astimezone(tz)
        return parsed
    except (ParserError, ValueError, OverflowError):
        return None


def _resolve_write_calendar(calendar_hint: str) -> str:
    """
    Resolve a friendly calendar name (e.g. "work", "family") to a Google Calendar ID.
    Falls back to "primary" if the name isn't in CALENDAR_NAMES or the dict is empty.
    """
    if not calendar_hint:
        return "primary"
    key = calendar_hint.strip().lower()
    # Check CALENDAR_NAMES first
    for name, cal_id in CALENDAR_NAMES.items():
        if key in name.lower() or name.lower() in key:
            return cal_id
    # Check CALENDAR_IDS by position ("second calendar", "calendar 2", etc.)
    return "primary"


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
        title        = entities.get("title", "").strip()
        start_str    = entities.get("start", "").strip()
        end_str      = entities.get("end", "").strip()
        location     = entities.get("location", "")
        description  = entities.get("description", "")
        recur        = entities.get("recur", "")
        cal_hint     = entities.get("calendar", "")   # e.g. "work", "family"

        if not title:
            await ctx.reply("What's the event title? Try: \"add [title] on [date] at [time]\"")
            return

        # Resolve target calendar (defaults to primary)
        write_cal_id = _resolve_write_calendar(cal_hint)

        # GPT may return separate date + time instead of a unified start ISO string.
        # Merge them into start_str so the flexible parser handles both paths.
        if not start_str:
            date_part = entities.get("date", "").strip()
            time_part = entities.get("time", "").strip()
            if date_part and time_part:
                start_str = f"{date_part} at {time_part}"
            elif date_part:
                start_str = date_part
            elif time_part:
                start_str = time_part

        # No date/time at all → Google Quick Add with full NL string
        # Always pass the full phrase so Google's NL parser resolves the date correctly.
        if not start_str:
            from adapters.google_calendar import quick_add_event
            result = quick_add_event(svc, title, calendar_id=write_cal_id)
            if result:
                from adapters.google_calendar import format_event_brief
                cal_label = f" → _{cal_hint}_ calendar" if cal_hint else ""
                await ctx.reply(f"✅ Added: *{format_event_brief(result)}*{cal_label}",
                    parse_mode="Markdown",
                )
            else:
                await ctx.reply(f"Sorry, I couldn't add that event. Try being more specific:\n"
                    f"\"add [title] on [date] at [time]\"")
            return

        # We have a start time string — use flexible parser (handles ISO + NL like "4pm")
        now = _now_local()
        start_dt = _parse_datetime_flexible(start_str, reference=now)
        if not start_dt:
            # dateutil couldn't parse it — pass full phrase to Google quick_add as last resort
            from adapters.google_calendar import quick_add_event, format_event_brief
            quick_text = f"{title} {start_str}"
            result = quick_add_event(svc, quick_text, calendar_id=write_cal_id)
            if result:
                cal_label = f" → _{cal_hint}_ calendar" if cal_hint else ""
                await ctx.reply(f"✅ Added: *{format_event_brief(result)}*{cal_label}",
                    parse_mode="Markdown",
                )
            else:
                await ctx.reply(f"I couldn't parse \"{start_str}\" as a date/time. "
                    "Try: \"[title] on March 15 at 2pm\"")
            return

        end_dt = _parse_datetime_flexible(end_str, reference=now) if end_str else None
        if not end_dt:
            end_dt = start_dt + datetime.timedelta(hours=1)  # default 1h

        kwargs = {"location": location, "description": description}
        if recur:
            from adapters.google_calendar import create_recurring_event
            result = create_recurring_event(
                svc, title, start_dt, end_dt, recur,
                calendar_id=write_cal_id, **kwargs
            )
        else:
            from adapters.google_calendar import create_event
            result = create_event(
                svc, title, start_dt, end_dt,
                calendar_id=write_cal_id, **kwargs
            )

        if result:
            from adapters.google_calendar import format_event_brief
            cal_label = f" → _{cal_hint}_ calendar" if cal_hint else ""
            await ctx.reply(f"✅ Added: *{format_event_brief(result)}*{cal_label}",
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
        title        = entities.get("title", "").strip()
        new_start    = entities.get("new_start", "").strip()
        new_end      = entities.get("new_end", "").strip()
        new_title    = entities.get("new_title", "").strip()
        new_location = entities.get("new_location", "").strip()
        new_desc     = entities.get("new_description", "").strip()

        if not title:
            await ctx.reply(
                "Which event should I update?\n"
                "Examples:\n"
                "• \"move my 3pm meeting to 4pm\"\n"
                "• \"rename dentist to Annual Checkup\"\n"
                "• \"change location of dentist to 123 Main St\""
            )
            return

        from adapters.google_calendar import find_event_by_title, update_event, format_event_brief

        now   = _now_local()
        start = now - datetime.timedelta(days=1)
        end   = now + datetime.timedelta(days=14)   # wider window than delete

        match = find_event_by_title(svc, title, start=start, end=end)
        if not match:
            await ctx.reply(f"I couldn't find an event matching \"{title}\". "
                f"Run /cal week to see upcoming events.")
            return

        update_fields: dict = {}

        # ── Time changes: use flexible parser so "4pm", "tomorrow at 3pm" all work
        if new_start:
            ns = _parse_datetime_flexible(new_start, reference=now)
            if ns is None:
                await ctx.reply(
                    f"I couldn't parse \"{new_start}\" as a time. "
                    "Try a format like \"4pm tomorrow\" or \"April 20 at 2pm\"."
                )
                return
            update_fields["start"] = ns
            # If a new end isn't specified, shift end by the same delta as start
            if not new_end:
                from adapters.google_calendar import get_event_start_dt, get_event_end_dt
                import pytz
                tz = pytz.timezone(TIMEZONE)
                old_start = get_event_start_dt(match, tz)
                old_end   = get_event_end_dt(match, tz)
                if old_start and old_end:
                    delta = old_end - old_start
                    update_fields["end"] = ns + delta

        if new_end:
            ne = _parse_datetime_flexible(new_end, reference=now)
            if ne is None:
                await ctx.reply(
                    f"I couldn't parse \"{new_end}\" as a time. "
                    "Try a format like \"5pm tomorrow\"."
                )
                return
            update_fields["end"] = ne

        # ── Field changes: title, location, description
        if new_title:
            update_fields["summary"] = new_title
        if new_location:
            update_fields["location"] = new_location
        if new_desc:
            update_fields["description"] = new_desc

        if not update_fields:
            await ctx.reply(
                "What should I change? I can update:\n"
                "• Time: \"move [event] to 4pm\"\n"
                "• Name: \"rename [event] to [new name]\"\n"
                "• Location: \"change location of [event] to [place]\"\n"
                "• Description: \"update description of [event] to [text]\""
            )
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

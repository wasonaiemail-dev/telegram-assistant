"""
alfred/adapters/google_calendar.py
====================================
Google Calendar full CRUD adapter — read, create, update, and delete events.

PUBLIC INTERFACE
────────────────
  Fetching
    get_events_range(service, start_dt, end_dt)
    get_todays_events(service)
    get_weeks_events(service)
    get_upcoming_events(service, hours_ahead)

  Creating
    create_event(service, title, start, end, ...)   full structured create
    quick_add_event(service, text)                  natural language create
                                                    e.g. "Dinner Friday 7pm"

  Updating
    update_event(service, event_id, **fields)       patch any field
    move_event(service, event_id, new_start, new_end)

  Deleting
    delete_event(service, event_id)

  Finding
    find_event_by_title(service, title, days_ahead)
    get_event_by_id(service, event_id)

  Analysis
    is_significant_event(event)
    is_travel_event(event)
    get_event_duration_minutes(event)
    get_event_start_dt(event, tz)
    get_event_end_dt(event, tz)
    is_all_day_event(event)
    get_attendee_count(event)
    extract_event_location(event)

  Pipelines
    get_events_needing_prep(service)
    get_travel_events(service, days_ahead)

  Formatting
    format_event_brief(event, tz)
    format_events_block(events, tz)
    format_event_detail(event, tz)
"""

import logging
import datetime

logger = logging.getLogger(__name__)

from core.config import (
    TIMEZONE,
    CALENDAR_IDS,
    MAX_EVENTS_PER_FETCH,
    HOME_CITY_KEYWORDS,
    EVENT_PREP_KEYWORDS,
    EVENT_PREP_SKIP_KEYWORDS,
    EVENT_PREP_MIN_DURATION_MINUTES,
    EVENT_PREP_HOURS_LOOKAHEAD,
    TRAVEL_DETECT_DAYS_AHEAD,
)

# The calendar used for all write operations (create/update/delete).
# Defaults to CALENDAR_IDS[0] — which is "primary" unless the buyer changed it.
# This ensures reads and writes always target the same calendar.
_PRIMARY_CALENDAR = CALENDAR_IDS[0] if CALENDAR_IDS else "primary"


# ═══════════════════════════════════════════════════════════════════════════════
# FETCH
# ═══════════════════════════════════════════════════════════════════════════════

def get_events_range(
    service,
    start_dt:    datetime.datetime,
    end_dt:      datetime.datetime,
    max_results: int | None = None,
) -> list[dict]:
    """
    Fetch all events across all configured CALENDAR_IDS between start_dt and end_dt.
    Both datetimes must be timezone-aware. Events sorted by start time.
    Returns [] on error.
    """
    if max_results is None:
        max_results = MAX_EVENTS_PER_FETCH

    all_events = []
    for cal_id in CALENDAR_IDS:
        try:
            result = service.events().list(
                calendarId=cal_id,
                timeMin=_to_rfc3339(start_dt),
                timeMax=_to_rfc3339(end_dt),
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            ).execute()
            events = result.get("items", [])
            for e in events:
                e["_calendar_id"] = cal_id
            all_events.extend(events)
        except Exception as ex:
            logger.error(f"get_events_range(cal={cal_id}): {ex}")

    if len(CALENDAR_IDS) > 1:
        all_events.sort(key=lambda e: _sort_key(e))

    return all_events


def get_todays_events(service) -> list[dict]:
    import pytz
    tz    = pytz.timezone(TIMEZONE)
    now   = datetime.datetime.now(tz)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end   = now.replace(hour=23, minute=59, second=59, microsecond=0)
    return get_events_range(service, start, end)


def get_weeks_events(service) -> list[dict]:
    import pytz
    tz    = pytz.timezone(TIMEZONE)
    now   = datetime.datetime.now(tz)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end   = start + datetime.timedelta(days=7)
    return get_events_range(service, start, end)


def get_upcoming_events(service, hours_ahead: int = 24) -> list[dict]:
    import pytz
    tz  = pytz.timezone(TIMEZONE)
    now = datetime.datetime.now(tz)
    end = now + datetime.timedelta(hours=hours_ahead)
    return get_events_range(service, now, end)


def get_event_by_id(service, event_id: str, calendar_id: str = "primary") -> dict | None:
    """Fetch a single event by its ID. Returns None on error."""
    try:
        return service.events().get(
            calendarId=calendar_id,
            eventId=event_id,
        ).execute()
    except Exception as e:
        logger.error(f"get_event_by_id({event_id}): {e}")
        return None


def find_event_by_title(
    service,
    title:       str,
    days_ahead:  int = 30,
) -> dict | None:
    """
    Find the next upcoming event whose summary contains `title` (case-insensitive).
    Searches within the next `days_ahead` days across all CALENDAR_IDS.
    Returns the first match (earliest start), or None if not found.
    """
    import pytz
    tz    = pytz.timezone(TIMEZONE)
    now   = datetime.datetime.now(tz)
    end   = now + datetime.timedelta(days=days_ahead)
    events = get_events_range(service, now, end, max_results=100)
    title_lower = title.lower()
    for e in events:
        if title_lower in e.get("summary", "").lower():
            return e
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# CREATE
# ═══════════════════════════════════════════════════════════════════════════════

def create_event(
    service,
    title:       str,
    start:       datetime.datetime,   # timezone-aware
    end:         datetime.datetime,   # timezone-aware
    description: str  = "",
    location:    str  = "",
    attendees:   list[str] = None,    # list of email strings
    all_day:     bool = False,
) -> dict | None:
    """
    Create a new calendar event on the primary calendar.

    For all-day events, pass all_day=True and set start/end to midnight on
    the relevant date(s). Alfred will convert them to the correct date format.

    Returns the created event dict (contains 'id', 'htmlLink', etc.) or None.
    """
    import pytz
    tz = pytz.timezone(TIMEZONE)

    if all_day:
        body = {
            "summary": title,
            "start":   {"date": start.strftime("%Y-%m-%d")},
            "end":     {"date": end.strftime("%Y-%m-%d")},
        }
    else:
        body = {
            "summary": title,
            "start": {
                "dateTime": start.isoformat(),
                "timeZone": TIMEZONE,
            },
            "end": {
                "dateTime": end.isoformat(),
                "timeZone": TIMEZONE,
            },
        }

    if description:
        body["description"] = description
    if location:
        body["location"] = location
    if attendees:
        body["attendees"] = [{"email": e} for e in attendees]

    try:
        event = service.events().insert(
            calendarId=_PRIMARY_CALENDAR,
            body=body,
        ).execute()
        logger.info(f"Created event: '{title}' (id={event.get('id')})")
        return event
    except Exception as e:
        logger.error(f"create_event('{title}'): {e}")
        return None


def create_recurring_event(
    service,
    title:       str,
    start:       datetime.datetime,
    end:         datetime.datetime,
    recurrence:  str,              # "daily" | "weekdays" | "weekly" | "monthly" | "yearly"
    description: str  = "",
    location:    str  = "",
    count:       int  | None = None,   # stop after N occurrences (None = forever)
    until:       str  | None = None,   # stop on this date "YYYY-MM-DD" (None = forever)
) -> dict | None:
    """
    Create a recurring calendar event.

    Args:
        recurrence: one of "daily", "weekdays", "weekly", "monthly", "yearly"
        count:      stop after this many occurrences (e.g. count=10)
        until:      stop on this ISO date e.g. "2026-12-31" (count takes precedence)

    Examples:
        create_recurring_event(svc, "Team standup", start, end, "weekdays")
        create_recurring_event(svc, "Monthly review", start, end, "monthly", count=12)

    Note: for complex recurrence (e.g. "every other Tuesday"), use quick_add_event()
    with natural language — Google's parser handles those cases better.

    Returns the created event dict, or None on error.
    """
    rrule_freq = {
        "daily":    "DAILY",
        "weekdays": "WEEKLY;BYDAY=MO,TU,WE,TH,FR",
        "weekly":   "WEEKLY",
        "monthly":  "MONTHLY",
        "yearly":   "YEARLY",
    }.get(recurrence.lower())

    if not rrule_freq:
        logger.error(f"create_recurring_event: unknown recurrence '{recurrence}'")
        return None

    rrule = f"RRULE:FREQ={rrule_freq}"
    if count:
        rrule += f";COUNT={count}"
    elif until:
        rrule += f";UNTIL={until.replace('-', '')}T000000Z"

    body = {
        "summary": title,
        "start": {
            "dateTime": start.isoformat(),
            "timeZone": TIMEZONE,
        },
        "end": {
            "dateTime": end.isoformat(),
            "timeZone": TIMEZONE,
        },
        "recurrence": [rrule],
    }
    if description:
        body["description"] = description
    if location:
        body["location"] = location

    try:
        event = service.events().insert(
            calendarId=_PRIMARY_CALENDAR,
            body=body,
        ).execute()
        logger.info(f"Created recurring event: '{title}' ({recurrence})")
        return event
    except Exception as e:
        logger.error(f"create_recurring_event('{title}'): {e}")
        return None


def quick_add_event(service, text: str) -> dict | None:
    """
    Create an event using Google Calendar's natural language quick-add API.

    Examples of valid `text`:
      "Dinner with Sarah Friday at 7pm"
      "Dentist appointment next Tuesday at 2pm for 1 hour"
      "Team standup every weekday at 9am"

    Google parses the text and extracts time, title, and recurrence.
    Returns the created event dict, or None on error.

    Note: quick_add only works with the primary calendar.
    """
    try:
        event = service.events().quickAdd(
            calendarId=_PRIMARY_CALENDAR,
            text=text,
        ).execute()
        logger.info(f"Quick-added event: '{text}' → id={event.get('id')}")
        return event
    except Exception as e:
        logger.error(f"quick_add_event('{text}'): {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# UPDATE
# ═══════════════════════════════════════════════════════════════════════════════

def update_event(
    service,
    event_id:    str,
    calendar_id: str = "primary",
    **fields,
) -> dict | None:
    """
    Patch arbitrary fields on an existing event.

    Common fields: summary, description, location,
                   start (dict), end (dict)

    Example:
        update_event(service, event_id, summary="New title")
        update_event(service, event_id,
                     start={"dateTime": "2026-04-10T15:00:00-07:00",
                             "timeZone": "America/Los_Angeles"})

    Returns the updated event dict, or None on error.
    """
    try:
        return service.events().patch(
            calendarId=calendar_id,
            eventId=event_id,
            body=fields,
        ).execute()
    except Exception as e:
        logger.error(f"update_event({event_id}, fields={list(fields.keys())}): {e}")
        return None


def move_event(
    service,
    event_id:    str,
    new_start:   datetime.datetime,
    new_end:     datetime.datetime,
    calendar_id: str = "primary",
) -> dict | None:
    """
    Reschedule an event to a new start and end time.
    Both datetimes must be timezone-aware.
    Returns the updated event dict, or None on error.
    """
    return update_event(
        service,
        event_id,
        calendar_id=calendar_id,
        start={
            "dateTime": new_start.isoformat(),
            "timeZone": TIMEZONE,
        },
        end={
            "dateTime": new_end.isoformat(),
            "timeZone": TIMEZONE,
        },
    )


# ═══════════════════════════════════════════════════════════════════════════════
# DELETE
# ═══════════════════════════════════════════════════════════════════════════════

def delete_event(
    service,
    event_id:    str,
    calendar_id: str = "primary",
) -> bool:
    """
    Permanently delete an event. Returns True on success, False on error.

    Note: Google Calendar moves deleted events to trash for ~30 days before
    permanent deletion, so this is recoverable in the Google Calendar UI.
    """
    try:
        service.events().delete(
            calendarId=calendar_id,
            eventId=event_id,
        ).execute()
        logger.info(f"Deleted event id={event_id}")
        return True
    except Exception as e:
        logger.error(f"delete_event({event_id}): {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════════

def get_event_start_dt(event: dict, tz=None) -> datetime.datetime | None:
    """
    Parse the event start into a timezone-aware datetime.
    Handles both timed ("dateTime") and all-day ("date") events.
    All-day events are treated as midnight in the user's timezone.
    Returns None if start is missing or unparseable.
    """
    import pytz
    if tz is None:
        tz = pytz.timezone(TIMEZONE)

    start     = event.get("start", {})
    date_time = start.get("dateTime")
    if date_time:
        try:
            dt = datetime.datetime.fromisoformat(date_time.replace("Z", "+00:00"))
            return dt.astimezone(tz)
        except (ValueError, TypeError):
            pass

    date_str = start.get("date")
    if date_str:
        try:
            d  = datetime.date.fromisoformat(date_str)
            dt = datetime.datetime(d.year, d.month, d.day, 0, 0, 0)
            return tz.localize(dt)
        except (ValueError, TypeError):
            pass

    return None


def get_event_end_dt(event: dict, tz=None) -> datetime.datetime | None:
    """Parse event end into a timezone-aware datetime."""
    import pytz
    if tz is None:
        tz = pytz.timezone(TIMEZONE)

    end       = event.get("end", {})
    date_time = end.get("dateTime")
    if date_time:
        try:
            dt = datetime.datetime.fromisoformat(date_time.replace("Z", "+00:00"))
            return dt.astimezone(tz)
        except (ValueError, TypeError):
            pass

    date_str = end.get("date")
    if date_str:
        try:
            d  = datetime.date.fromisoformat(date_str)
            dt = datetime.datetime(d.year, d.month, d.day, 23, 59, 59)
            return tz.localize(dt)
        except (ValueError, TypeError):
            pass

    return None


def get_event_duration_minutes(event: dict) -> int | None:
    """
    Return event duration in whole minutes.
    Returns None for all-day events or if times are unparseable.
    """
    import pytz
    if "dateTime" not in event.get("start", {}):
        return None
    tz    = pytz.timezone(TIMEZONE)
    start = get_event_start_dt(event, tz)
    end   = get_event_end_dt(event, tz)
    if start and end:
        return max(0, int((end - start).total_seconds() / 60))
    return None


def is_all_day_event(event: dict) -> bool:
    return (
        "date"     in event.get("start", {})
        and "dateTime" not in event.get("start", {})
    )


def get_attendee_count(event: dict) -> int:
    return len(event.get("attendees", []))


def extract_event_location(event: dict) -> str:
    return event.get("location", "").strip()


def is_significant_event(event: dict) -> bool:
    """
    True if this event qualifies for an event prep briefing.

    Significant if ANY of:
      - title contains an EVENT_PREP_KEYWORD
      - has at least one attendee
      - duration >= EVENT_PREP_MIN_DURATION_MINUTES

    Skip list (EVENT_PREP_SKIP_KEYWORDS) takes full precedence.
    """
    title = event.get("summary", "").lower()

    if any(kw.lower() in title for kw in EVENT_PREP_SKIP_KEYWORDS):
        return False
    if any(kw.lower() in title for kw in EVENT_PREP_KEYWORDS):
        return True
    if get_attendee_count(event) > 0:
        return True
    duration = get_event_duration_minutes(event)
    if duration is not None and duration >= EVENT_PREP_MIN_DURATION_MINUTES:
        return True
    return False


def is_travel_event(event: dict) -> bool:
    """
    True if the event has a location that doesn't match any HOME_CITY_KEYWORD.
    No location = not travel.
    """
    location = extract_event_location(event).lower()
    if not location:
        return False
    for keyword in HOME_CITY_KEYWORDS:
        if keyword.lower() in location:
            return False
    return True


# ═══════════════════════════════════════════════════════════════════════════════
# PIPELINES
# ═══════════════════════════════════════════════════════════════════════════════

def get_events_needing_prep(service) -> list[dict]:
    """Events starting within EVENT_PREP_HOURS_LOOKAHEAD that are significant."""
    events = get_upcoming_events(service, hours_ahead=EVENT_PREP_HOURS_LOOKAHEAD)
    return [e for e in events if is_significant_event(e)]


def get_travel_events(service, days_ahead: int | None = None) -> list[dict]:
    """Events within the next `days_ahead` days that appear to be out of town."""
    if days_ahead is None:
        days_ahead = TRAVEL_DETECT_DAYS_AHEAD
    import pytz
    tz    = pytz.timezone(TIMEZONE)
    now   = datetime.datetime.now(tz)
    end   = now + datetime.timedelta(days=days_ahead)
    events = get_events_range(service, now, end)
    return [e for e in events if is_travel_event(e)]


# ═══════════════════════════════════════════════════════════════════════════════
# FORMATTING
# ═══════════════════════════════════════════════════════════════════════════════

def format_event_brief(event: dict, tz=None) -> str:
    """
    Compact one-line summary of an event.
    Examples:
      "📅 Tue 7 Apr at 9:00 AM — Team standup (30 min)"
      "📅 Wed 8 Apr (all day) — Company offsite"
    """
    import pytz
    if tz is None:
        tz = pytz.timezone(TIMEZONE)

    title = event.get("summary", "Untitled event")
    start = get_event_start_dt(event, tz)

    def _fmt_day(dt):
        """Platform-agnostic day number without leading zero."""
        return dt.strftime("%d %b").lstrip("0").strip()

    def _fmt_time(dt):
        """Platform-agnostic 12-hour time without leading zero."""
        return dt.strftime("%I:%M %p").lstrip("0").strip()

    if is_all_day_event(event):
        date_str = _fmt_day(start) if start else "?"
        return f"📅 {date_str} (all day) — {title}"

    time_str = f"{start.strftime('%a')} {_fmt_day(start)} at {_fmt_time(start)}" if start else "?"
    duration = get_event_duration_minutes(event)
    if duration is not None:
        if duration < 60:
            dur_str = f"{duration} min"
        elif duration % 60 == 0:
            dur_str = f"{duration // 60}h"
        else:
            dur_str = f"{duration // 60}h {duration % 60}m"
        return f"📅 {time_str} — {title} ({dur_str})"

    return f"📅 {time_str} — {title}"


def format_events_block(
    events:     list[dict],
    tz=None,
    empty_msg:  str = "No events.",
    max_events: int = 10,
) -> str:
    """Multi-line block of event briefs for Telegram. Caps at max_events."""
    if not events:
        return empty_msg

    import pytz
    if tz is None:
        tz = pytz.timezone(TIMEZONE)

    lines = [format_event_brief(e, tz) for e in events[:max_events]]
    remaining = len(events) - max_events
    if remaining > 0:
        lines.append(f"…and {remaining} more event{'s' if remaining > 1 else ''}")
    return "\n".join(lines)


def format_event_detail(event: dict, tz=None) -> str:
    """
    Full detail view of a single event — used for event prep briefings
    and when the user asks "what's my 3pm tomorrow?"
    """
    import pytz
    if tz is None:
        tz = pytz.timezone(TIMEZONE)

    title    = event.get("summary", "Untitled event")
    start    = get_event_start_dt(event, tz)
    duration = get_event_duration_minutes(event)
    location = extract_event_location(event)
    guests   = get_attendee_count(event)
    desc     = event.get("description", "").strip()
    event_id = event.get("id", "")

    lines = [f"<b>{title}</b>"]

    def _fmt_day_long(dt):
        return dt.strftime("%d %B").lstrip("0").strip()

    def _fmt_time_short(dt):
        return dt.strftime("%I:%M %p").lstrip("0").strip()

    if is_all_day_event(event):
        lines.append(f"📅 {_fmt_day_long(start)} (all day)" if start else "📅 All day")
    else:
        if start:
            lines.append(f"🕐 {start.strftime('%A')}, {_fmt_day_long(start)} at {_fmt_time_short(start)}")
        if duration is not None:
            h, m = divmod(duration, 60)
            lines.append(f"⏱ {f'{h}h ' if h else ''}{f'{m}m' if m else ''}".strip())

    if location:
        lines.append(f"📍 {location}")
    if guests:
        lines.append(f"👥 {guests} attendee{'s' if guests != 1 else ''}")
    if desc:
        short = desc[:200] + ("…" if len(desc) > 200 else "")
        lines.append(f"📝 {short}")
    if event_id:
        lines.append(f"<code>id:{event_id}</code>")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# INTERNAL HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _to_rfc3339(dt: datetime.datetime) -> str:
    return dt.isoformat()


def _sort_key(event: dict) -> str:
    start = event.get("start", {})
    return start.get("dateTime") or start.get("date") or ""

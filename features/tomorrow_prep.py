"""
marvin/features/tomorrow_prep.py
==================================
Night-before briefing — fires once per night before a "busy day."

A busy day is defined as: ≥ BUSY_DAY_THRESHOLD calendar events  OR
at least one high-priority to-do due tomorrow.  The threshold is
configurable in proactive settings (default 3).

The briefing blends multiple signals into a single message so Marvin
doesn't spam the user with separate notifications:

  1. Tomorrow's full schedule (events + times)
  2. Priority to-dos due tomorrow
  3. Tonight's weather & tomorrow's weather
  4. Sleep nudge — "to get 7 hrs you need to be in bed by X"
  5. Meeting-prep hints (named contacts → quick-prep notes)
  6. Travel alert — if any event has a location, include travel time reminder
  7. Vacation start alert — if a travel/vacation event starts tomorrow

De-duplicated via proactive_sent["tomorrow_prep"] so it fires once per night
even if the daily job re-runs.

PUBLIC
──────
  run_tomorrow_prep(ctx)          — called by the daily job in bot.py
  cmd_tomorrow_prep(ctx)          — /tomorrowprep slash command (manual trigger)
"""

from __future__ import annotations

import asyncio
import datetime
import logging
from zoneinfo import ZoneInfo

from core.marvin_context import MarvinContext
from core.config import (
    TIMEZONE, BOT_NAME,
    WEATHER_LAT, WEATHER_LON,
    OPENAI_API_KEY, GPT_CHAT_MODEL,
)
from core.data import load_data, save_data, get_proactive_settings, get_sleep_schedule_settings
from features.proactive import _is_quiet_hours

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _now() -> datetime.datetime:
    return datetime.datetime.now(ZoneInfo(TIMEZONE))


def _today() -> datetime.date:
    return _now().date()


def _tomorrow() -> datetime.date:
    return _today() + datetime.timedelta(days=1)


def _already_sent_tonight(data: dict) -> bool:
    """True if we already sent the tomorrow-prep briefing this evening."""
    sent = data.get("proactive_sent", {})
    return sent.get("tomorrow_prep") == str(_today())


def _mark_sent(data: dict) -> None:
    data.setdefault("proactive_sent", {})["tomorrow_prep"] = str(_today())


# ═══════════════════════════════════════════════════════════════════════════════
# TOMORROW'S EVENTS
# ═══════════════════════════════════════════════════════════════════════════════

async def _get_tomorrow_events(data: dict) -> list[dict]:
    """Fetch tomorrow's calendar events. Returns [] if Google not connected."""
    try:
        from core.google_auth import get_creds
        from googleapiclient.discovery import build
        from adapters.google_calendar import get_events_range

        creds = get_creds(data)
        if not creds:
            return []
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        tz = ZoneInfo(TIMEZONE)
        tom = _tomorrow()
        start = datetime.datetime.combine(tom, datetime.time.min, tzinfo=tz)
        end   = datetime.datetime.combine(tom, datetime.time.max, tzinfo=tz)
        return get_events_range(service, start, end) or []
    except Exception as exc:
        logger.debug("tomorrow_prep: calendar fetch failed: %s", exc)
        return []


def _is_travel_event(event: dict) -> bool:
    """Heuristic: event summary or description contains travel keywords."""
    text = " ".join([
        event.get("summary", ""),
        event.get("description", ""),
        event.get("location", ""),
    ]).lower()
    keywords = [
        "flight", "airport", "hotel", "airbnb", "check-in",
        "depart", "arrive", "travel", "train", "amtrak", "cruise",
    ]
    return any(k in text for k in keywords)


def _format_event_line(event: dict, tz: ZoneInfo) -> str:
    """Return a short one-line description of an event."""
    from adapters.google_calendar import is_all_day_event, get_event_start_dt
    summary = event.get("summary", "Untitled")
    if is_all_day_event(event):
        return f"• {summary} (all day)"
    start_dt = get_event_start_dt(event, tz)
    if start_dt:
        return f"• {start_dt.strftime('%-I:%M %p')} — {summary}"
    return f"• {summary}"


# ═══════════════════════════════════════════════════════════════════════════════
# PRIORITY TO-DOS DUE TOMORROW
# ═══════════════════════════════════════════════════════════════════════════════

async def _get_priority_todos_due_tomorrow(data: dict) -> list[str]:
    """
    Return titles of to-dos flagged high-priority or due tomorrow.
    Checks Google Tasks and local data (whichever is available).
    """
    results: list[str] = []
    tom_str = str(_tomorrow())

    # Local todos stored in userdata
    for task in data.get("todos", []):
        if task.get("done"):
            continue
        due = task.get("due", "")
        priority = task.get("priority", "").lower()
        if due == tom_str or priority in ("high", "urgent"):
            results.append(task.get("title", "Unknown task"))

    # Google Tasks
    try:
        from core.google_auth import get_creds
        from googleapiclient.discovery import build
        from adapters.google_tasks import list_todos

        creds = get_creds(data)
        if creds:
            service = build("tasks", "v1", credentials=creds, cache_discovery=False)
            tasks = list_todos(service) or []
            for t in tasks:
                title = t.get("title", "")
                if not title:
                    continue
                due = (t.get("due") or "")[:10]   # "2025-06-15T00:00:00.000Z" → "2025-06-15"
                if due == tom_str:
                    if title not in results:
                        results.append(title)
    except Exception as exc:
        logger.debug("tomorrow_prep: tasks fetch failed: %s", exc)

    return results[:8]   # cap at 8 items


# ═══════════════════════════════════════════════════════════════════════════════
# WEATHER HELPERS (reuses Open-Meteo, same pattern as briefing.py)
# ═══════════════════════════════════════════════════════════════════════════════

async def _fetch_tomorrow_weather() -> str:
    """
    Return a one-line tomorrow weather summary using Open-Meteo.
    Returns empty string if unavailable.
    """
    try:
        import httpx
        from features.briefing import _wmo_description  # reuse code description map

        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={WEATHER_LAT}&longitude={WEATHER_LON}"
            f"&daily=weathercode,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
            f"&temperature_unit=fahrenheit&forecast_days=2&timezone=auto"
        )
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            return ""
        j = resp.json().get("daily", {})
        # index 1 = tomorrow
        code   = j.get("weathercode", [0, 0])[1]
        hi     = j.get("temperature_2m_max", [0, 0])[1]
        lo     = j.get("temperature_2m_min", [0, 0])[1]
        precip = j.get("precipitation_probability_max", [0, 0])[1]
        desc = _wmo_description(code)
        line = f"{desc}, {lo:.0f}–{hi:.0f}°F"
        if precip and precip >= 40:
            line += f" ({precip:.0f}% chance of rain)"
        return line
    except Exception as exc:
        logger.debug("tomorrow_prep: weather fetch failed: %s", exc)
        return ""


# ═══════════════════════════════════════════════════════════════════════════════
# BEDTIME CALCULATOR
# ═══════════════════════════════════════════════════════════════════════════════

def _parse_hhmm(s: str) -> datetime.time | None:
    """Parse "23:00" or "07:30" → datetime.time. Returns None on failure."""
    try:
        h, m = (int(x) for x in s.split(":"))
        return datetime.time(h, m)
    except Exception:
        return None


def _bedtime_suggestion(events: list[dict], tz: ZoneInfo, data: dict | None = None) -> str:
    """
    Suggest a bedtime based on the user's configured sleep schedule.

    Logic:
      1. Determine target wake time from user settings (weekday vs weekend).
      2. If tomorrow's first event requires an earlier wake (event - 30min),
         use that instead.
      3. bedtime = wake_target - sleep_goal_hours
      4. Only surface the suggestion if the bedtime is at or before the
         user's configured bed time — otherwise it's not actionable.
         (e.g. "9am meeting → bed by 1:30am" is useless; stay silent.)
    """
    from adapters.google_calendar import is_all_day_event, get_event_start_dt

    # ── Load user sleep settings ──────────────────────────────────────────────
    if data is None:
        data = load_data()
    ss          = get_sleep_schedule_settings(data)
    sleep_hours = ss.get("sleep_goal_hours", 7.5)

    tom = _tomorrow()
    is_weekend = tom.weekday() >= 5   # Saturday=5, Sunday=6
    wake_key   = "weekend_wake_time"  if is_weekend else "weekday_wake_time"
    bed_key    = "weekend_bed_time"   if is_weekend else "weekday_bed_time"

    target_wake_t = _parse_hhmm(ss.get(wake_key, "07:00"))
    target_bed_t  = _parse_hhmm(ss.get(bed_key,  "23:00"))

    if not target_wake_t or not target_bed_t:
        return ""

    # Convert target wake to a datetime so we can do arithmetic
    target_wake_dt = datetime.datetime.combine(tom, target_wake_t, tzinfo=tz)

    # ── Check if first event demands an earlier rise ──────────────────────────
    earliest: datetime.datetime | None = None
    for ev in events:
        if is_all_day_event(ev):
            continue
        dt = get_event_start_dt(ev, tz)
        if dt and (earliest is None or dt < earliest):
            earliest = dt

    if earliest:
        event_wake = earliest - datetime.timedelta(minutes=30)
        if event_wake < target_wake_dt:
            target_wake_dt = event_wake   # event forces an earlier start

    # ── Calculate bedtime ─────────────────────────────────────────────────────
    bedtime_dt = target_wake_dt - datetime.timedelta(hours=sleep_hours)
    bedtime_t  = bedtime_dt.time()

    # ── Usefulness gate: only show if bedtime ≤ user's target bed time ────────
    # Compare as minutes-past-midnight, handling wrap (bed at 23:00 < wake 07:00)
    def _to_mins(t: datetime.time) -> int:
        return t.hour * 60 + t.minute

    bed_mins    = _to_mins(target_bed_t)
    result_mins = _to_mins(bedtime_t)

    # If target bedtime is "late night" (≥22:00, i.e. same side as midnight),
    # the suggestion is only useful if calculated bedtime is ≤ target bed time.
    # For early-morning targets (<06:00) it's always useful.
    if bed_mins >= 18 * 60:   # target bed is 6pm or later (normal range)
        if result_mins > bed_mins:
            return ""   # calculated bedtime is after target — not useful

    return bedtime_dt.strftime("%-I:%M %p")


# ═══════════════════════════════════════════════════════════════════════════════
# MEETING-PREP HINTS
# ═══════════════════════════════════════════════════════════════════════════════

def _meeting_prep_hints(events: list[dict], data: dict) -> list[str]:
    """
    Cross-reference event attendees and summaries against stored contacts.
    Returns short prep blurbs for any known contacts.
    """
    hints: list[str] = []
    contacts: dict = data.get("contacts", {})
    if not contacts:
        return hints

    for ev in events:
        summary = ev.get("summary", "")
        attendees = [
            a.get("displayName") or a.get("email", "")
            for a in ev.get("attendees", [])
            if not a.get("self")
        ]
        for person, info in contacts.items():
            person_lower = person.lower()
            # Check if person name appears in event title or attendee list
            match = (
                person_lower in summary.lower()
                or any(person_lower in att.lower() for att in attendees)
            )
            if match:
                notes = info.get("notes", "") if isinstance(info, dict) else ""
                hint  = f"• {person}"
                if notes:
                    # Show first line of notes only
                    hint += f": {notes.splitlines()[0]}"
                hints.append(hint)
                if len(hints) >= 4:
                    break
        if len(hints) >= 4:
            break
    return hints


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN BUILDER
# ═══════════════════════════════════════════════════════════════════════════════

async def _build_tomorrow_prep_message(data: dict) -> str | None:
    """
    Build the full night-before briefing string.
    Returns None if tomorrow isn't a busy day (below threshold).
    """
    ps = get_proactive_settings(data)
    threshold = ps.get("busy_day_threshold", 3)
    tz = ZoneInfo(TIMEZONE)

    # Fetch events and todos concurrently
    events, priority_todos = await asyncio.gather(
        _get_tomorrow_events(data),
        _get_priority_todos_due_tomorrow(data),
    )

    # Decide if tomorrow qualifies as a busy day
    regular_events = [e for e in events if not _is_travel_event(e)]
    travel_events  = [e for e in events if _is_travel_event(e)]
    is_busy = len(events) >= threshold or bool(priority_todos)

    if not is_busy:
        return None

    tom = _tomorrow()
    day_name = tom.strftime("%A, %B %-d")

    lines: list[str] = [
        f"🌙 <b>Night-before briefing for {day_name}</b>",
        "",
    ]

    # ── Tomorrow's schedule ──────────────────────────────────────────────────
    if events:
        lines.append("📅 <b>Tomorrow's schedule</b>")
        for ev in sorted(events, key=lambda e: e.get("start", {}).get("dateTime", "00:00")):
            lines.append(_format_event_line(ev, tz))
        lines.append("")

    # ── Priority to-dos ──────────────────────────────────────────────────────
    if priority_todos:
        lines.append("✅ <b>Priority tasks due tomorrow</b>")
        for t in priority_todos:
            lines.append(f"• {t}")
        lines.append("")

    # ── Weather ──────────────────────────────────────────────────────────────
    weather = await _fetch_tomorrow_weather()
    if weather:
        lines.append(f"🌤 <b>Tomorrow's weather:</b> {weather}")
        lines.append("")

    # ── Bedtime suggestion ────────────────────────────────────────────────────
    bedtime = _bedtime_suggestion(events, tz, data=data)
    if bedtime:
        lines.append(f"😴 <b>Bedtime suggestion:</b> In bed by {bedtime} to get 7 hrs of sleep.")
        lines.append("")

    # ── Meeting-prep hints ────────────────────────────────────────────────────
    hints = _meeting_prep_hints(events, data)
    if hints:
        lines.append("📋 <b>Meeting-prep notes</b>")
        lines.extend(hints)
        lines.append("")

    # ── Travel alerts ─────────────────────────────────────────────────────────
    if travel_events:
        lines.append("✈️ <b>Travel reminder</b>")
        for ev in travel_events:
            summary  = ev.get("summary", "Travel event")
            location = ev.get("location", "")
            loc_str  = f" ({location})" if location else ""
            lines.append(f"• {summary}{loc_str} — remember travel time & any items you need.")
        lines.append("")

    # Strip trailing blank line
    while lines and lines[-1] == "":
        lines.pop()

    # If nothing was added beyond the header, treat as "not busy"
    if len(lines) <= 1:
        return None

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC ENTRY POINTS
# ═══════════════════════════════════════════════════════════════════════════════

async def run_tomorrow_prep(ctx: MarvinContext) -> None:
    """
    Called by the nightly job in bot.py.
    Silently skips if: not a busy day, already sent tonight, or module disabled.
    """
    data = load_data()
    ps   = get_proactive_settings(data)

    if not ps.get("tomorrow_prep", True):
        return
    if _already_sent_tonight(data):
        return
    if _is_quiet_hours(data):
        return

    # Skip during vacation (unless explicitly enabled)
    if ps.get("vacation_active", False):
        return

    msg = await _build_tomorrow_prep_message(data)
    if not msg:
        return

    await ctx.reply_html(msg)

    # Mark sent
    data = load_data()   # fresh load in case something mutated it
    _mark_sent(data)
    save_data(data)


async def cmd_tomorrow_prep(ctx: MarvinContext) -> None:
    """
    /tomorrowprep — manual trigger, always fires regardless of busy threshold.
    Useful for testing and for the user to see the briefing on demand.
    """
    data = load_data()
    ps   = get_proactive_settings(data)

    # Temporarily lower threshold to 0 so it always builds
    original = ps.get("busy_day_threshold", 3)
    ps["busy_day_threshold"] = 0
    save_data(data)

    msg = await _build_tomorrow_prep_message(data)

    # Restore
    ps["busy_day_threshold"] = original
    save_data(data)

    if msg:
        await ctx.reply_html(msg)
    else:
        tom = _tomorrow()
        await ctx.reply(
            f"Nothing on the calendar for {tom.strftime('%A')} yet — "
            "add some events and try again."
        )

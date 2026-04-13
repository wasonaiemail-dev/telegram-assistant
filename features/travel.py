"""
alfred/features/travel.py
==========================
Smart travel system — Alfred tracks upcoming trips and gives proactive,
staged alerts so the user is never caught unprepared.

HOW IT WORKS
────────────
Alfred scans the calendar for events that look like travel (flights, hotels,
"trip to X", etc.).  For each trip it fires a sequence of alerts:

  7 days out  — "You're leaving for {destination} in 7 days. Here's a
                  packing checklist for {trip type} + destination weather."
  3 days out  — "3 days until {destination}. Confirm flight / hotel / docs?"
  2 days out  — "2 days out — weather at destination, any last prep items?"
  1 day out   — "Tomorrow! Packing reminders + departure weather."

Alerts are de-duplicated: each (trip_id, checkpoint) fires at most once.
Trip IDs are derived from the event's Google Calendar ID (or a hash of
title+date for local-only events).

TRIP TYPE DETECTION
───────────────────
"Weekend trip", "business trip", "international", "beach", "ski", "camping"
are detected from the event title, description, and location.  Unknown trips
get a generic packing list.

PACKING SUGGESTIONS
───────────────────
Configurable per trip type in PACKING_LISTS below.  The buyer can add custom
lists via "add packing item [item] for [type]" (handled in vacation.py).
Stored in userdata.json["travel_packing_overrides"].

PUBLIC
──────
  run_travel_alerts(ctx)        — called daily by bot.py job
  cmd_travel(ctx)               — /travel slash command (shows upcoming trips)
"""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import logging
from zoneinfo import ZoneInfo

from core.alfred_context import AlfredContext
from core.config import TIMEZONE, WEATHER_LAT, WEATHER_LON
from core.data import load_data, save_data, get_proactive_settings

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# PACKING LISTS BY TRIP TYPE
# ═══════════════════════════════════════════════════════════════════════════════

PACKING_LISTS: dict[str, list[str]] = {
    "generic": [
        "Passport / ID", "Phone charger", "Headphones", "Medications",
        "Toiletries", "Comfortable clothes", "Snacks for travel day",
        "Laptop / tablet", "Earbuds / AirPods", "Cash / card",
    ],
    "business": [
        "Laptop + charger", "Business cards", "Dress clothes", "Dress shoes",
        "Portfolio / notebook", "Presentation materials", "Adapter / dongle",
        "Medications", "Phone charger", "Toiletries",
    ],
    "beach": [
        "Sunscreen (SPF 50+)", "Swimsuit", "Beach towel", "Sunglasses",
        "Flip-flops / sandals", "Hat / sun hat", "After-sun lotion",
        "Snorkelling gear", "Light cover-up", "Medications", "Phone charger",
    ],
    "ski": [
        "Ski jacket + pants", "Base layers (thermal)", "Ski gloves", "Goggles",
        "Helmet", "Warm socks (wool)", "Hand warmers", "Ski boots / rentals info",
        "Sunscreen (altitude)", "Medications", "Phone charger",
    ],
    "camping": [
        "Tent + stakes", "Sleeping bag", "Sleeping pad", "Headlamp + batteries",
        "Camp stove + fuel", "Water filter / iodine", "Bug spray",
        "Rain jacket", "First-aid kit", "Medications", "Phone charger",
    ],
    "international": [
        "Passport (check expiry!)", "Travel insurance docs", "Foreign currency",
        "Power adapter", "Visa documents", "Vaccination records",
        "Emergency contacts (written down)", "Medications (+ prescription)",
        "Unlocked phone / SIM card", "Hotel/hostel confirmations",
    ],
    "weekend": [
        "Phone charger", "Change of clothes (2 days)", "Toiletries",
        "Medications", "Snacks", "Comfortable shoes", "Any event tickets / info",
    ],
}

# Keywords used to detect trip type from event text
_TRIP_TYPE_KEYWORDS: dict[str, list[str]] = {
    "business":      ["conference", "meeting", "work trip", "business", "client"],
    "beach":         ["beach", "resort", "tropical", "bahamas", "cancun", "hawaii", "caribbean"],
    "ski":           ["ski", "snowboard", "mountain", "vail", "aspen", "tahoe", "whistler"],
    "camping":       ["camping", "camp", "backpack", "hike", "national park", "outdoors"],
    "international": ["international", "passport", "visa", "europe", "asia", "flight overseas"],
    "weekend":       ["weekend", "getaway", "short trip", "day trip"],
}

# Travel event keywords (same set used in tomorrow_prep)
_TRAVEL_KEYWORDS = [
    "flight", "airport", "hotel", "airbnb", "check-in", "depart", "arrive",
    "travel", "train", "amtrak", "cruise", "trip to", "flying to", "leaving for",
]

# Checkpoints (days_before, key_suffix, emoji)
_CHECKPOINTS = [
    (7, "7d",  "📅"),
    (3, "3d",  "🧳"),
    (2, "2d",  "⏰"),
    (1, "1d",  "✈️"),
]


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _today() -> datetime.date:
    return datetime.datetime.now(ZoneInfo(TIMEZONE)).date()


def _trip_key(event: dict) -> str:
    """Stable ID for a trip event, used in proactive_sent de-dup."""
    eid = event.get("id", "")
    if eid:
        return f"trip_{eid[:16]}"
    # fallback: hash of title+date
    raw = event.get("summary", "") + str(event.get("start", {}))
    return "trip_" + hashlib.md5(raw.encode()).hexdigest()[:12]


def _detect_trip_type(event: dict) -> str:
    text = " ".join([
        event.get("summary", ""),
        event.get("description", ""),
        event.get("location", ""),
    ]).lower()
    for trip_type, keywords in _TRIP_TYPE_KEYWORDS.items():
        if any(k in text for k in keywords):
            return trip_type
    return "generic"


def _detect_destination(event: dict) -> str:
    """Best-effort destination label from event location or summary."""
    loc = event.get("location", "").strip()
    if loc:
        # Return first part (city-ish)
        return loc.split(",")[0].strip()
    summary = event.get("summary", "")
    # Try to extract "to X" pattern
    import re
    m = re.search(r"(?:to|for|in)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", summary)
    if m:
        return m.group(1)
    return summary or "your trip"


def _already_sent(data: dict, key: str) -> bool:
    return key in data.get("proactive_sent", {})


def _mark_sent(data: dict, key: str) -> None:
    data.setdefault("proactive_sent", {})[key] = str(_today())


def _packing_list_for(trip_type: str, data: dict) -> list[str]:
    """Merge base list with any user-added overrides."""
    base = list(PACKING_LISTS.get(trip_type, PACKING_LISTS["generic"]))
    overrides: dict = data.get("travel_packing_overrides", {})
    extras = overrides.get(trip_type, []) + overrides.get("generic", [])
    for item in extras:
        if item not in base:
            base.append(item)
    return base


# ═══════════════════════════════════════════════════════════════════════════════
# DESTINATION WEATHER
# ═══════════════════════════════════════════════════════════════════════════════

async def _geocode_city(city: str) -> tuple[float, float] | None:
    """Geocode a city name using Open-Meteo geocoding API. Returns (lat, lon) or None."""
    try:
        import httpx
        url = f"https://geocoding-api.open-meteo.com/v1/search?name={city}&count=1"
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            return None
        results = resp.json().get("results", [])
        if results:
            return results[0]["latitude"], results[0]["longitude"]
    except Exception as exc:
        logger.debug("travel: geocoding failed for %s: %s", city, exc)
    return None


async def _destination_weather(destination: str) -> str:
    """
    Return a one-line weather summary for the destination.
    Falls back to empty string if geocoding fails.
    """
    try:
        from features.briefing import _wmo_description
        import httpx

        coords = await _geocode_city(destination)
        if not coords:
            return ""
        lat, lon = coords

        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&daily=weathercode,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
            f"&temperature_unit=fahrenheit&forecast_days=3&timezone=auto"
        )
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            return ""
        j = resp.json().get("daily", {})
        # Use day index 0 (today) as a representative forecast
        code   = (j.get("weathercode") or [0])[0]
        hi     = (j.get("temperature_2m_max") or [0])[0]
        lo     = (j.get("temperature_2m_min") or [0])[0]
        precip = (j.get("precipitation_probability_max") or [0])[0]
        desc   = _wmo_description(code)
        line   = f"{desc}, {lo:.0f}–{hi:.0f}°F"
        if precip and precip >= 40:
            line += f" ({precip:.0f}% chance of rain)"
        return line
    except Exception as exc:
        logger.debug("travel: dest weather failed: %s", exc)
        return ""


# ═══════════════════════════════════════════════════════════════════════════════
# FETCH UPCOMING TRAVEL EVENTS
# ═══════════════════════════════════════════════════════════════════════════════

async def _get_upcoming_travel_events(data: dict, days_ahead: int = 10) -> list[dict]:
    """
    Fetch calendar events in the next `days_ahead` days and filter to
    those that look like travel.
    """
    try:
        from core.google_auth import get_creds
        from googleapiclient.discovery import build
        from adapters.google_calendar import get_events_range

        creds = get_creds(data)
        if not creds:
            return []

        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        tz = ZoneInfo(TIMEZONE)
        start = datetime.datetime.now(tz)
        end   = start + datetime.timedelta(days=days_ahead)
        events = get_events_range(service, start, end) or []

        result = []
        for ev in events:
            text = " ".join([
                ev.get("summary", ""),
                ev.get("description", ""),
                ev.get("location", ""),
            ]).lower()
            if any(k in text for k in _TRAVEL_KEYWORDS):
                result.append(ev)
        return result
    except Exception as exc:
        logger.debug("travel: calendar fetch failed: %s", exc)
        return []


def _event_start_date(event: dict) -> datetime.date | None:
    """Return the start date of an event as a date object."""
    start = event.get("start", {})
    date_str = start.get("date") or (start.get("dateTime", "") or "")[:10]
    if date_str:
        try:
            return datetime.date.fromisoformat(date_str)
        except ValueError:
            pass
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# MESSAGE BUILDERS
# ═══════════════════════════════════════════════════════════════════════════════

async def _build_alert(
    event: dict,
    days_until: int,
    emoji: str,
    data: dict,
) -> str:
    destination = _detect_destination(event)
    trip_type   = _detect_trip_type(event)
    event_date  = _event_start_date(event)
    date_str    = event_date.strftime("%A, %B %-d") if event_date else "upcoming"

    lines = [
        f"{emoji} <b>Trip reminder — {destination}</b>",
        f"<i>{date_str} ({days_until} day{'s' if days_until != 1 else ''} away)</i>",
        "",
    ]

    # Packing list for early alerts (7d, 3d)
    if days_until >= 3:
        packing = _packing_list_for(trip_type, data)
        lines.append(f"🧳 <b>Packing list ({trip_type.replace('_', ' ').title()} trip)</b>")
        for item in packing:
            lines.append(f"• {item}")
        lines.append("")

    # Destination weather
    weather = await _destination_weather(destination)
    if weather:
        lines.append(f"🌤 <b>Weather in {destination}:</b> {weather}")
        lines.append("")

    # Last-minute reminders (2d, 1d)
    if days_until <= 2:
        lines.append("📋 <b>Final checklist</b>")
        lines.append("• Confirm flight / travel bookings")
        lines.append("• Charge all devices tonight")
        lines.append("• Set out of office reply if needed")
        loc = event.get("location", "")
        if loc:
            lines.append(f"• Allow travel time to: {loc}")
        lines.append("")

    # Boarding pass reminder for flight events
    if "flight" in (event.get("summary", "") + event.get("description", "")).lower():
        lines.append("✈️ <b>Don't forget:</b> Check in online (24 hrs before) + download boarding pass.")
        lines.append("")

    while lines and lines[-1] == "":
        lines.pop()

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC ENTRY POINTS
# ═══════════════════════════════════════════════════════════════════════════════

async def run_travel_alerts(ctx: AlfredContext) -> None:
    """
    Called daily by bot.py. Scans calendar for travel events and fires
    checkpoint alerts at 7/3/2/1 days out.
    """
    data = load_data()
    ps   = get_proactive_settings(data)

    if not ps.get("travel_alerts", True):
        return

    events = await _get_upcoming_travel_events(data, days_ahead=10)
    if not events:
        return

    today = _today()
    fired: list[str] = []

    for event in events:
        start_date = _event_start_date(event)
        if not start_date:
            continue
        days_until = (start_date - today).days
        if days_until < 0:
            continue  # past event

        trip_key = _trip_key(event)

        for days_before, suffix, emoji in _CHECKPOINTS:
            if days_until != days_before:
                continue
            sent_key = f"{trip_key}_{suffix}"
            if _already_sent(data, sent_key):
                continue

            msg = await _build_alert(event, days_until, emoji, data)
            await ctx.reply_html(msg)
            fired.append(sent_key)
            break   # only one checkpoint per event per day

    if fired:
        data = load_data()  # fresh re-load
        for key in fired:
            _mark_sent(data, key)
        save_data(data)


async def cmd_travel(ctx: AlfredContext) -> None:
    """/travel — show all upcoming detected trips."""
    data   = load_data()
    events = await _get_upcoming_travel_events(data, days_ahead=30)
    today  = _today()

    if not events:
        await ctx.reply(
            "No upcoming travel events detected. "
            "Alfred looks for events with keywords like: flight, hotel, trip, arrive, depart."
        )
        return

    lines = ["✈️ <b>Upcoming trips detected</b>", ""]
    for ev in events:
        start = _event_start_date(ev)
        if not start:
            continue
        days_until = (start - today).days
        destination = _detect_destination(ev)
        trip_type   = _detect_trip_type(ev)
        date_str    = start.strftime("%b %-d")
        if days_until < 0:
            day_label = f"{-days_until}d ago"
        elif days_until == 0:
            day_label = "today"
        elif days_until == 1:
            day_label = "tomorrow"
        else:
            day_label = f"in {days_until} days"
        lines.append(
            f"• <b>{destination}</b> — {date_str} ({day_label}, {trip_type} trip)"
        )

    lines += [
        "",
        "<i>Alfred will send packing reminders at 7, 3, 2, and 1 days out.</i>",
        "<i>Toggle travel alerts: \"turn off travel alerts\"</i>",
    ]
    await ctx.reply_html("\n".join(lines))

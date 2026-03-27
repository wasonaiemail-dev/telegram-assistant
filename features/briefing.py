"""
alfred/features/briefing.py
============================
Morning briefing, on-demand weather, and travel weather detection.

PUBLIC INTERFACE
────────────────
  send_briefing(context, chat_id)
      Sends the full morning briefing. Called by /briefing command and the
      daily job at BRIEFING_HOUR. Composes all sections and sends in one or
      more messages (Telegram has a 4096-char limit).

  send_weather(context, chat_id, location=None)
      Sends a weather report. Called by WEATHER intent. If location is None,
      uses the buyer's home coordinates. Fetches from Open-Meteo (free, no
      API key needed).

  send_travel_weather(context, chat_id)
      Scans calendar events for the next TRAVEL_DETECT_DAYS_AHEAD days.
      For any event that appears to be in a non-home city, fetches weather
      for that city and sends an alert. Runs nightly at TRAVEL_WEATHER_HOUR.

WEATHER SOURCE
──────────────
  Open-Meteo (https://open-meteo.com) — free, no API key required.
  Falls back to GPT-generated description if the API is unavailable.
  For geocoding travel cities, uses Open-Meteo Geocoding API (also free).

BRIEFING SECTIONS
─────────────────
  1. Greeting + date
  2. Quote of the day
  3. Weather summary (home)
  4. Today's calendar events
  5. Tasks due today + overdue
  6. Habits logged yesterday (summary)
  7. Active reminders due today
  8. Word of the day
"""

import asyncio
import logging
import datetime
from zoneinfo import ZoneInfo

from core.config import (
    BOT_NAME,
    TIMEZONE,
    WEATHER_LAT,
    WEATHER_LON,
    HOME_CITY,
    HOME_CITY_KEYWORDS,
    TRAVEL_DETECT_DAYS_AHEAD,
    QUOTE_TYPE,
    STOIC_QUOTES_URL,
    ZENQUOTES_URL,
    OPENAI_API_KEY,
    GPT_CHAT_MODEL,
    WORD_OF_DAY_LIST,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# INTERNAL HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _now_local() -> datetime.datetime:
    """Return the current datetime in the buyer's local timezone."""
    return datetime.datetime.now(ZoneInfo(TIMEZONE))


def _fmt_date(dt: datetime.datetime) -> str:
    """Return a friendly date string like 'Monday, March 3'."""
    day   = dt.strftime("%d").lstrip("0")
    month = dt.strftime("%B")
    dow   = dt.strftime("%A")
    return f"{dow}, {month} {day}"


def _fmt_time(dt: datetime.datetime) -> str:
    """Return '9:05 AM' with no leading zero."""
    return dt.strftime("%I:%M %p").lstrip("0").strip()


def _greeting(dt: datetime.datetime) -> str:
    """Return Good morning / afternoon / evening based on hour."""
    h = dt.hour
    if h < 12:
        return "Good morning"
    if h < 17:
        return "Good afternoon"
    return "Good evening"


def _word_of_the_day(dt: datetime.datetime) -> tuple[str, str]:
    """
    Return (word, definition) for today using the config WORD_OF_DAY_LIST.
    Cycles deterministically by day-of-year so every day is different.
    Each entry is a tuple: (word, pos, definition, example_sentence).
    """
    if not WORD_OF_DAY_LIST:
        return "", ""
    idx  = dt.timetuple().tm_yday % len(WORD_OF_DAY_LIST)
    item = WORD_OF_DAY_LIST[idx]
    if isinstance(item, (list, tuple)) and len(item) >= 3:
        # item = (word, part_of_speech, definition[, example])
        word       = item[0]
        pos        = item[1]
        definition = item[2]
        return word, f"_{pos}_ — {definition}"
    if isinstance(item, (list, tuple)) and len(item) >= 1:
        return item[0], ""
    return str(item), ""


# ─────────────────────────────────────────────────────────────────────────────
# QUOTE OF THE DAY
# ─────────────────────────────────────────────────────────────────────────────

async def _fetch_quote() -> str:
    """
    Fetch a quote based on QUOTE_TYPE.
    Falls back to a GPT-generated quote if the API fails.
    Returns a formatted string like: "The obstacle is the way." — Marcus Aurelius
    """
    import aiohttp
    from openai import AsyncOpenAI

    async def _gpt_fallback(style: str) -> str:
        client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        try:
            resp = await client.chat.completions.create(
                model=GPT_CHAT_MODEL,
                messages=[{
                    "role": "user",
                    "content": (
                        f"Give me one short {style} quote (15 words max). "
                        "Reply with only: \"quote\" — Author"
                    ),
                }],
                max_tokens=60,
                temperature=0.9,
                timeout=10,
            )
            return resp.choices[0].message.content.strip()
        except Exception:
            return ""

    qt = QUOTE_TYPE.lower()

    try:
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as session:

            if qt == "stoic":
                async with session.get(STOIC_QUOTES_URL) as r:
                    if r.status == 200:
                        data = await r.json(content_type=None)
                        text   = data.get("text", "").strip()
                        author = data.get("author", "").strip()
                        if text:
                            return f'"{text}" — {author}' if author else f'"{text}"'

            elif qt in ("bible",):
                # Use bible-api.com for a random verse
                async with session.get("https://bible-api.com/random") as r:
                    if r.status == 200:
                        data = await r.json(content_type=None)
                        text = data.get("text", "").strip().replace("\n", " ")
                        ref  = data.get("reference", "").strip()
                        if text:
                            return f'"{text[:200]}" — {ref}' if ref else f'"{text[:200]}"'

            else:  # motivational / philosophical / random
                async with session.get(ZENQUOTES_URL) as r:
                    if r.status == 200:
                        data = await r.json(content_type=None)
                        if data and isinstance(data, list):
                            q = data[0]
                            text   = q.get("q", "").strip()
                            author = q.get("a", "").strip()
                            if text:
                                return f'"{text}" — {author}' if author else f'"{text}"'

    except Exception as e:
        logger.warning(f"_fetch_quote API error ({qt}): {e}")

    # GPT fallback
    style_map = {
        "stoic":         "stoic",
        "bible":         "biblical",
        "motivational":  "motivational",
        "philosophical": "philosophical",
    }
    return await _gpt_fallback(style_map.get(qt, "inspirational"))


# ─────────────────────────────────────────────────────────────────────────────
# WEATHER  (Open-Meteo — free, no API key)
# ─────────────────────────────────────────────────────────────────────────────

_WMO_CODES = {
    0:  "Clear sky",
    1:  "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Foggy", 48: "Icy fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow",
    77: "Snow grains",
    80: "Light showers", 81: "Showers", 82: "Heavy showers",
    85: "Snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with hail", 99: "Heavy thunderstorm with hail",
}


async def _get_weather(lat: float, lon: float) -> dict | None:
    """
    Fetch current + today forecast from Open-Meteo.
    Returns a dict with keys: temp_c, feels_c, condition, high_c, low_c,
                               precip_mm, wind_kph, humidity
    Returns None on failure.
    """
    import aiohttp
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&current=temperature_2m,apparent_temperature,weathercode,"
        "windspeed_10m,relativehumidity_2m"
        "&daily=weathercode,temperature_2m_max,temperature_2m_min,precipitation_sum"
        "&timezone=auto"
        "&forecast_days=1"
    )
    try:
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as r:
                if r.status != 200:
                    return None
                data = await r.json()

        cur   = data.get("current", {})
        daily = data.get("daily", {})

        temp_c    = cur.get("temperature_2m")
        feels_c   = cur.get("apparent_temperature")
        wmo       = cur.get("weathercode", 0)
        wind_kph  = cur.get("windspeed_10m")
        humidity  = cur.get("relativehumidity_2m")
        high_c    = daily.get("temperature_2m_max", [None])[0]
        low_c     = daily.get("temperature_2m_min", [None])[0]
        precip_mm = daily.get("precipitation_sum", [None])[0]

        def c_to_f(c):
            return round(c * 9 / 5 + 32) if c is not None else None

        return {
            "temp_f":    c_to_f(temp_c),
            "feels_f":   c_to_f(feels_c),
            "high_f":    c_to_f(high_c),
            "low_f":     c_to_f(low_c),
            "condition": _WMO_CODES.get(wmo, "Unknown"),
            "wind_kph":  round(wind_kph) if wind_kph is not None else None,
            "humidity":  round(humidity) if humidity is not None else None,
            "precip_mm": round(precip_mm, 1) if precip_mm is not None else None,
        }

    except Exception as e:
        logger.warning(f"_get_weather error: {e}")
        return None


def _format_weather(w: dict, city: str = "") -> str:
    """Format weather dict into a Telegram-friendly string."""
    loc = f" in {city}" if city else ""
    lines = [f"🌤 *Weather{loc}*"]
    lines.append(f"  {w['condition']} — {w['temp_f']}°F (feels {w['feels_f']}°F)")
    lines.append(f"  High {w['high_f']}°F / Low {w['low_f']}°F")
    if w.get("precip_mm") and w["precip_mm"] > 0:
        lines.append(f"  Precipitation: {w['precip_mm']} mm")
    if w.get("wind_kph"):
        lines.append(f"  Wind: {w['wind_kph']} km/h")
    if w.get("humidity"):
        lines.append(f"  Humidity: {w['humidity']}%")
    return "\n".join(lines)


async def _geocode_city(city_name: str) -> tuple[float, float] | None:
    """
    Geocode a city name using Open-Meteo's free geocoding API.
    Returns (lat, lon) or None.
    """
    import aiohttp
    url = (
        "https://geocoding-api.open-meteo.com/v1/search"
        f"?name={city_name}&count=1&language=en&format=json"
    )
    try:
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as r:
                if r.status != 200:
                    return None
                data = await r.json()
        results = data.get("results", [])
        if not results:
            return None
        return results[0]["latitude"], results[0]["longitude"]
    except Exception as e:
        logger.warning(f"_geocode_city({city_name}) error: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# BRIEFING SECTIONS
# ─────────────────────────────────────────────────────────────────────────────

async def _section_calendar(dt: datetime.datetime) -> str:
    """Return today's and tomorrow's calendar events."""
    try:
        import pytz
        from adapters.google_calendar import get_events_range, format_event_brief
        from core.google_auth import get_calendar_service
        svc = get_calendar_service()
        if not svc:
            return "📅 *Calendar*\n  _(Google not connected — run /auth)_"

        tz    = pytz.timezone(TIMEZONE)
        today_start = dt.replace(hour=0, minute=0, second=0, microsecond=0,
                                  tzinfo=dt.tzinfo or tz.localize(dt).tzinfo)
        # Ensure tz-awareness
        import datetime as _dt
        aware_start = tz.localize(_dt.datetime(dt.year, dt.month, dt.day, 0, 0, 0))
        today_end   = tz.localize(_dt.datetime(dt.year, dt.month, dt.day, 23, 59, 59))
        tomorrow_start = aware_start + _dt.timedelta(days=1)
        tomorrow_end   = today_end   + _dt.timedelta(days=1)

        today_events    = get_events_range(svc, aware_start, today_end)
        tomorrow_events = get_events_range(svc, tomorrow_start, tomorrow_end)
    except Exception as e:
        logger.warning(f"_section_calendar error: {e}")
        return "📅 *Calendar*\n  _(unable to load — check Google auth)_"

    lines = ["📅 *Today's Schedule*"]

    if not today_events:
        lines.append("  No events today.")
    else:
        for ev in today_events:
            lines.append(f"  • {format_event_brief(ev)}")

    if tomorrow_events:
        lines.append("\n📅 *Tomorrow*")
        for ev in tomorrow_events[:3]:  # cap at 3 to keep briefing concise
            lines.append(f"  • {format_event_brief(ev)}")

    return "\n".join(lines)


def _task_due_date(task: dict) -> datetime.date | None:
    """Extract the due date from a Google Tasks task dict, or None."""
    due_str = task.get("due", "")
    if not due_str:
        return None
    try:
        # Google Tasks returns due as RFC 3339: "2024-03-15T00:00:00.000Z"
        return datetime.date.fromisoformat(due_str[:10])
    except Exception:
        return None


async def _section_tasks(dt: datetime.datetime) -> str:
    """Return tasks due today and overdue tasks."""
    today = dt.date()
    try:
        from adapters.google_tasks import list_todos
        from core.google_auth import get_tasks_service as _svc
        svc = _svc()
        if not svc:
            return "✅ *Tasks*\n  _(Google not connected — run /auth)_"

        all_tasks = list_todos(svc, include_done=False)
    except Exception as e:
        logger.warning(f"_section_tasks error: {e}")
        return "✅ *Tasks*\n  _(unable to load tasks)_"

    due_today = []
    overdue   = []
    for t in all_tasks:
        d = _task_due_date(t)
        if d is None:
            continue
        if d == today:
            due_today.append(t)
        elif d < today:
            overdue.append(t)

    lines = ["✅ *Tasks*"]

    if overdue:
        lines.append(f"  ⚠️ {len(overdue)} overdue:")
        for t in overdue[:5]:
            lines.append(f"    • {t.get('title', '(untitled)')}")
        if len(overdue) > 5:
            lines.append(f"    …and {len(overdue) - 5} more")

    if due_today:
        lines.append(f"  Due today ({len(due_today)}):")
        for t in due_today[:5]:
            lines.append(f"    • {t.get('title', '(untitled)')}")
        if len(due_today) > 5:
            lines.append(f"    …and {len(due_today) - 5} more")

    if not overdue and not due_today:
        lines.append("  Nothing due today. 🎉")

    return "\n".join(lines)


async def _section_habits(dt: datetime.datetime) -> str:
    """Return yesterday's habit completion summary."""
    try:
        from features.habits import get_yesterday_summary
        summary = get_yesterday_summary()
        if summary:
            return f"💪 *Habits (Yesterday)*\n{summary}"
        return ""
    except Exception as e:
        logger.debug(f"_section_habits: {e}")
        return ""


async def _section_reminders(dt: datetime.datetime) -> str:
    """Return reminders due today."""
    try:
        from features.reminders import get_due_today
        due = get_due_today()
        if not due:
            return ""
        lines = ["⏰ *Reminders Due Today*"]
        for r in due[:5]:
            lines.append(f"  • {r.get('text', '(no text)')}")
        return "\n".join(lines)
    except Exception as e:
        logger.debug(f"_section_reminders: {e}")
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC: send_briefing
# ─────────────────────────────────────────────────────────────────────────────

async def _section_quote(_now):
    return await _fetch_quote()

async def _section_weather(_now):
    from core.config import WEATHER_LAT, WEATHER_LON, HOME_CITY
    wd = await _get_weather(WEATHER_LAT, WEATHER_LON)
    if wd:
        return _format_weather(wd, city=HOME_CITY.title())
    return "🌤 *Weather*\n  _(unable to load weather)_"

async def _section_word_of_day(now):
    word, definition = _word_of_the_day(now)
    if not word:
        return ""
    wotd = f"📖 *Word of the Day*\n  *{word}*"
    if definition:
        wotd += f" — {definition}"
    return wotd

async def _section_meals_today(_now):
    try:
        from features.meals import get_todays_meals_text
        return await get_todays_meals_text()
    except Exception:
        return ""

async def _section_journal_highlight(_now):
    try:
        from features.journal import get_yesterday_highlight
        return get_yesterday_highlight()
    except Exception:
        return ""

async def _section_workout_stats(_now):
    try:
        from features.workout import get_briefing_line
        return get_briefing_line()
    except Exception:
        return ""

_SECTION_BUILDERS = {
    "weather":           _section_weather,
    "calendar":          _section_calendar,
    "todos":             _section_tasks,
    "habits":            _section_habits,
    "reminders":         _section_reminders,
    "meals":             _section_meals_today,
    "journal_highlight": _section_journal_highlight,
    "workout_stats":     _section_workout_stats,
    "quote":             _section_quote,
    "word_of_day":       _section_word_of_day,
}


async def send_briefing(context, chat_id: int) -> None:
    """
    Compose and send the morning briefing.

    Section order and enabled/disabled state are read from the buyer's
    briefing_settings in userdata.json (configured via /setup briefing).
    Falls back to a sensible default order if not configured.
    """
    from core.data import load_data, get_briefing_settings
    data = load_data()
    bs   = get_briefing_settings(data)

    enabled = bs.get("enabled", list(_SECTION_BUILDERS.keys()))
    order   = [s for s in bs.get("order", list(_SECTION_BUILDERS.keys())) if s in enabled]

    now = _now_local()

    tasks = {key: asyncio.create_task(_SECTION_BUILDERS[key](now))
             for key in order if key in _SECTION_BUILDERS}
    results = {}
    for key, task in tasks.items():
        try:
            results[key] = await task
        except Exception:
            results[key] = ""

    sections = [f"☀️ *{_greeting(now)}, {_fmt_date(now)}*"]
    for key in order:
        val = results.get(key, "")
        if val:
            sections.append(val)

    full_text = "\n\n".join(s for s in sections if s)
    await _send_long(context.bot, chat_id, full_text)



async def send_weather(context, chat_id: int, location: str | None = None) -> None:
    """
    Send a weather report.

    If location is provided (extracted by intent classifier), geocode it.
    Otherwise use the buyer's home coordinates.
    """
    if location:
        coords = await _geocode_city(location)
        if not coords:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"Sorry, I couldn't find weather data for '{location}'.",
            )
            return
        lat, lon = coords
        city = location.title()
    else:
        lat, lon = WEATHER_LAT, WEATHER_LON
        city = HOME_CITY.title()

    w = await _get_weather(lat, lon)
    if not w:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Sorry, weather data is unavailable right now.",
        )
        return

    await context.bot.send_message(
        chat_id=chat_id,
        text=_format_weather(w, city=city),
        parse_mode="Markdown",
    )


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC: send_travel_weather
# ─────────────────────────────────────────────────────────────────────────────

async def send_travel_weather(context, chat_id: int) -> None:
    """
    Scan upcoming calendar events for travel (non-home city) and send
    weather alerts for any travel destinations found.

    Runs nightly at TRAVEL_WEATHER_HOUR. Silently exits if no travel found.
    """
    try:
        from adapters.google_calendar import get_upcoming_events
        from core.google_auth import is_authorized, get_calendar_service
        if not is_authorized():
            return

        svc = get_calendar_service()
        if not svc:
            return

        hours_ahead = TRAVEL_DETECT_DAYS_AHEAD * 24
        events = get_upcoming_events(svc, hours_ahead=hours_ahead)
    except Exception as e:
        logger.warning(f"send_travel_weather: calendar error: {e}")
        return

    if not events:
        return

    # Find events that look like travel (location field set, not a home keyword)
    travel_events = []
    for ev in events:
        loc = (ev.get("location") or "").lower().strip()
        if not loc:
            continue
        if any(kw in loc for kw in HOME_CITY_KEYWORDS):
            continue  # still home
        travel_events.append((ev, loc))

    if not travel_events:
        return

    # Deduplicate by city (send one weather alert per city)
    seen_cities: set[str] = set()
    alerts_sent = 0

    for ev, loc in travel_events:
        if loc in seen_cities:
            continue
        seen_cities.add(loc)

        coords = await _geocode_city(loc)
        if not coords:
            continue

        lat, lon = coords
        w = await _get_weather(lat, lon)
        if not w:
            continue

        # Find the earliest event in this city for context
        ev_title = ev.get("summary", "your trip")
        start    = ev.get("start", {})
        start_dt = start.get("dateTime") or start.get("date") or ""

        msg_lines = [
            f"✈️ *Travel Weather Alert*",
            f"For: _{ev_title}_",
            "",
            _format_weather(w, city=loc.title()),
        ]
        await context.bot.send_message(
            chat_id=chat_id,
            text="\n".join(msg_lines),
            parse_mode="Markdown",
        )
        alerts_sent += 1


# ─────────────────────────────────────────────────────────────────────────────
# UTILITY: split and send long messages
# ─────────────────────────────────────────────────────────────────────────────

async def _send_long(bot, chat_id: int, text: str, parse_mode: str = "Markdown") -> None:
    """
    Send text to chat_id, splitting at 4096 chars if necessary.
    Splits on double-newlines to avoid breaking Markdown mid-block.
    """
    MAX = 4000  # stay under Telegram's 4096 limit with buffer

    if len(text) <= MAX:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)
        return

    # Split on paragraph boundaries
    parts = text.split("\n\n")
    chunk = ""
    for part in parts:
        if len(chunk) + len(part) + 2 > MAX:
            if chunk:
                await bot.send_message(chat_id=chat_id, text=chunk.strip(), parse_mode=parse_mode)
            chunk = part
        else:
            chunk = (chunk + "\n\n" + part).strip() if chunk else part

    if chunk:
        await bot.send_message(chat_id=chat_id, text=chunk.strip(), parse_mode=parse_mode)

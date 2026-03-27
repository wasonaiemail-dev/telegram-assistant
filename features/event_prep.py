"""
alfred/features/event_prep.py
==============================
Nightly event prep briefing — GPT-powered context for upcoming events.

PUBLIC INTERFACE
────────────────
  send_event_prep(context, chat_id)
      Called nightly at EVENT_PREP_HOUR by the background job in bot.py.
      Scans for events within EVENT_PREP_HOURS_LOOKAHEAD that are
      significant (meetings, appointments, travel, etc.) and sends
      a GPT-generated prep note for each one.

HOW IT WORKS
────────────
  1. Fetch events needing prep from Google Calendar.
  2. For each event, build a context string (title, time, location,
     attendees, description).
  3. Call GPT to generate a 2–4 sentence prep note:
       - What to prepare / bring
       - Any relevant memory context (injected from Alfred's memory)
       - Suggested talking points (for meetings with attendees)
  4. Send each prep note as a separate Telegram message.

SIGNIFICANCE RULES  (from google_calendar.py)
──────────────────
  Events are selected if they:
    - Title contains EVENT_PREP_KEYWORDS (meeting, appointment, interview…)
    - OR duration >= EVENT_PREP_MIN_DURATION_MINUTES (30 min default)
  And skip if:
    - Title contains EVENT_PREP_SKIP_KEYWORDS (commute, gym…)
"""

import logging

from core.config import (
    BOT_NAME,
    OPENAI_API_KEY,
    GPT_CHAT_MODEL,
    TIMEZONE,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# PREP NOTE GENERATOR
# ─────────────────────────────────────────────────────────────────────────────

_PREP_SYSTEM = """You are {bot_name}, a personal assistant preparing a brief event prep note.
Given details about an upcoming event, write 2–4 sentences covering:
  - What the person should prepare or bring
  - Any useful context or talking points (if it's a meeting)
  - One practical action item if relevant

Keep it concise, specific, and useful. Do not pad or repeat the event details back."""

_PREP_USER = """Upcoming event:
  Title:       {title}
  Time:        {time}
  Location:    {location}
  Attendees:   {attendees}
  Description: {description}

{memory_block}
Write the prep note now."""


async def _generate_prep_note(
    title:        str,
    time_str:     str,
    location:     str,
    attendees:    str,
    description:  str,
    memory_block: str,
) -> str:
    """Call GPT to generate a prep note for the event."""
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=OPENAI_API_KEY)

    system = _PREP_SYSTEM.format(bot_name=BOT_NAME)
    user   = _PREP_USER.format(
        title=title,
        time=time_str,
        location=location or "Not specified",
        attendees=attendees or "None listed",
        description=description[:500] if description else "None",
        memory_block=(
            f"User memory context:\n{memory_block}\n"
            if memory_block
            else ""
        ),
    )

    try:
        resp = await client.chat.completions.create(
            model=GPT_CHAT_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            temperature=0.5,
            max_tokens=250,
            timeout=20,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.warning(f"_generate_prep_note error: {e}")
        return f"You have *{title}* coming up. Check your calendar for details."


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC: send_event_prep
# ─────────────────────────────────────────────────────────────────────────────

async def send_event_prep(context, chat_id: int) -> None:
    """
    Fetch upcoming significant events and send a prep note for each.
    Silently exits if not authorized or no prep-worthy events found.
    """
    from core.google_auth import get_calendar_service, is_authorized
    from adapters.google_calendar import (
        get_events_needing_prep,
        format_event_brief,
        get_event_start_dt,
        get_attendee_count,
        extract_event_location,
    )
    from features.memory import get_context_for_message

    if not is_authorized():
        return

    svc = get_calendar_service()
    if not svc:
        return

    try:
        events = get_events_needing_prep(svc)
    except Exception as e:
        logger.warning(f"send_event_prep: could not fetch events: {e}")
        return

    if not events:
        return  # Nothing to prep — silent

    import pytz
    tz = pytz.timezone(TIMEZONE)

    sent_header = False
    for ev in events:
        title       = ev.get("summary", "(untitled event)")
        location    = extract_event_location(ev)
        description = ev.get("description", "")

        # Format start time
        start_dt = get_event_start_dt(ev, tz=tz)
        time_str = (
            start_dt.strftime("%A, %b %d at %I:%M %p").lstrip("0").strip()
            if start_dt else "Unknown time"
        )

        # Attendees
        attendees_raw = ev.get("attendees", [])
        attendee_names = []
        for a in attendees_raw[:5]:
            name = a.get("displayName") or a.get("email", "")
            if name:
                attendee_names.append(name)
        attendees_str = ", ".join(attendee_names) if attendee_names else ""

        # Memory context for this event
        memory_block = get_context_for_message(f"{title} {location} {attendees_str}")

        # Generate prep note
        prep_note = await _generate_prep_note(
            title=title,
            time_str=time_str,
            location=location,
            attendees=attendees_str,
            description=description,
            memory_block=memory_block,
        )

        if not sent_header:
            await context.bot.send_message(
                chat_id=chat_id,
                text="📋 *Event Prep for Tomorrow*",
                parse_mode="Markdown",
            )
            sent_header = True

        msg = (
            f"🗓 *{title}*\n"
            f"_{time_str}_\n\n"
            f"{prep_note}"
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text=msg,
            parse_mode="Markdown",
        )

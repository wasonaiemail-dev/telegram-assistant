"""
alfred/features/photo_handlers.py
===================================
Photo-to-action handlers for specialised image types.

HANDLERS
────────
  handle_calendar_photo(file_path, ctx)
    — Extracts event details from a photo (flyer, invitation, screenshot)
      and adds the event to Google Calendar.

  handle_whiteboard_photo(file_path, ctx)
    — Transcribes text from a whiteboard, handwritten note, or sticky note
      and saves it as a Google Tasks note.

  handle_food_photo(file_path, ctx)
    — Identifies food in a photo (plate or menu) and logs it as a meal
      in the Adherence sheet of meals.xlsx.
"""

import base64
import datetime
import logging

from core.alfred_context import AlfredContext
from core.config import OPENAI_API_KEY, GPT_VISION_MODEL, TIMEZONE

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# SHARED HELPER
# ─────────────────────────────────────────────────────────────────────────────

async def _vision_query(file_path: str, prompt: str, max_tokens: int = 600) -> str:
    """Run a GPT-4o vision query against a local image file. Returns the text response."""
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    with open(file_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    resp = await client.chat.completions.create(
        model=GPT_VISION_MODEL,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            ],
        }],
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content.strip()


# ─────────────────────────────────────────────────────────────────────────────
# CALENDAR PHOTO
# ─────────────────────────────────────────────────────────────────────────────

async def handle_calendar_photo(file_path: str, ctx: AlfredContext) -> None:
    """
    Extract event details from a photo (flyer, invitation, event screenshot)
    and add the event to Google Calendar.
    """
    await ctx.reply("📅 Reading event details…")

    prompt = (
        "This image appears to contain event or calendar information. "
        "Extract the following and reply in this EXACT JSON format with no markdown:\n"
        '{"title": "...", "date": "YYYY-MM-DD or description", "time": "HH:MM or description or null", '
        '"location": "... or null", "description": "brief description or null"}\n'
        "If a field is unknown leave it as null. Only output valid JSON."
    )

    try:
        raw = await _vision_query(file_path, prompt, max_tokens=300)
    except Exception as e:
        logger.error(f"Calendar photo vision error: {e}")
        await ctx.reply("Sorry, I couldn't read the event details. Try again.")
        return

    # Parse the JSON
    import json, re
    try:
        # Strip any accidental markdown fences
        clean = re.sub(r"```(?:json)?", "", raw).strip()
        data = json.loads(clean)
    except Exception:
        logger.warning(f"Calendar photo JSON parse failed, raw: {raw!r}")
        await ctx.reply(f"I can see an event but couldn't extract the details cleanly.\n\nHere's what I found:\n{raw}")
        return

    title    = (data.get("title") or "").strip()
    date_str = (data.get("date")  or "").strip()
    time_str = (data.get("time")  or "").strip()
    location = (data.get("location") or "").strip()
    desc     = (data.get("description") or "").strip()

    if not title:
        await ctx.reply("I couldn't identify an event title in that image. What should I call this event?")
        return

    # Try to build a datetime for create_event; fall back to Quick Add
    from features.calendar import _get_service
    from core.config import TIMEZONE as TZ
    import pytz

    svc = _get_service()
    if not svc:
        await ctx.reply("❌ Google Calendar isn't connected. Run /auth first.")
        return

    tz = pytz.timezone(TZ)
    start_dt = None

    if date_str:
        # Try to parse date + optional time
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
            combined = f"{date_str} {time_str}".strip() if time_str else date_str
            try:
                start_dt = datetime.datetime.strptime(combined, fmt)
                if start_dt.tzinfo is None:
                    start_dt = tz.localize(start_dt)
                break
            except ValueError:
                continue

    if start_dt:
        end_dt = start_dt + datetime.timedelta(hours=1)
        from adapters.google_calendar import create_event, format_event_brief
        kwargs = {}
        if location:
            kwargs["location"] = location
        if desc:
            kwargs["description"] = desc
        result = create_event(svc, title, start_dt, end_dt, **kwargs)
        if result:
            from adapters.google_calendar import format_event_brief
            await ctx.reply_markdown(f"✅ Added to calendar: *{format_event_brief(result)}*")
        else:
            await ctx.reply("Couldn't create the calendar event. Please try again.")
    else:
        # Fallback: Quick Add with title + whatever details we have
        quick_str = title
        if date_str:
            quick_str += f" on {date_str}"
        if time_str:
            quick_str += f" at {time_str}"
        if location:
            quick_str += f" at {location}"

        from adapters.google_calendar import quick_add_event, format_event_brief
        result = quick_add_event(svc, quick_str)
        if result:
            await ctx.reply_markdown(f"✅ Added to calendar: *{format_event_brief(result)}*")
        else:
            await ctx.reply(
                f"I found this event but couldn't add it automatically:\n\n"
                f"*{title}*\n{date_str or ''} {time_str or ''}\n{location or ''}".strip(),
            )


# ─────────────────────────────────────────────────────────────────────────────
# WHITEBOARD PHOTO
# ─────────────────────────────────────────────────────────────────────────────

async def handle_whiteboard_photo(file_path: str, ctx: AlfredContext) -> None:
    """
    Transcribe text from a whiteboard, handwritten note, or sticky note
    and save it as a note in Google Tasks.
    """
    await ctx.reply("📝 Reading your note…")

    prompt = (
        "This image contains handwritten or whiteboard text. "
        "Transcribe ALL the text exactly as written, preserving structure. "
        "If there are multiple items or bullet points, keep them. "
        "Just output the transcribed text with no preamble or commentary."
    )

    try:
        transcribed = await _vision_query(file_path, prompt, max_tokens=800)
    except Exception as e:
        logger.error(f"Whiteboard photo vision error: {e}")
        await ctx.reply("Sorry, I couldn't read the text in that image.")
        return

    if not transcribed:
        await ctx.reply("I couldn't make out any text in that image.")
        return

    # Save to Google Tasks as a note
    from features.notes import _get_service as _notes_service
    svc = _notes_service()
    if not svc:
        await ctx.reply("❌ Google Tasks isn't connected. Run /auth first.\n\nHere's what I read:\n\n" + transcribed)
        return

    from adapters.google_tasks import add_note
    result = add_note(svc, transcribed)
    if result:
        preview = transcribed[:120] + ("…" if len(transcribed) > 120 else "")
        await ctx.reply_markdown(f"📝 Saved note:\n_{preview}_")
    else:
        await ctx.reply(f"Couldn't save to notes, but here's what I read:\n\n{transcribed}")


# ─────────────────────────────────────────────────────────────────────────────
# FOOD / MENU PHOTO
# ─────────────────────────────────────────────────────────────────────────────

def _current_meal_slot() -> str:
    """Return breakfast / lunch / dinner / snack based on current local time."""
    import pytz
    now = datetime.datetime.now(pytz.timezone(TIMEZONE))
    hour = now.hour
    if 5 <= hour < 10:
        return "breakfast"
    elif 10 <= hour < 14:
        return "lunch"
    elif 14 <= hour < 17:
        return "snack"
    elif 17 <= hour < 21:
        return "dinner"
    else:
        return "snack"


async def handle_food_photo(file_path: str, ctx: AlfredContext) -> None:
    """
    Identify food in a photo (plate of food or restaurant menu)
    and log it in the meal adherence tracker.
    """
    await ctx.reply("🍽️ Identifying food…")

    prompt = (
        "Look at this image. "
        "If it's a PLATE OF FOOD or a meal someone just ate, list what you can see "
        "(e.g. 'grilled chicken, rice, broccoli'). Be concise — one line.\n"
        "If it's a RESTAURANT MENU, list the 5 most notable dishes with brief descriptions.\n"
        "Start your reply with either 'MEAL:' or 'MENU:' to indicate which type."
    )

    try:
        raw = await _vision_query(file_path, prompt, max_tokens=300)
    except Exception as e:
        logger.error(f"Food photo vision error: {e}")
        await ctx.reply("Sorry, I couldn't identify the food in that image.")
        return

    if raw.upper().startswith("MENU:"):
        # It's a menu — just display the items
        items = raw[5:].strip()
        await ctx.reply(f"📋 Menu items I can see:\n\n{items}")
        return

    # It's a meal — log to adherence tracker
    meal_text = raw[5:].strip() if raw.upper().startswith("MEAL:") else raw

    from features.meals import _log_adherence, _today_iso
    slot     = _current_meal_slot()
    date_iso = _today_iso()

    success = _log_adherence(
        date_iso=date_iso,
        slot=slot,
        planned="",          # unknown what was planned
        actual=meal_text,
        notes="Logged via photo",
    )

    if success:
        await ctx.reply_markdown(
            f"✅ Logged as *{slot}*:\n_{meal_text}_"
        )
    else:
        await ctx.reply(
            f"I identified your meal but couldn't log it to the spreadsheet.\n\n"
            f"*{slot.capitalize()}:* {meal_text}"
        )

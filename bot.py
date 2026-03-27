"""
alfred/bot.py
=============
Entry point for Alfred. Initialises the Telegram bot, registers all
command and message handlers, schedules all background jobs, and starts
the polling loop.

HOW IT WORKS
------------
1. On startup:
   - Load alfred_memory.json and refresh the intent classifier prompt
   - Ensure all Google Tasks lists exist (todos, notes, shopping, gifts)
   - Start background jobs (briefing, reminders, habits, event prep, etc.)

2. Every incoming message:
   a. Rate-limit check
   b. If setup wizard is active  -> route to features/setup.py
   c. Handle media (voice/photo) -> transcribe/analyse first
   d. Classify intent via core/intent.py (Layer 1 keyword, Layer 2 GPT)
   e. Dispatch to the appropriate feature handler
   f. After /ask responses: run memory auto-suggest (non-blocking)

COMMAND REGISTRY
----------------
  /start          - welcome message (or quick capture if start=capture)
  /briefing       - trigger morning briefing now
  /todos          - list todos
  /notes          - list notes
  /shopping       - show shopping lists
  /reminders      - list reminders
  /habits         - show habit progress
  /memory         - memory management (see features/memory.py)
  /ask            - persistent conversational thread
  /calendar       - show today's calendar
  /gifts          - show gift list
  /setup          - in-Telegram onboarding wizard
  /auth           - start Google OAuth flow
  /code           - complete Google OAuth with code
  /checkauth      - verify Google auth status
  /disconnect     - revoke Google auth
  /help           - show command list
"""

import asyncio
import logging
import traceback
from datetime import time as dtime

import pytz
from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
    JobQueue,
)
from telegram.constants import ParseMode

from core.config import (
    TELEGRAM_TOKEN,
    ALLOWED_USER_ID,
    BOT_NAME,
    TIMEZONE,
    BRIEFING_HOUR, BRIEFING_MINUTE,
    HEALTH_CHECK_HOUR, HEALTH_CHECK_MINUTE,
    HABIT_NUDGE_HOUR, HABIT_NUDGE_MINUTE,
    TRAVEL_WEATHER_HOUR, TRAVEL_WEATHER_MINUTE,
    WEEKLY_SUMMARY_HOUR, WEEKLY_SUMMARY_MINUTE, WEEKLY_SUMMARY_WEEKDAY,
    EVENT_PREP_HOUR, EVENT_PREP_MINUTE,
    REMINDER_CHECK_INTERVAL,
    RATE_LIMIT_COUNT, RATE_LIMIT_WINDOW,
)
from core.data import load_memory, get_active_categories
from core.intent import classify, refresh_intent_prompt
from core.google_auth import (
    cmd_auth, cmd_code, cmd_checkauth, cmd_disconnect,
    job_google_health_check,
)
from features.memory import cmd_memory, handle_memory_callback, suggest_memory_fact
from features.setup  import cmd_setup, handle_setup_callback, handle_setup_message, is_setup_active
from features.mood          import cmd_mood, handle_mood_intent, handle_mood_callback
from features.links         import cmd_readlater, handle_link_intent, handle_link_callback
from features.export_data   import cmd_export, handle_export_intent

logger = logging.getLogger(__name__)


# =============================================================================
# RATE LIMITER
# =============================================================================

import time as _time_module
_rate_window_start: float = 0.0
_rate_message_count: int  = 0


def _check_rate_limit() -> bool:
    """Return True if the message should be allowed, False if rate-limited."""
    global _rate_window_start, _rate_message_count
    now = _time_module.monotonic()
    if now - _rate_window_start > RATE_LIMIT_WINDOW:
        _rate_window_start  = now
        _rate_message_count = 0
    _rate_message_count += 1
    return _rate_message_count <= RATE_LIMIT_COUNT


# =============================================================================
# AUTH GUARD
# =============================================================================

def _is_allowed(update: Update) -> bool:
    """Return True only if the message is from the configured user."""
    user = update.effective_user
    return user is not None and user.id == ALLOWED_USER_ID


# =============================================================================
# INTENT -> FEATURE DISPATCH
# =============================================================================

async def _dispatch(intent_result, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Route a classified intent to the appropriate feature handler.

    All feature modules are imported lazily here so circular imports are avoided
    and unbuilt features fail gracefully with a "coming soon" reply rather than
    crashing the bot.
    """
    from core.intent import (
        TODO_ADD, TODO_LIST, TODO_COMPLETE, TODO_DELETE, TODO_UPDATE,
        SHOP_ADD, SHOP_LIST, SHOP_COMPLETE, SHOP_DELETE, SHOP_CLEAR,
        NOTE_ADD, NOTE_LIST, NOTE_DELETE, NOTE_EDIT, NOTE_APPEND,
        CAL_VIEW, CAL_ADD, CAL_DELETE, CAL_UPDATE,
        HABIT_LOG, HABIT_VIEW,
        REMINDER_ADD, REMINDER_LIST, REMINDER_DONE, REMINDER_DELETE,
        GIFT_ADD, GIFT_LIST, GIFT_DONE, GIFT_DELETE,
        MEMORY_ADD, MEMORY_VIEW, MEMORY_REMOVE,
        CONTACT_VIEW, CONTACT_ADD, CONTACT_UPDATE,
        MEAL_PLAN, MEAL_VIEW, MEAL_ADD, MEAL_RECIPE, MEAL_GENERATE,
        MEAL_IMPORT, MEAL_NUTRITION, MEAL_ADHERENCE, MEAL_EXPORT, MEAL_LEFTOVERS,
        WORKOUT_LOG, WORKOUT_VIEW, WORKOUT_ASK, WORKOUT_PLAN, WORKOUT_REBUILD,
        WORKOUT_TEMPLATE, WORKOUT_EXPORT, WORKOUT_BODY,
        JOURNAL_PROMPT, JOURNAL_VIEW, JOURNAL_SEARCH, JOURNAL_MONTH, JOURNAL_WINS,
        REPLY_ASSIST, EMAIL_ASSIST, REPLY_STYLE_ADD,
        MOOD_LOG, MOOD_VIEW,
        LINK_SAVE, LINK_VIEW, LINK_SEARCH, LINK_MARK_READ, LINK_SNOOZE,
        EXPORT_DATA,
        BRIEFING, WEATHER, WEEKLY_SUMMARY,
        ASK, UNKNOWN,
    )

    intent = intent_result.intent
    ents   = intent_result.entities

    try:
        # -- TODOS ------------------------------------------------------------
        if intent in (TODO_ADD, TODO_LIST, TODO_COMPLETE, TODO_DELETE, TODO_UPDATE):
            from features.todos import handle_todo_intent
            await handle_todo_intent(intent, ents, update, context)

        # -- SHOPPING ---------------------------------------------------------
        elif intent in (SHOP_ADD, SHOP_LIST, SHOP_COMPLETE, SHOP_DELETE, SHOP_CLEAR):
            from features.shopping import handle_shopping_intent
            await handle_shopping_intent(intent, ents, update, context)

        # -- NOTES ------------------------------------------------------------
        elif intent in (NOTE_ADD, NOTE_LIST, NOTE_DELETE, NOTE_EDIT, NOTE_APPEND):
            from features.notes import handle_note_intent
            await handle_note_intent(intent, ents, update, context)

        # -- CALENDAR ---------------------------------------------------------
        elif intent in (CAL_VIEW, CAL_ADD, CAL_DELETE, CAL_UPDATE):
            from features.calendar import handle_calendar_intent
            await handle_calendar_intent(intent, ents, update, context)

        # -- HABITS -----------------------------------------------------------
        elif intent in (HABIT_LOG, HABIT_VIEW):
            from features.habits import handle_habit_intent
            await handle_habit_intent(intent, ents, update, context)

        # -- REMINDERS --------------------------------------------------------
        elif intent in (REMINDER_ADD, REMINDER_LIST, REMINDER_DONE, REMINDER_DELETE):
            from features.reminders import handle_reminder_intent
            await handle_reminder_intent(intent, ents, update, context)

        # -- GIFTS ------------------------------------------------------------
        elif intent in (GIFT_ADD, GIFT_LIST, GIFT_DONE, GIFT_DELETE):
            from features.gifts import handle_gift_intent
            await handle_gift_intent(intent, ents, update, context)

        # -- MEMORY (inline, no /memory command needed) -----------------------
        elif intent == MEMORY_ADD:
            cat  = ents.get("category", "")
            fact = ents.get("fact", "")
            if cat and fact:
                from core.data import add_memory_fact
                ok, err = add_memory_fact(cat, fact)
                if ok:
                    await update.message.reply_text(
                        f"Remembered under *{cat}*: _{fact}_",
                        parse_mode=ParseMode.MARKDOWN,
                    )
                else:
                    await update.message.reply_text(f"Couldn't save that: {err}")
            else:
                await update.message.reply_text(
                    "Use `/memory add [category] [fact]` to save a memory.",
                    parse_mode=ParseMode.MARKDOWN,
                )

        elif intent == MEMORY_VIEW:
            context.args = [ents.get("category", "")] if ents.get("category") else []
            await cmd_memory(update, context)

        elif intent == MEMORY_REMOVE:
            await update.message.reply_text(
                "To remove a specific fact, use `/memory remove [category] [number]`.",
                parse_mode=ParseMode.MARKDOWN,
            )

        # -- CONTACTS ---------------------------------------------------------
        elif intent in (CONTACT_VIEW, CONTACT_ADD, CONTACT_UPDATE):
            from features.contacts import handle_contact_intent
            await handle_contact_intent(intent, ents, update, context)

        # -- BRIEFING ---------------------------------------------------------
        elif intent == BRIEFING:
            from features.briefing import send_briefing
            await send_briefing(context, update.effective_chat.id)

        # -- WEATHER ----------------------------------------------------------
        elif intent == WEATHER:
            from features.briefing import send_weather
            location = ents.get("location")
            await send_weather(context, update.effective_chat.id, location=location)

        # -- WEEKLY SUMMARY ---------------------------------------------------
        elif intent == WEEKLY_SUMMARY:
            from features.summary import send_weekly_summary
            await send_weekly_summary(context, update.effective_chat.id)

        # -- MEALS -----------------------------------------------------------
        elif intent in (MEAL_PLAN, MEAL_VIEW, MEAL_ADD, MEAL_RECIPE, MEAL_GENERATE,
                        MEAL_IMPORT, MEAL_NUTRITION, MEAL_ADHERENCE, MEAL_EXPORT, MEAL_LEFTOVERS):
            from features.meals import handle_meal_intent
            await handle_meal_intent(intent, ents, update, context)

        # -- WORKOUT ----------------------------------------------------------
        elif intent in (WORKOUT_LOG, WORKOUT_VIEW, WORKOUT_ASK, WORKOUT_PLAN,
                        WORKOUT_REBUILD, WORKOUT_TEMPLATE, WORKOUT_EXPORT, WORKOUT_BODY):
            from features.workout import handle_workout_intent
            await handle_workout_intent(intent, ents, update, context)

        # -- JOURNAL ----------------------------------------------------------
        elif intent in (JOURNAL_PROMPT, JOURNAL_VIEW, JOURNAL_SEARCH,
                        JOURNAL_MONTH, JOURNAL_WINS):
            from features.journal import handle_journal_intent
            await handle_journal_intent(intent, ents, update, context)

        # -- REPLY / EMAIL ASSIST --------------------------------------------
        elif intent in (REPLY_ASSIST, EMAIL_ASSIST, REPLY_STYLE_ADD):
            from features.reply_assist import handle_reply_intent
            await handle_reply_intent(intent, ents, update, context)

        # -- ASK / UNKNOWN ----------------------------------------------------
        elif intent in (ASK, UNKNOWN):
            from features.ask import handle_ask
            response_text = await handle_ask(
                update.message.text or "",
                update,
                context,
            )
            # Non-blocking memory auto-suggest after /ask responses
            if response_text:
                asyncio.create_task(
                    suggest_memory_fact(
                        user_text=update.message.text or "",
                        assistant_text=response_text,
                        update=update,
                        context=context,
                    )
                )

        # -- MOOD -----------------------------------------------------------------
        elif intent in (MOOD_LOG, MOOD_VIEW):
            await handle_mood_intent(intent, ents, update, context)

        # -- LINKS (READ-LATER) ---------------------------------------------------
        elif intent in (LINK_SAVE, LINK_VIEW, LINK_SEARCH, LINK_MARK_READ, LINK_SNOOZE):
            await handle_link_intent(intent, ents, update, context)

        # -- EXPORT ---------------------------------------------------------------
        elif intent == EXPORT_DATA:
            await handle_export_intent(intent, ents, update, context)

        else:
            await update.message.reply_text(
                "I'm not sure how to handle that. Try `/help` to see what I can do.",
                parse_mode=ParseMode.MARKDOWN,
            )

    except ImportError as e:
        # Feature module not yet built -- fail gracefully
        logger.warning(f"dispatch: feature not yet built for intent '{intent}': {e}")
        await update.message.reply_text(
            "That feature is coming soon. Try `/help` to see what's available.",
        )
    except Exception as e:
        logger.error(
            f"dispatch: unhandled error for intent '{intent}': {e}\n"
            f"{traceback.format_exc()}"
        )
        await update.message.reply_text(
            "Something went wrong. Try again, or use a specific command.",
        )


# =============================================================================
# MESSAGE HANDLER (free-text and media)
# =============================================================================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Central handler for all non-command messages.

    Order of processing:
      1. Auth guard
      2. Rate limit
      3. Setup wizard intercept (if active)
      4. Voice message -> Whisper transcription
      5. Photo -> GPT-4o vision analysis
      6. Intent classification -> feature dispatch
    """
    if not _is_allowed(update):
        return

    if not _check_rate_limit():
        await update.message.reply_text(
            "You're sending messages very quickly -- slow down a little."
        )
        return

    # Setup wizard intercept
    if is_setup_active():
        await handle_setup_message(update, context)
        return

    # Voice messages — check if journal session wants voice first
    if update.message.voice or update.message.audio:
        from features.journal import is_journal_session_active, handle_voice_journal
        import os
        import tempfile

        file_obj = update.message.voice or update.message.audio
        tg_file  = await context.bot.get_file(file_obj.file_id)
        suffix = ".ogg" if update.message.voice else ".mp3"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            await tg_file.download_to_drive(tmp.name)
            tmp_path = tmp.name

        try:
            # Journal session takes priority
            if is_journal_session_active():
                await handle_voice_journal(tmp_path, update, context)
                return

            # General voice: transcribe and route as text
            text = await _transcribe_voice_file(tmp_path)
            if not text:
                await update.message.reply_text("Sorry, I couldn't understand that audio.")
                return

            # Acknowledge transcription
            await update.message.reply_text(f"🎙️ _{text}_", parse_mode="Markdown")

            # Now treat `text` as the user's message and continue to intent classification
            # Fall through with text set
        finally:
            try:
                os.unlink(tmp_path)
            except:
                pass

    # Photo messages — detect type and route appropriately
    elif update.message.photo:
        from features.reply_assist import handle_photo_for_reply
        import os
        import tempfile

        photo   = update.message.photo[-1]
        caption = (update.message.caption or "").strip()
        tg_file = await context.bot.get_file(photo.file_id)
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            await tg_file.download_to_drive(tmp.name)
            tmp_path = tmp.name

        try:
            photo_type = await _detect_photo_type(tmp_path)

            if photo_type == "receipt":
                from features.shopping import handle_receipt_photo
                await handle_receipt_photo(tmp_path, update, context)
            elif photo_type == "screenshot":
                await handle_photo_for_reply(tmp_path, update, context, is_email=False)
            else:
                # General photo — existing analysis
                description = await _analyse_photo_file(tmp_path)
                if description:
                    await update.message.reply_text(description)
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
        return

    # Text messages
    else:
        text = (update.message.text or "").strip()
        if not text:
            return

        # Journal session intercepts
        from features.journal import (
            is_journal_session_active,
            handle_journal_session_reply,
            handle_journal_freeform_reply,
            handle_voice_confirm,
        )
        if is_journal_session_active():
            consumed = await handle_journal_session_reply(text, update, context)
            if consumed:
                return
        consumed = await handle_journal_freeform_reply(text, update, context)
        if consumed:
            return
        consumed = await handle_voice_confirm(text, update, context)
        if consumed:
            return

        # Reply refinement intercept
        from features.reply_assist import looks_like_refinement, handle_refinement
        if looks_like_refinement(text):
            await handle_refinement(text, update, context)
            return

    intent_result = await classify(text)
    await _dispatch(intent_result, update, context)


# =============================================================================
# VOICE TRANSCRIPTION
# =============================================================================

async def _transcribe_voice_file(file_path: str) -> str | None:
    """Transcribe a voice file with Whisper. Returns text or None on failure."""
    from openai import AsyncOpenAI
    from core.config import OPENAI_API_KEY

    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    try:
        with open(file_path, "rb") as f:
            resp = await client.audio.transcriptions.create(model="whisper-1", file=f)
        return resp.text.strip() or None
    except Exception as e:
        logger.warning(f"Whisper transcription failed: {e}")
        return None


async def _transcribe_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    """
    Download a voice/audio message and transcribe it with OpenAI Whisper.
    Returns the transcribed text, or empty string on failure.
    """
    import os
    import tempfile
    from openai import AsyncOpenAI
    from core.config import OPENAI_API_KEY, GPT_VOICE_MODEL

    try:
        file_obj = update.message.voice or update.message.audio
        tg_file  = await context.bot.get_file(file_obj.file_id)

        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            await tg_file.download_to_drive(tmp.name)
            tmp_path = tmp.name

        client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        with open(tmp_path, "rb") as audio_file:
            transcript = await client.audio.transcriptions.create(
                model=GPT_VOICE_MODEL,
                file=audio_file,
            )

        os.unlink(tmp_path)
        return transcript.text.strip()

    except Exception as e:
        logger.error(f"voice transcription error: {e}")
        return ""


# =============================================================================
# PHOTO TYPE DETECTION
# =============================================================================

async def _detect_photo_type(file_path: str) -> str:
    """Use GPT-4o vision to classify photo as 'receipt', 'screenshot', or 'general'."""
    import base64
    from openai import AsyncOpenAI
    from core.config import OPENAI_API_KEY

    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    try:
        with open(file_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        resp = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": "Classify this image as exactly one of: 'receipt' (store/restaurant receipt showing purchased items and prices), 'screenshot' (screenshot of text messages, emails, social media, apps), or 'general' (anything else like photos of people, places, food, objects). Reply with ONLY the single word."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "low"}}
                ]
            }],
            max_tokens=10,
        )
        classification = resp.choices[0].message.content.strip().lower()
        if classification in {"receipt", "screenshot", "general"}:
            return classification
    except Exception as e:
        logger.warning(f"Photo type detection failed: {e}")
    return "general"


# =============================================================================
# PHOTO ANALYSIS
# =============================================================================

async def _analyse_photo_file(file_path: str) -> str:
    """
    Analyse a photo file using GPT-4o vision.
    Returns a text description, or empty string on failure.
    """
    import base64
    from openai import AsyncOpenAI
    from core.config import OPENAI_API_KEY, GPT_VISION_MODEL

    try:
        with open(file_path, "rb") as img_file:
            b64 = base64.b64encode(img_file.read()).decode("utf-8")

        client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        resp = await client.chat.completions.create(
            model=GPT_VISION_MODEL,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": "What is in this image? Be concise."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            }],
            max_tokens=500,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"photo analysis error: {e}")
        return ""


async def _analyse_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    """
    Analyse a photo using GPT-4o vision.

    Builds a prompt that includes any caption the user sent alongside the photo,
    then returns a text description suitable for intent classification.
    Returns empty string on failure.
    """
    import os
    import base64
    import tempfile
    from openai import AsyncOpenAI
    from core.config import OPENAI_API_KEY, GPT_VISION_MODEL

    try:
        photo   = update.message.photo[-1]   # highest resolution
        caption = (update.message.caption or "").strip()
        tg_file = await context.bot.get_file(photo.file_id)

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            await tg_file.download_to_drive(tmp.name)
            tmp_path = tmp.name

        with open(tmp_path, "rb") as img_file:
            b64 = base64.b64encode(img_file.read()).decode("utf-8")
        os.unlink(tmp_path)

        user_prompt = caption if caption else "What is in this image? Be concise."

        client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        resp   = await client.chat.completions.create(
            model=GPT_VISION_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text",      "text": user_prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    ],
                }
            ],
            max_tokens=500,
        )
        return resp.choices[0].message.content.strip()

    except Exception as e:
        logger.error(f"photo analysis error: {e}")
        return ""


# =============================================================================
# COMMAND HANDLERS
# =============================================================================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Welcome message, or quick capture mode if /start capture."""
    if not _is_allowed(update):
        return
    args = context.args or []
    if args and args[0].lower() == "capture":
        await update.message.reply_text(
            f"*Quick Capture* -- what's on your mind?\n\n"
            "Just type it and I'll figure out what to do with it.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    await update.message.reply_text(
        f"Hi! I'm *{BOT_NAME}*, your personal assistant.\n\n"
        "A few things I can do:\n"
        "- Add todos, reminders, notes, and shopping items\n"
        "- Show your calendar and send event prep briefings\n"
        "- Track your habits and summarise your week\n"
        "- Remember things about you long-term\n"
        "- Answer questions and search the web\n\n"
        "Run `/setup` to get started, or just tell me what's on your mind.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Full command reference."""
    if not _is_allowed(update):
        return
    await update.message.reply_text(
        f"*{BOT_NAME} -- Commands*\n\n"
        "*Daily*\n"
        "  /briefing -- morning briefing\n"
        "  /calendar -- today's events\n"
        "  /habits   -- habit tracker\n\n"
        "*Tasks and Lists*\n"
        "  /todos     -- manage your todo list\n"
        "  /reminders -- set and view reminders\n"
        "  /shopping  -- shopping lists\n"
        "  /notes     -- save and view notes\n"
        "  /gifts     -- gift ideas tracker\n\n"
        "*Memory and Assistant*\n"
        "  /memory -- view and edit what I remember about you\n"
        "  /ask    -- ask me anything (persistent thread)\n\n"
        "*Setup*\n"
        "  /setup      -- onboarding wizard\n"
        "  /auth       -- connect Google account\n"
        "  /checkauth  -- verify Google connection\n"
        "  /disconnect -- revoke Google access\n\n"
        "Or just type naturally -- I'll figure out what you need.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_briefing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update):
        return
    from features.briefing import send_briefing
    await send_briefing(context, update.effective_chat.id)


async def cmd_todos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update):
        return
    from features.todos import cmd_todos as _f
    await _f(update, context)


async def cmd_notes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update):
        return
    from features.notes import cmd_notes as _f
    await _f(update, context)


async def cmd_shopping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update):
        return
    from features.shopping import cmd_shopping as _f
    await _f(update, context)


async def cmd_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update):
        return
    from features.reminders import cmd_reminders as _f
    await _f(update, context)


async def cmd_habits(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update):
        return
    from features.habits import cmd_habits as _f
    await _f(update, context)


async def cmd_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update):
        return
    from features.calendar import cmd_calendar as _f
    await _f(update, context)


async def cmd_gifts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update):
        return
    from features.gifts import cmd_gifts as _f
    await _f(update, context)


async def cmd_meals(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update):
        return
    from features.meals import cmd_meals as _f
    await _f(update, context)


async def cmd_workout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update):
        return
    from features.workout import cmd_workout as _f
    await _f(update, context)


async def cmd_journal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update):
        return
    from features.journal import cmd_journal as _f
    await _f(update, context)


async def cmd_contacts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update):
        return
    from features.contacts import cmd_contacts as _f
    await _f(update, context)


async def cmd_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Persistent /ask conversational thread."""
    if not _is_allowed(update):
        return
    from features.ask import handle_ask
    text = (update.message.text or "").strip()
    if text.lower().startswith("/ask"):
        text = text[4:].strip()
    if not text:
        await update.message.reply_text(
            "What would you like to know? Type your question after `/ask`.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    response_text = await handle_ask(text, update, context)
    if response_text:
        asyncio.create_task(
            suggest_memory_fact(
                user_text=text,
                assistant_text=response_text,
                update=update,
                context=context,
            )
        )


# =============================================================================
# CALLBACK QUERY HANDLER (all inline button presses)
# =============================================================================

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Route all inline keyboard callbacks by prefix:
      mem_*   -> features/memory.py
      setup_* -> features/setup.py
    """
    query = update.callback_query
    data  = (query.data or "")

    if data.startswith("mem_"):
        await handle_memory_callback(update, context)
    elif data.startswith("setup_"):
        await handle_setup_callback(update, context)
    else:
        await query.answer()
        logger.warning(f"Unhandled callback: {data!r}")


# =============================================================================
# BACKGROUND JOBS
# =============================================================================

async def _job_briefing(context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        from features.briefing import send_briefing
        await send_briefing(context, ALLOWED_USER_ID)
    except Exception as e:
        logger.error(f"job_briefing error: {e}")


async def _job_habit_nudge(context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        from features.habits import send_habit_nudge
        await send_habit_nudge(context, ALLOWED_USER_ID)
    except Exception as e:
        logger.error(f"job_habit_nudge error: {e}")


async def _job_reminders(context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        from features.reminders import check_and_fire_reminders
        await check_and_fire_reminders(context, ALLOWED_USER_ID)
    except Exception as e:
        logger.error(f"job_reminders error: {e}")


async def _job_event_prep(context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        from features.event_prep import send_event_prep
        await send_event_prep(context, ALLOWED_USER_ID)
    except Exception as e:
        logger.error(f"job_event_prep error: {e}")


async def _job_travel_weather(context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        from features.briefing import send_travel_weather
        await send_travel_weather(context, ALLOWED_USER_ID)
    except Exception as e:
        logger.error(f"job_travel_weather error: {e}")


async def _job_weekly_summary(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Runs daily at WEEKLY_SUMMARY_HOUR; handler skips wrong weekdays."""
    import datetime
    try:
        now = datetime.datetime.now(pytz.timezone(TIMEZONE))
        if now.weekday() != WEEKLY_SUMMARY_WEEKDAY:
            return
        from features.summary import send_weekly_summary
        await send_weekly_summary(context, ALLOWED_USER_ID)
    except Exception as e:
        logger.error(f"job_weekly_summary error: {e}")


async def _job_journal_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        from core.data import load_data, get_journal_settings
        from features.journal import send_journal_reminder
        data     = load_data()
        js       = get_journal_settings(data)
        # First reminder fires at configured times — this job runs at reminder_times[0]
        await send_journal_reminder(context, ALLOWED_USER_ID, is_followup=False)
    except Exception as e:
        logger.error(f"job_journal_reminder error: {e}")


async def _job_journal_followup(context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        from features.journal import send_journal_reminder
        await send_journal_reminder(context, ALLOWED_USER_ID, is_followup=True)
    except Exception as e:
        logger.error(f"job_journal_followup error: {e}")


async def _job_meal_adherence_check(context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        from features.meals import send_meal_adherence_check
        await send_meal_adherence_check(context, ALLOWED_USER_ID)
    except Exception as e:
        logger.error(f"job_meal_adherence error: {e}")


async def _job_advance_recurring(context: ContextTypes.DEFAULT_TYPE) -> None:
    """12:01 AM job to roll recurring todos/reminders to their next date."""
    try:
        from core.data import load_data, save_data, advance_recurring_items
        data    = load_data()
        changed = advance_recurring_items(data)
        if changed:
            save_data(data)
            logger.info(f"Advanced {changed} recurring item(s).")
    except Exception as e:
        logger.error(f"job_advance_recurring error: {e}")


def _schedule_jobs(job_queue: JobQueue) -> None:
    """Register all background jobs."""
    tz = pytz.timezone(TIMEZONE)

    job_queue.run_daily(
        _job_briefing,
        time=dtime(BRIEFING_HOUR, BRIEFING_MINUTE, tzinfo=tz),
        name="daily_briefing",
    )
    job_queue.run_daily(
        job_google_health_check,
        time=dtime(HEALTH_CHECK_HOUR, HEALTH_CHECK_MINUTE, tzinfo=tz),
        name="google_health_check",
    )
    job_queue.run_daily(
        _job_habit_nudge,
        time=dtime(HABIT_NUDGE_HOUR, HABIT_NUDGE_MINUTE, tzinfo=tz),
        name="habit_nudge",
    )
    job_queue.run_daily(
        _job_event_prep,
        time=dtime(EVENT_PREP_HOUR, EVENT_PREP_MINUTE, tzinfo=tz),
        name="event_prep",
    )
    job_queue.run_daily(
        _job_travel_weather,
        time=dtime(TRAVEL_WEATHER_HOUR, TRAVEL_WEATHER_MINUTE, tzinfo=tz),
        name="travel_weather",
    )
    job_queue.run_daily(
        _job_weekly_summary,
        time=dtime(WEEKLY_SUMMARY_HOUR, WEEKLY_SUMMARY_MINUTE, tzinfo=tz),
        name="weekly_summary",
    )
    job_queue.run_repeating(
        _job_reminders,
        interval=REMINDER_CHECK_INTERVAL,
        first=10,
        name="reminder_check",
    )
    job_queue.run_daily(
        _job_advance_recurring,
        time=dtime(0, 1, tzinfo=tz),   # 12:01 AM avoids DST midnight ambiguity
        name="advance_recurring",
    )
    # Journal reminders — read configured times from userdata at runtime
    # Default: 9pm reminder, 9:30pm follow-up
    try:
        from core.data import load_data, get_journal_settings
        data = load_data()
        js   = get_journal_settings(data)
        times = js.get("reminder_times", ["21:00"])
        gap   = js.get("reminder_gap_min", 30)
        count = js.get("reminder_count", 1)
        for i, t_str in enumerate(times[:count]):
            h, m = (int(x) for x in t_str.split(":"))
            job_queue.run_daily(
                _job_journal_reminder if i == 0 else _job_journal_followup,
                time=dtime(h, m, tzinfo=tz),
                name=f"journal_reminder_{i}",
            )
            if count > 1 and gap and i == 0:
                import datetime as _dt
                fu_m = m + gap
                fu_h = h + fu_m // 60
                fu_m = fu_m % 60
                job_queue.run_daily(
                    _job_journal_followup,
                    time=dtime(fu_h % 24, fu_m, tzinfo=tz),
                    name="journal_followup",
                )
    except Exception as _e:
        # Fall back to 9pm + 9:30pm defaults
        job_queue.run_daily(_job_journal_reminder, time=dtime(21, 0, tzinfo=tz), name="journal_reminder_0")
        job_queue.run_daily(_job_journal_followup, time=dtime(21, 30, tzinfo=tz), name="journal_followup")

    # Meal adherence check — default 8pm
    try:
        from core.data import load_data, get_journal_settings
        data = load_data()
        adh_time = data.get("settings", {}).get("journal", {}).get("adherence_reminder", "20:00")
        ah, am = (int(x) for x in adh_time.split(":"))
        job_queue.run_daily(_job_meal_adherence_check, time=dtime(ah, am, tzinfo=tz), name="meal_adherence")
    except Exception:
        job_queue.run_daily(_job_meal_adherence_check, time=dtime(20, 0, tzinfo=tz), name="meal_adherence")

    logger.info("All background jobs scheduled.")


# =============================================================================
# ERROR HANDLER
# =============================================================================

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log all unhandled exceptions and notify the user if possible."""
    logger.error(f"Unhandled exception: {context.error}", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "Something went wrong on my end. I've logged the error."
            )
        except Exception:
            pass


# =============================================================================
# STARTUP HOOK
# =============================================================================

async def _on_startup(app: Application) -> None:
    """
    Runs once after the bot starts polling, before the first message.

    - Refreshes the intent classifier with live memory categories
    - Ensures all Google Tasks lists exist
    - Sets the Telegram bot command menu
    """
    logger.info(f"{BOT_NAME} starting up...")

    # Refresh intent classifier with live memory categories
    try:
        mem        = load_memory()
        categories = get_active_categories(mem)
        refresh_intent_prompt(categories)
        logger.info(f"Intent prompt refreshed ({len(categories)} categories).")
    except Exception as e:
        logger.warning(f"Startup: could not refresh intent prompt: {e}")

    # Warm up Google Tasks lists (creates missing lists)
    try:
        from core.google_auth import get_tasks_service, is_authorized
        if is_authorized():
            from adapters.google_tasks import ensure_all_lists
            service = get_tasks_service()
            if service:
                ensure_all_lists(service)
                logger.info("Google Tasks lists verified.")
    except Exception as e:
        logger.warning(f"Startup: Google Tasks warm-up failed: {e}")

    # Set Telegram bot command menu
    try:
        commands = [
            BotCommand("start",      "Get started"),
            BotCommand("briefing",   "Morning briefing"),
            BotCommand("calendar",   "Today's events"),
            BotCommand("todos",      "Todo list"),
            BotCommand("reminders",  "Reminders"),
            BotCommand("shopping",   "Shopping lists"),
            BotCommand("notes",      "Notes"),
            BotCommand("habits",     "Habit tracker"),
            BotCommand("gifts",      "Gift ideas"),
            BotCommand("meals",      "Meal planning & recipes"),
            BotCommand("workout",    "Workout tracking"),
            BotCommand("journal",    "Evening journal"),
            BotCommand("contacts",   "Personal contact notes"),
            BotCommand("mood",       "Log or view your mood"),
            BotCommand("readlater",  "View or search saved links"),
            BotCommand("export",     "Export all your data to Excel"),
            BotCommand("memory",     "What I remember about you"),
            BotCommand("ask",        "Ask me anything"),
            BotCommand("setup",      "Setup wizard"),
            BotCommand("checkauth",  "Check Google connection"),
            BotCommand("help",       "All commands"),
        ]
        await app.bot.set_my_commands(commands)
        logger.info("Bot command menu set.")
    except Exception as e:
        logger.warning(f"Startup: could not set bot commands: {e}")

    logger.info(f"{BOT_NAME} is ready.")


# =============================================================================
# MAIN
# =============================================================================

def main() -> None:
    """Build the Application, register all handlers, and start polling."""
    logging.basicConfig(
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        level=logging.INFO,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .post_init(_on_startup)
        .build()
    )

    # Command handlers
    app.add_handler(CommandHandler("start",      cmd_start))
    app.add_handler(CommandHandler("help",       cmd_help))
    app.add_handler(CommandHandler("briefing",   cmd_briefing))
    app.add_handler(CommandHandler("todos",      cmd_todos))
    app.add_handler(CommandHandler("notes",      cmd_notes))
    app.add_handler(CommandHandler("shopping",   cmd_shopping))
    app.add_handler(CommandHandler("reminders",  cmd_reminders))
    app.add_handler(CommandHandler("habits",     cmd_habits))
    app.add_handler(CommandHandler("calendar",   cmd_calendar))
    app.add_handler(CommandHandler("gifts",      cmd_gifts))
    app.add_handler(CommandHandler("meals",      cmd_meals))
    app.add_handler(CommandHandler("workout",    cmd_workout))
    app.add_handler(CommandHandler("journal",    cmd_journal))
    app.add_handler(CommandHandler("contacts",   cmd_contacts))
    app.add_handler(CommandHandler("ask",        cmd_ask))
    app.add_handler(CommandHandler("memory",     cmd_memory))
    app.add_handler(CommandHandler("setup",      cmd_setup))
    app.add_handler(CommandHandler("auth",       cmd_auth))
    app.add_handler(CommandHandler("code",       cmd_code))
    app.add_handler(CommandHandler("checkauth",  cmd_checkauth))
    app.add_handler(CommandHandler("disconnect", cmd_disconnect))
    app.add_handler(CommandHandler("mood",      cmd_mood))
    app.add_handler(CommandHandler("readlater", cmd_readlater))
    app.add_handler(CommandHandler("rl",        cmd_readlater))
    app.add_handler(CommandHandler("export",    cmd_export))

    # Inline keyboard callbacks (single handler, prefix-routed)
    app.add_handler(CallbackQueryHandler(handle_mood_callback,   pattern="^mood_"))
    app.add_handler(CallbackQueryHandler(handle_link_callback,   pattern="^link_"))
    app.add_handler(CallbackQueryHandler(handle_callback))

    # Free-text and media messages
    app.add_handler(MessageHandler(
        filters.TEXT | filters.VOICE | filters.AUDIO | filters.PHOTO,
        handle_message,
    ))

    # Global error handler
    app.add_error_handler(error_handler)

    # Background jobs
    _schedule_jobs(app.job_queue)

    logger.info("Starting polling...")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,  # ignore backlog from while offline
    )


if __name__ == "__main__":
    main()

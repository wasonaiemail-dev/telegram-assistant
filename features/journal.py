"""
marvin/features/journal.py
===========================
End-of-day journaling with prompted flow, free-form, and voice support.

STORAGE
───────
  journal.json  (JOURNAL_FILE in config)
    {date_iso: {entries: [{type, content, timestamp}], saved_at: str}}

  entries types:
    "prompted"  — content is dict {question: answer, ...}
    "freeform"  — content is str
    "voice"     — content is str (GPT-cleaned transcript)

COMMANDS
────────
  /journal          — start tonight's journal session
  /journal [date]   — view a past entry
  /journal month    — GPT summary of current month
  /journal wins     — gratitude / highlights from last 30 days
  /journal search   — keyword or date search

INTENTS HANDLED
───────────────
  JOURNAL_PROMPT, JOURNAL_VIEW, JOURNAL_SEARCH, JOURNAL_MONTH, JOURNAL_WINS

SCHEDULED JOBS (called from bot.py)
────────────────────────────────────
  send_journal_reminder(context, chat_id)   — evening journal prompt
  check_journal_for_briefing(date_iso)      — returns highlight string for briefing
"""

import os
import re
import json
import logging
import asyncio
import datetime

import pytz

from core.config import BOT_NAME, TIMEZONE, OPENAI_API_KEY, GPT_CHAT_MODEL, JOURNAL_FILE
from core.intent import (
    JOURNAL_PROMPT, JOURNAL_VIEW, JOURNAL_SEARCH, JOURNAL_MONTH, JOURNAL_WINS,
)
from core.data import (
    load_journal, save_journal, add_journal_entry, get_journal_day,
    load_data, get_journal_settings,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _today_iso() -> str:
    tz = pytz.timezone(TIMEZONE)
    return datetime.datetime.now(tz).date().isoformat()


def _yesterday_iso() -> str:
    tz = pytz.timezone(TIMEZONE)
    return (datetime.datetime.now(tz).date() - datetime.timedelta(days=1)).isoformat()


def _weekday_num() -> int:
    """0=Monday, 6=Sunday"""
    tz = pytz.timezone(TIMEZONE)
    return datetime.datetime.now(tz).weekday()


def _get_prompts_for_today() -> list[str]:
    """Return the buyer-configured prompts for today's day of week."""
    data     = load_data()
    settings = get_journal_settings(data)
    day_num  = str(_weekday_num())
    return settings.get("prompts_by_day", {}).get(day_num, [
        "What went well today?",
        "What was challenging?",
        "What are you grateful for?",
    ])


def _format_entry(entry: dict) -> str:
    """Format a single journal entry for display."""
    etype   = entry.get("type", "freeform")
    content = entry.get("content", "")
    ts      = entry.get("timestamp", "")

    if etype == "prompted" and isinstance(content, dict):
        lines = []
        for q, a in content.items():
            lines.append(f"*{q}*\n  {a}")
        return "\n\n".join(lines)
    return str(content)


def _format_day(date_iso: str, day_data: dict) -> str:
    """Format an entire day's journal for display."""
    entries = day_data.get("entries", [])
    if not entries:
        return f"No entries for {date_iso}."
    lines = [f"📓 *Journal — {date_iso}*"]
    for i, e in enumerate(entries, 1):
        if len(entries) > 1:
            lines.append(f"\n— Entry {i} ({e.get('type','')}) —")
        lines.append(_format_entry(e))
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# BRIEFING HELPER
# ─────────────────────────────────────────────────────────────────────────────

def get_yesterday_highlight() -> str:
    """
    Return a one-line highlight from yesterday's journal for the morning briefing.
    Returns "" if no entry exists or highlight extraction fails.
    """
    yesterday = _yesterday_iso()
    day_data  = get_journal_day(yesterday)
    if not day_data or not day_data.get("entries"):
        return ""
    # Try to find the "prompted" entry's first positive answer
    for entry in day_data["entries"]:
        if entry.get("type") == "prompted":
            content = entry.get("content", {})
            if isinstance(content, dict):
                for q, a in content.items():
                    if a and len(str(a)) > 5:
                        return f"📓 *Yesterday's highlight:* _{str(a)[:120]}_"
        elif entry.get("type") in ("freeform", "voice"):
            text = str(entry.get("content", ""))
            if text:
                return f"📓 *Yesterday's journal:* _{text[:120]}_"
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# STATE MACHINE (prompted session)
# ─────────────────────────────────────────────────────────────────────────────
# We use userdata["settings"]["journal"]["_active_session"] to track
# an in-progress prompted session: {date, questions, answers, current_idx}

def _get_session(data: dict) -> dict | None:
    return data.get("settings", {}).get("journal", {}).get("_active_session")


def _set_session(data: dict, session: dict | None) -> None:
    data.setdefault("settings", {}).setdefault("journal", {})["_active_session"] = session


def is_journal_session_active() -> bool:
    data = load_data()
    return bool(_get_session(data))


async def handle_journal_session_reply(text: str, ctx) -> bool:
    """
    If an active prompted session exists, record the answer and send the
    next question (or finalise the session).
    Returns True if message was consumed, False if no active session.
    ctx: MarvinContext
    """
    from core.data import save_data
    data    = load_data()
    session = _get_session(data)
    if not session:
        return False

    questions   = session["questions"]
    answers     = session.get("answers", {})
    current_idx = session.get("current_idx", 0)

    # Record the answer to the current question
    if current_idx < len(questions):
        q = questions[current_idx]
        answers[q] = text.strip()
        current_idx += 1
        session["answers"]     = answers
        session["current_idx"] = current_idx
        _set_session(data, session)
        save_data(data)

    # More questions?
    if current_idx < len(questions):
        next_q = questions[current_idx]
        await ctx.reply_markdown(f"*{current_idx + 1}/{len(questions)}* {next_q}")
        return True

    # Session complete — save and finalize
    _set_session(data, None)
    save_data(data)

    ts = datetime.datetime.utcnow().isoformat()
    add_journal_entry(session["date"], {
        "type":      "prompted",
        "content":   answers,
        "timestamp": ts,
    })

    # Offer freeform add-on
    await ctx.reply(
        "✓ Journal saved. Anything else you'd like to add? (Send text or a voice message, or type \"done\" to finish.)"
    )
    # Set a freeform follow-on flag
    from core.data import save_data
    data = load_data()
    data.setdefault("settings", {}).setdefault("journal", {})["_awaiting_freeform"] = session["date"]
    save_data(data)
    return True


async def handle_journal_freeform_reply(text: str, ctx) -> bool:
    """Handle a freeform follow-on after a prompted session. ctx: MarvinContext"""
    from core.data import save_data
    data = load_data()
    date_iso = data.get("settings", {}).get("journal", {}).get("_awaiting_freeform")
    if not date_iso:
        return False

    # Clear the flag
    data["settings"]["journal"]["_awaiting_freeform"] = None
    save_data(data)

    if text.strip().lower() in ("done", "no", "skip", "nothing"):
        await ctx.reply("Good. Sleep well 🌙")
        return True

    ts = datetime.datetime.utcnow().isoformat()
    add_journal_entry(date_iso, {
        "type":      "freeform",
        "content":   text.strip(),
        "timestamp": ts,
    })
    await ctx.reply("✓ Added to tonight's journal. Sleep well 🌙")
    return True


# ─────────────────────────────────────────────────────────────────────────────
# VOICE JOURNAL
# ─────────────────────────────────────────────────────────────────────────────

async def handle_voice_journal(file_path: str, ctx) -> None:
    """
    Transcribe a voice message with Whisper, GPT-clean it, confirm with user.
    Called from bot.py when a voice message is received during an active session.
    ctx: MarvinContext
    """
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=OPENAI_API_KEY)

    try:
        with open(file_path, "rb") as f:
            transcript_resp = await client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                response_format="text",
            )
        raw_text = transcript_resp.strip() if isinstance(transcript_resp, str) else str(transcript_resp)
    except Exception as e:
        logger.error(f"Whisper transcription failed: {e}")
        await ctx.reply("Couldn't transcribe that voice message. Try typing instead.")
        return

    # GPT clean-up
    try:
        clean_resp = await client.chat.completions.create(
            model=GPT_CHAT_MODEL,
            messages=[
                {"role": "system", "content": "You are a transcript editor. Clean up filler words, "
                 "repeated words, and run-on sentences from the following voice journal transcription. "
                 "Keep the meaning and voice intact. Return only the cleaned text, no preamble."},
                {"role": "user", "content": raw_text},
            ],
            temperature=0.3,
        )
        cleaned = clean_resp.choices[0].message.content.strip()
    except Exception:
        cleaned = raw_text  # fall back to raw

    # Show user and ask to confirm
    from core.data import save_data
    data = load_data()
    today = _today_iso()
    data.setdefault("settings", {}).setdefault("journal", {})["_pending_voice"] = {
        "date":    today,
        "content": cleaned,
    }
    save_data(data)

    await ctx.reply_markdown(
        f"🎙 *Transcription:*\n_{cleaned[:600]}_\n\n"
        f"Save this to your journal? Reply *yes* to save or *edit* + corrected text."
    )


async def handle_voice_confirm(text: str, ctx) -> bool:
    """Confirm or edit a pending voice transcription. ctx: MarvinContext"""
    from core.data import save_data
    data    = load_data()
    pending = data.get("settings", {}).get("journal", {}).get("_pending_voice")
    if not pending:
        return False

    lower = text.strip().lower()
    if lower in ("yes", "save", "ok", "yep", "yeah"):
        content = pending["content"]
        save    = True
    elif lower.startswith("edit "):
        content = text[5:].strip()
        save    = True
    elif lower in ("no", "cancel", "discard"):
        data["settings"]["journal"]["_pending_voice"] = None
        save_data(data)
        await ctx.reply("Voice journal discarded.")
        return True
    else:
        return False  # Not a voice confirm response

    if save:
        data["settings"]["journal"]["_pending_voice"] = None
        save_data(data)
        ts = datetime.datetime.utcnow().isoformat()
        add_journal_entry(pending["date"], {
            "type":      "voice",
            "content":   content,
            "timestamp": ts,
        })
        await ctx.reply("✓ Voice journal saved. Sleep well 🌙")
    return True


# ─────────────────────────────────────────────────────────────────────────────
# GPT ANALYSIS
# ─────────────────────────────────────────────────────────────────────────────

async def _gpt_monthly_summary(entries_text: str, month_label: str) -> str:
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    prompt = f"""The following are journal entries from {month_label}. Write a warm, insightful
monthly reflection that identifies themes, emotional arc, wins, struggles, and patterns.
Be honest and specific. 3-4 paragraphs. First person voice.

Journal entries:
{entries_text[:6000]}"""
    try:
        resp = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"GPT monthly summary failed: {e}")
        return "Couldn't generate monthly summary right now. Try again."


async def _gpt_wins_highlights(entries_text: str, days: int) -> str:
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    prompt = f"""From these journal entries (last {days} days), extract all positive moments,
gratitude mentions, wins (big or small), and things to be proud of.
Format as a numbered list with a brief quote or paraphrase from the entry.
Be uplifting. No preamble.

Journal entries:
{entries_text[:5000]}"""
    try:
        resp = await client.chat.completions.create(
            model=GPT_CHAT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.6,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"GPT wins failed: {e}")
        return "Couldn't extract highlights right now. Try again."


async def _gpt_search(entries_text: str, query: str) -> str:
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    prompt = f"""Search these journal entries for: "{query}"

Return only the relevant excerpts with their dates. Format each as:
[date] excerpt...

If nothing matches, say so clearly. No preamble.

Journal entries:
{entries_text[:6000]}"""
    try:
        resp = await client.chat.completions.create(
            model=GPT_CHAT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return "Search failed. Try again."


def _collect_entries_text(journal: dict, start_iso: str | None = None,
                           end_iso: str | None = None) -> str:
    """Flatten journal entries to a single string for GPT processing."""
    lines = []
    for date_iso in sorted(journal.keys()):
        if start_iso and date_iso < start_iso:
            continue
        if end_iso and date_iso > end_iso:
            continue
        day = journal[date_iso]
        for entry in day.get("entries", []):
            content = entry.get("content", "")
            if isinstance(content, dict):
                for q, a in content.items():
                    lines.append(f"[{date_iso}] Q: {q} A: {a}")
            else:
                lines.append(f"[{date_iso}] {content}")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# /journal COMMAND
# ─────────────────────────────────────────────────────────────────────────────

async def cmd_journal(ctx) -> None:
    """Start or view journal. /journal → prompt. /journal [date] → view. ctx: MarvinContext"""
    js = get_journal_settings(load_data())
    if not js.get("enabled", True):
        await ctx.reply(
            "Journal is currently disabled. "
            "Enable it in /setup → Configure preferences → Journal."
        )
        return

    args = ctx.args or []
    if args:
        # View a past entry
        date_str = " ".join(args)
        try:
            date_iso = datetime.date.fromisoformat(date_str).isoformat()
        except ValueError:
            date_iso = _today_iso()
        day_data = get_journal_day(date_iso)
        if day_data and day_data.get("entries"):
            await ctx.reply_markdown(_format_day(date_iso, day_data))
        else:
            await ctx.reply(f"No journal entry found for {date_iso}.")
        return

    # Start prompted session
    await _start_journal_session(ctx)


async def _start_journal_session(ctx) -> None:
    """ctx: MarvinContext"""
    from core.data import save_data
    questions = _get_prompts_for_today()
    if not questions:
        await ctx.reply(
            "No journal prompts configured. Say whatever you'd like and I'll save it."
        )
        return

    data = load_data()
    _set_session(data, {
        "date":        _today_iso(),
        "questions":   questions,
        "answers":     {},
        "current_idx": 0,
    })
    save_data(data)

    await ctx.reply_markdown(
        f"📓 *Evening Journal* ({_today_iso()})\n\n"
        f"*1/{len(questions)}* {questions[0]}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# INTENT HANDLER
# ─────────────────────────────────────────────────────────────────────────────

async def handle_journal_intent(intent: str, entities: dict, ctx) -> None:
    """ctx: MarvinContext"""

    # ── JOURNAL_PROMPT ────────────────────────────────────────────────────────
    if intent == JOURNAL_PROMPT:
        await _start_journal_session(ctx)
        return

    # ── JOURNAL_VIEW ──────────────────────────────────────────────────────────
    if intent == JOURNAL_VIEW:
        date_str = entities.get("date", "today")
        if date_str in ("today", ""):
            date_iso = _today_iso()
        elif date_str == "yesterday":
            date_iso = _yesterday_iso()
        else:
            try:
                date_iso = datetime.date.fromisoformat(date_str).isoformat()
            except ValueError:
                date_iso = _today_iso()
        day_data = get_journal_day(date_iso)
        if day_data and day_data.get("entries"):
            await ctx.reply_markdown(_format_day(date_iso, day_data))
        else:
            await ctx.reply(f"No journal entry found for {date_iso}.")
        return

    # ── JOURNAL_SEARCH ────────────────────────────────────────────────────────
    if intent == JOURNAL_SEARCH:
        query    = entities.get("query", "").strip()
        date_str = entities.get("date", "").strip()
        journal  = load_journal()

        if not journal:
            await ctx.reply("No journal entries yet.")
            return

        if date_str and not query:
            # Date-only lookup
            try:
                date_iso = datetime.date.fromisoformat(date_str).isoformat()
            except ValueError:
                date_iso = _today_iso()
            day_data = journal.get(date_iso)
            if day_data:
                await ctx.reply_markdown(_format_day(date_iso, day_data))
            else:
                await ctx.reply(f"No entry found for {date_iso}.")
            return

        if not query:
            await ctx.reply("What should I search for? e.g. \"search journal for stress\"")
            return

        # GPT keyword search
        await ctx.reply("🔍 Searching your journal...")
        # Optionally narrow by date
        start_iso = None
        if date_str:
            try:
                start_iso = datetime.date.fromisoformat(date_str).isoformat()
            except ValueError:
                pass
        text   = _collect_entries_text(journal, start_iso=start_iso)
        result = await _gpt_search(text, query)
        await ctx.reply_markdown(f"🔍 *Search: \"{query}\"*\n\n{result}")
        return

    # ── JOURNAL_MONTH ─────────────────────────────────────────────────────────
    if intent == JOURNAL_MONTH:
        month_str = entities.get("month", "")
        tz        = pytz.timezone(TIMEZONE)
        now       = datetime.datetime.now(tz)
        if month_str:
            try:
                dt        = datetime.datetime.strptime(month_str, "%Y-%m")
                month_iso = dt.strftime("%Y-%m")
            except ValueError:
                month_iso = now.strftime("%Y-%m")
        else:
            month_iso = now.strftime("%Y-%m")

        journal   = load_journal()
        start_iso = month_iso + "-01"
        end_iso   = month_iso + "-31"
        text      = _collect_entries_text(journal, start_iso=start_iso, end_iso=end_iso)
        if not text:
            await ctx.reply(f"No journal entries found for {month_iso}.")
            return

        await ctx.reply("⏳ Writing your monthly reflection...")
        summary = await _gpt_monthly_summary(text, month_label=month_iso)
        await ctx.reply_markdown(f"📓 *{month_iso} Monthly Reflection*\n\n{summary}")
        return

    # ── JOURNAL_WINS ──────────────────────────────────────────────────────────
    if intent == JOURNAL_WINS:
        days    = int(entities.get("days", 30))
        journal = load_journal()
        tz      = pytz.timezone(TIMEZONE)
        cutoff  = (datetime.datetime.now(tz).date() - datetime.timedelta(days=days)).isoformat()
        text    = _collect_entries_text(journal, start_iso=cutoff)
        if not text:
            await ctx.reply(f"No journal entries in the last {days} days.")
            return
        await ctx.reply("⏳ Finding your highlights...")
        wins = await _gpt_wins_highlights(text, days)
        await ctx.reply_markdown(f"🌟 *Wins & Gratitude — Last {days} Days*\n\n{wins}")
        return


# ─────────────────────────────────────────────────────────────────────────────
# SCHEDULED: journal reminder
# ─────────────────────────────────────────────────────────────────────────────

async def send_journal_reminder(ctx, is_followup: bool = False) -> None:
    """Send the nightly journal reminder. ctx: MarvinContext"""
    js = get_journal_settings(load_data())
    if not js.get("enabled", True):
        return  # Buyer disabled journal reminders

    today    = _today_iso()
    day_data = get_journal_day(today)

    if day_data and day_data.get("entries"):
        return  # Already journaled today

    prefix = "One more reminder 📓 " if is_followup else ""
    await ctx.reply_markdown(
        f"{prefix}*Evening Journal* 📓\n\n"
        f"Time to reflect on your day. Send /journal to start, "
        f"or just send a voice message and I'll transcribe it for you."
    )

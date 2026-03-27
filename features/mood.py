"""
alfred/features/mood.py
=======================
Mood tracking — log emotional state with ratings and view trends.

STORAGE
───────
  userdata.json["mood_log"]: list of mood entries
    {date: "2026-03-27", rating: 8, note: "Good workout day", ts: 1234567890}

COMMANDS
────────
  /mood              — log today's mood or show quick rating buttons
  /mood view         — show last 7 days of mood entries
  /mood history N    — show last N days

INTENT HANDLER
──────────────
  handle_mood_intent(intent, entities, update, context)
    MOOD_LOG  — log a mood rating (1-10 with optional note)
    MOOD_VIEW — show recent mood history
"""

import logging
import datetime
import time
import re
from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from core.config import BOT_NAME, TIMEZONE
from core.intent import MOOD_LOG, MOOD_VIEW
from core.data import load_data, save_data

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _today_str() -> str:
    """Return today's date as ISO string."""
    tz = ZoneInfo(TIMEZONE)
    return datetime.datetime.now(tz).date().isoformat()


def _now_ts() -> float:
    """Return current Unix timestamp."""
    return time.time()


# ─────────────────────────────────────────────────────────────────────────────
# CORE FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def log_mood(rating: int, note: str, data: dict) -> str:
    """
    Log a mood entry. Rating should be 1-10.
    Returns a confirmation string.
    """
    rating = max(1, min(10, int(rating)))
    today = _today_str()

    mood_log = data.setdefault("mood_log", [])

    # Check if we already have an entry for today; if so, update it
    for entry in mood_log:
        if entry.get("date") == today:
            entry["rating"] = rating
            entry["note"] = note
            entry["ts"] = _now_ts()
            save_data(data)
            return f"✓ Updated today's mood to {rating}/10"

    # Add new entry
    mood_log.append({
        "date": today,
        "rating": rating,
        "note": note.strip() if note else "",
        "ts": _now_ts(),
    })
    save_data(data)

    emoji = "😭" if rating <= 3 else "😕" if rating <= 5 else "😐" if rating <= 7 else "😊" if rating <= 9 else "🤩"
    return f"{emoji} Logged mood {rating}/10" + (f" — {note}" if note else "")


def get_mood_trend(days: int, data: dict) -> list:
    """Return last N days of mood entries."""
    cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    mood_log = data.get("mood_log", [])
    return [e for e in mood_log if e.get("date", "") >= cutoff]


def get_mood_summary_text(days: int, data: dict) -> str:
    """
    Return a brief 1-2 line mood summary for briefing.
    E.g. "Avg mood 7.2/10 this week, trending up ↑"
    """
    entries = get_mood_trend(days, data)
    if not entries:
        return ""

    ratings = [e.get("rating", 0) for e in entries if e.get("rating")]
    if not ratings:
        return ""

    avg = sum(ratings) / len(ratings)
    trend = "↑" if len(ratings) >= 2 and ratings[-1] > ratings[0] else "↓" if len(ratings) >= 2 else "→"

    return f"Mood avg {avg:.1f}/10 last {days}d, {trend}"


async def _gpt_mood_analysis(entries: list) -> str:
    """
    Use GPT-4o-mini to analyze mood patterns and suggest insights.
    Returns a formatted string (2-4 bullet points max).
    """
    if not entries or len(entries) < 3:
        return ""

    from openai import AsyncOpenAI
    from core.config import OPENAI_API_KEY, GPT_CHAT_MODEL

    # Format entries for GPT
    formatted = []
    for e in entries[-14:]:  # last 14 days
        formatted.append(f"{e.get('date')}: rating {e.get('rating')}/10" + (f", {e.get('note')}" if e.get("note") else ""))

    prompt = f"""Analyze these mood entries and identify 2-4 brief, actionable patterns:

{chr(10).join(formatted)}

Respond with short bullet points (max 2-4) about patterns, triggers, or suggestions. Be concise."""

    try:
        client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        resp = await client.chat.completions.create(
            model=GPT_CHAT_MODEL,
            messages=[
                {"role": "system", "content": "You are a behavioral pattern analyst. Identify mood trends in brief, actionable points."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=150,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.warning(f"mood: GPT analysis error: {e}")
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# COMMANDS
# ─────────────────────────────────────────────────────────────────────────────

async def cmd_mood(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /mood command: show buttons for quick logging or view history."""
    if not update.message:
        return

    args = context.args or []
    text = " ".join(args).lower() if args else ""

    if text in ("view", "history", "show"):
        # Show last 7 days
        data = load_data()
        entries = get_mood_trend(7, data)
        if not entries:
            await update.message.reply_text("No mood entries yet. Use /mood to log one!")
            return

        lines = ["📊 *Mood History (Last 7 Days)*\n"]
        for e in sorted(entries, key=lambda x: x.get("date", "")):
            rating = e.get("rating", 0)
            emoji = "😭😕😐😊🤩"[min(4, max(0, rating - 1))]
            note = e.get("note", "")
            lines.append(f"{e.get('date')} • {rating}/10 {emoji}" + (f" • {note}" if note else ""))

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        return

    # Show quick-log buttons (1-10)
    keyboard = []
    for row_start in range(1, 11, 5):
        row = [
            InlineKeyboardButton(str(i), callback_data=f"mood_rate_{i}")
            for i in range(row_start, min(row_start + 5, 11))
        ]
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("View This Week", callback_data="mood_view_7")])

    markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "How are you feeling today? Pick a rating (1–10):",
        reply_markup=markup,
    )


# ─────────────────────────────────────────────────────────────────────────────
# CALLBACK HANDLERS
# ─────────────────────────────────────────────────────────────────────────────

async def handle_mood_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle mood rating and view callbacks."""
    query = update.callback_query
    data_str = query.data or ""

    if data_str.startswith("mood_rate_"):
        rating = int(data_str.split("_")[-1])
        data = load_data()
        msg = log_mood(rating, "", data)
        await query.answer(msg)
        await query.edit_message_text(msg)

    elif data_str == "mood_view_7":
        data = load_data()
        entries = get_mood_trend(7, data)
        if not entries:
            await query.answer("No mood entries yet.")
            return

        lines = ["📊 *Mood History (Last 7 Days)*\n"]
        for e in sorted(entries, key=lambda x: x.get("date", "")):
            rating = e.get("rating", 0)
            emoji = "😭😕😐😊🤩"[min(4, max(0, rating - 1))]
            note = e.get("note", "")
            lines.append(f"{e.get('date')} • {rating}/10 {emoji}" + (f" • {note}" if note else ""))

        await query.answer()
        await query.edit_message_text("\n".join(lines), parse_mode="Markdown")


# ─────────────────────────────────────────────────────────────────────────────
# INTENT HANDLER
# ─────────────────────────────────────────────────────────────────────────────

async def handle_mood_intent(intent: str, entities: dict, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route MOOD_LOG and MOOD_VIEW intents."""
    if not update.message:
        return

    data = load_data()

    if intent == MOOD_LOG:
        # Extract rating from entities or text
        rating = entities.get("rating")
        note = entities.get("note", "")

        if rating is None:
            # Try to extract from text
            text = update.message.text or ""
            match = re.search(r'(\d+)\s*(?:/10)?', text)
            if match:
                rating = int(match.group(1))
            else:
                await update.message.reply_text("Please include a rating (1–10) like '8/10' or just '8'.")
                return

        msg = log_mood(rating, note, data)
        await update.message.reply_text(msg)

    elif intent == MOOD_VIEW:
        days = entities.get("days", 7)
        entries = get_mood_trend(days, data)
        if not entries:
            await update.message.reply_text(f"No mood entries in the last {days} days.")
            return

        lines = [f"📊 *Mood History (Last {days} Days)*\n"]
        for e in sorted(entries, key=lambda x: x.get("date", "")):
            rating = e.get("rating", 0)
            emoji = "😭😕😐😊🤩"[min(4, max(0, rating - 1))]
            note = e.get("note", "")
            lines.append(f"{e.get('date')} • {rating}/10 {emoji}" + (f" • {note}" if note else ""))

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

"""
alfred/features/habits.py
==========================
Habit tracker — log completions and view progress.

COMMANDS
────────
  /habits                  — show today's habit status
  /habits log [habit]      — manually log a habit completion
  /habits history [days]   — show last N days of habit history (default 7)

INTENT HANDLER
──────────────
  handle_habit_intent(intent, entities, update, context)

  Supported intents:
    HABIT_LOG   — triggered by keyword phrases from HABIT_KEYWORDS config
                  e.g. "worked out today", "meditation done"
                  entities: {"habit_id": "workout"}
    HABIT_VIEW  — "show my habits" / "how are my habits"

BACKGROUND JOB
──────────────
  send_habit_nudge(context, chat_id)
      Called at HABIT_NUDGE_HOUR. Checks which habits haven't been logged
      today and sends a friendly nudge listing the missing ones.

PUBLIC
──────
  get_yesterday_summary() → str
      Returns a brief summary for the morning briefing showing how many
      habits were completed yesterday vs the total.

STORAGE
───────
  Habit log entries live in userdata.json["habit_log"]:
  [{"habit": "workout", "date": "2024-03-15", "note": ""}, ...]
"""

import logging
import datetime
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import ContextTypes

from core.config import (
    BOT_NAME, TIMEZONE,
    HABITS, HABIT_LABELS, HABIT_KEYWORDS,
)
from core.intent import HABIT_LOG, HABIT_VIEW

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _now_local() -> datetime.datetime:
    return datetime.datetime.now(ZoneInfo(TIMEZONE))


def _today_str() -> str:
    return _now_local().strftime("%Y-%m-%d")


def _yesterday_str() -> str:
    return (_now_local() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")


def _load_log() -> tuple[dict, list]:
    """Return (data, habit_log)."""
    from core.data import load_data
    data = load_data()
    return data, data.get("habit_log", [])


def _save_log(data: dict) -> None:
    from core.data import save_data
    save_data(data)


def _logged_today(habit_log: list, date: str | None = None) -> set[str]:
    """Return the set of habit IDs logged on `date` (default today)."""
    target = date or _today_str()
    return {e["habit"] for e in habit_log if e.get("date") == target}


def _logged_on(habit_log: list, date: str) -> set[str]:
    return {e["habit"] for e in habit_log if e.get("date") == date}


def _label(habit_id: str) -> str:
    return HABIT_LABELS.get(habit_id, habit_id.replace("_", " ").title())


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC: get_yesterday_summary  (used by briefing.py)
# ─────────────────────────────────────────────────────────────────────────────

def get_yesterday_summary() -> str:
    """
    Return a short summary of yesterday's habit completions.
    Returns empty string if no habits are configured.
    """
    if not HABITS:
        return ""

    _, habit_log   = _load_log()
    yesterday      = _yesterday_str()
    done_yesterday = _logged_on(habit_log, yesterday)
    total          = len(HABITS)
    done_count     = sum(1 for h in HABITS if h in done_yesterday)

    if done_count == 0:
        return f"  _(No habits logged yesterday)_"

    lines = [f"  {done_count}/{total} habits completed"]
    for h in HABITS:
        mark = "✓" if h in done_yesterday else "✗"
        lines.append(f"  {mark} {_label(h)}")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# DISPLAY
# ─────────────────────────────────────────────────────────────────────────────

def _format_today_status(habit_log: list) -> str:
    """Format today's habit status for Telegram."""
    if not HABITS:
        return "💪 *Habits*\n  _No habits configured. Edit HABITS in config.py._"

    today = _today_str()
    done  = _logged_today(habit_log)
    lines = [f"💪 *Habits — Today*"]

    for h in HABITS:
        mark  = "✅" if h in done else "⬜"
        label = _label(h)
        lines.append(f"  {mark} {label}")

    done_count = sum(1 for h in HABITS if h in done)
    total      = len(HABITS)
    lines.append(f"\n  _{done_count}/{total} done_")
    return "\n".join(lines)


def _format_history(habit_log: list, days: int = 7) -> str:
    """Format last N days of habit history."""
    if not HABITS:
        return "💪 *Habit History*\n  _No habits configured._"

    now  = _now_local()
    lines = [f"💪 *Habit History (last {days} days)*\n"]

    # Header row
    header = "Date       "
    for h in HABITS:
        header += f"{_label(h)[:6]:<7}"
    lines.append(header)

    for i in range(days - 1, -1, -1):
        date = (now - datetime.timedelta(days=i)).strftime("%Y-%m-%d")
        done = _logged_on(habit_log, date)
        row  = f"{date}  "
        for h in HABITS:
            row += ("✅  " if h in done else "⬜  ")
        lines.append(row)

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# BACKGROUND JOB: send_habit_nudge
# ─────────────────────────────────────────────────────────────────────────────

async def send_habit_nudge(context, chat_id: int) -> None:
    """
    Send a nudge for habits not yet logged today.
    Silently skips if all habits are done or no habits configured.
    """
    if not HABITS:
        return

    _, habit_log = _load_log()
    done_today   = _logged_today(habit_log)
    missing      = [h for h in HABITS if h not in done_today]

    if not missing:
        return  # All done — no nudge needed

    lines = [f"👋 *Habit Check-In*\n"]
    lines.append("Still to log today:")
    for h in missing:
        lines.append(f"  • {_label(h)}")
    lines.append(f"\n_{len(HABITS) - len(missing)}/{len(HABITS)} done so far._")

    await context.bot.send_message(
        chat_id=chat_id,
        text="\n".join(lines),
        parse_mode="Markdown",
    )


# ─────────────────────────────────────────────────────────────────────────────
# /habits COMMAND
# ─────────────────────────────────────────────────────────────────────────────

async def cmd_habits(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /habits [log [habit] | history [days]]
    """
    args = context.args or []
    data, habit_log = _load_log()

    if not args:
        await update.message.reply_text(
            _format_today_status(habit_log),
            parse_mode="Markdown",
        )
        return

    sub = args[0].lower()

    if sub == "log":
        # /habits log [habit_name_or_id]
        if len(args) < 2:
            labels = ", ".join(_label(h) for h in HABITS)
            await update.message.reply_text(
                f"Which habit? Options: {labels}\n"
                f"Example: /habits log workout"
            )
            return

        query    = " ".join(args[1:]).lower().strip()
        habit_id = None

        # Match by ID or label
        for h in HABITS:
            if query == h or query == _label(h).lower():
                habit_id = h
                break
        # Partial match
        if not habit_id:
            matches = [h for h in HABITS if query in h or query in _label(h).lower()]
            if len(matches) == 1:
                habit_id = matches[0]

        if not habit_id:
            labels = ", ".join(_label(h) for h in HABITS)
            await update.message.reply_text(
                f"Unknown habit \"{query}\". Options: {labels}"
            )
            return

        today = _today_str()
        done  = _logged_today(habit_log)
        if habit_id in done:
            await update.message.reply_text(
                f"✅ *{_label(habit_id)}* is already logged for today.",
                parse_mode="Markdown",
            )
            return

        data.setdefault("habit_log", []).append({
            "habit": habit_id,
            "date":  today,
            "note":  "",
        })
        _save_log(data)
        await update.message.reply_text(
            f"✅ Logged: *{_label(habit_id)}*",
            parse_mode="Markdown",
        )
        return

    if sub == "history":
        days = 7
        if len(args) > 1:
            try:
                days = max(1, min(30, int(args[1])))
            except ValueError:
                pass
        await update.message.reply_text(
            _format_history(habit_log, days),
            parse_mode="Markdown",
        )
        return

    await update.message.reply_text(
        "Usage:\n"
        "  /habits — today's status\n"
        "  /habits log [habit] — log a habit\n"
        "  /habits history [days] — view history"
    )


# ─────────────────────────────────────────────────────────────────────────────
# INTENT HANDLER
# ─────────────────────────────────────────────────────────────────────────────

async def handle_habit_intent(
    intent:   str,
    entities: dict,
    update:   Update,
    context:  ContextTypes.DEFAULT_TYPE,
) -> None:
    """Dispatch HABIT_LOG and HABIT_VIEW intents."""

    data, habit_log = _load_log()

    # ── HABIT_LOG ─────────────────────────────────────────────────────────────
    if intent == HABIT_LOG:
        habit_id = entities.get("habit_id", "")
        if not habit_id or habit_id not in HABITS:
            # Shouldn't happen (keyword rules only fire for known habits)
            await update.message.reply_text(
                "I didn't catch which habit that was. Try /habits log [habit]."
            )
            return

        today = _today_str()
        done  = _logged_today(habit_log)

        if habit_id in done:
            await update.message.reply_text(
                f"✅ *{_label(habit_id)}* already logged for today.",
                parse_mode="Markdown",
            )
            return

        data.setdefault("habit_log", []).append({
            "habit": habit_id,
            "date":  today,
            "note":  "",
        })
        _save_log(data)

        # Count how many are done now
        done.add(habit_id)
        done_count = sum(1 for h in HABITS if h in done)
        total      = len(HABITS)

        if done_count == total:
            msg = f"✅ *{_label(habit_id)}* logged! All {total} habits done today. 🎉"
        else:
            msg = f"✅ *{_label(habit_id)}* logged! _{done_count}/{total} today._"

        await update.message.reply_text(msg, parse_mode="Markdown")
        return

    # ── HABIT_VIEW ────────────────────────────────────────────────────────────
    if intent == HABIT_VIEW:
        await update.message.reply_text(
            _format_today_status(habit_log),
            parse_mode="Markdown",
        )
        return


# ─────────────────────────────────────────────────────────────────────────────
# SMART PATTERN SUGGESTIONS
# ─────────────────────────────────────────────────────────────────────────────

async def _gpt_habit_suggestions(habit_data: list, journal_data: dict, mood_data: list, enabled_areas: list) -> str:
    """
    Analyze habits + optionally journal/mood for smart pattern-based suggestions.
    enabled_areas: list of strings from ["habits", "workout", "meals", "mood_journal", "shopping"]
    Returns a formatted string with 2-4 actionable observations.
    """
    from openai import AsyncOpenAI
    from core.config import OPENAI_API_KEY, GPT_CHAT_MODEL

    # Prepare habit summary (last 30 days)
    import datetime as _dt
    cutoff = (_dt.date.today() - _dt.timedelta(days=30)).isoformat()
    recent_entries = [e for e in habit_data if e.get("date", "") >= cutoff]

    if not recent_entries:
        return ""

    # Count completions per habit
    habit_counts = {}
    for e in recent_entries:
        h = e.get("habit")
        habit_counts[h] = habit_counts.get(h, 0) + 1

    habit_summary = "\n".join(
        f"  - {h}: {habit_counts.get(h, 0)}/30 days" for h in HABITS
    )

    # Prepare journal snippet if enabled
    journal_snippet = ""
    if "mood_journal" in enabled_areas and journal_data:
        journal_entries = sorted(journal_data.keys(), reverse=True)[:14]
        journal_snippet = f"\nRecent journal: {len(journal_entries)} entries in last 2 weeks"

    # Prepare mood snippet if enabled
    mood_snippet = ""
    if "mood_journal" in enabled_areas and mood_data:
        recent_moods = [m for m in mood_data if m.get("date", "") >= cutoff]
        if recent_moods:
            avg_mood = sum(m.get("rating", 0) for m in recent_moods) / len(recent_moods)
            mood_snippet = f"\nAverage mood: {avg_mood:.1f}/10 (last 30d)"

    system_prompt = (
        "You are a behavioral pattern analyst. Analyze habit completion data and "
        "identify 2-4 brief, actionable patterns or suggestions. Be specific and encouraging."
    )

    user_prompt = f"""Analyze these 30-day habit trends:

{habit_summary}{journal_snippet}{mood_snippet}

Provide 2-4 concise observations about what's working well, patterns, or gentle nudges."""

    try:
        client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        resp = await client.chat.completions.create(
            model=GPT_CHAT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=200,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.warning(f"habits: GPT suggestions error: {e}")
        return ""


async def get_habit_suggestions_text(data: dict) -> str:
    """Called by weekly summary to inject smart suggestions section."""
    settings = data.get("settings", {}).get("smart_suggestions", {})
    if not settings.get("enabled", True):
        return ""

    enabled_areas = settings.get("areas", ["habits"])
    habits_data = data.get("habit_log", [])

    if not habits_data:
        return ""

    # Load optional journal/mood data if enabled
    journal_data = {}
    mood_data = []

    if "mood_journal" in enabled_areas:
        from core.data import load_journal
        journal_data = load_journal()
        mood_data = data.get("mood_log", [])

    analysis = await _gpt_habit_suggestions(habits_data, journal_data, mood_data, enabled_areas)
    if not analysis:
        return ""

    return f"💡 *Smart Insights*\n{analysis}"

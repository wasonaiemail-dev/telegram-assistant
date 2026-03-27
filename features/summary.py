"""
alfred/features/summary.py
===========================
Weekly summary — a GPT-powered review of the week's activity.

PUBLIC INTERFACE
────────────────
  send_weekly_summary(context, chat_id)
      Called every Sunday at WEEKLY_SUMMARY_HOUR by the background job,
      or on-demand by the WEEKLY_SUMMARY intent.

      Compiles:
        - Habit completions this week
        - Calendar events this week (from Google Calendar)
        - Completed todos this week (from Google Tasks)
        - Memory context (full, via get_full_context())
      Sends a GPT-generated narrative summary.

SUMMARY STYLE
─────────────
  The summary reads like a brief, friendly weekly review — not a data dump.
  GPT writes it as 3–5 short paragraphs covering: what the week looked like,
  habit performance, and a short forward-looking nudge for next week.
"""

import asyncio
import logging
import datetime
from zoneinfo import ZoneInfo

from core.config import (
    BOT_NAME,
    TIMEZONE,
    OPENAI_API_KEY,
    GPT_CHAT_MODEL,
    HABITS,
    HABIT_LABELS,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _now_local() -> datetime.datetime:
    return datetime.datetime.now(ZoneInfo(TIMEZONE))


def _habit_label(habit_id: str) -> str:
    return HABIT_LABELS.get(habit_id, habit_id.replace("_", " ").title())


# ─────────────────────────────────────────────────────────────────────────────
# DATA GATHERING
# ─────────────────────────────────────────────────────────────────────────────

def _get_habit_summary(completed_habits: dict) -> str:
    """Format habit completion rates for the week."""
    if not HABITS:
        return ""
    lines = []
    for h in HABITS:
        count = completed_habits.get(h, 0)
        lines.append(f"  - {_habit_label(h)}: {count}/7 days")
    return "Habits this week:\n" + "\n".join(lines)


def _get_calendar_summary(svc) -> str:
    """Get a list of this week's calendar events."""
    try:
        from adapters.google_calendar import get_weeks_events, format_event_brief
        events = get_weeks_events(svc)
        if not events:
            return "No calendar events this week."
        lines = ["Calendar events this week:"]
        for ev in events[:10]:  # cap at 10 to keep prompt manageable
            lines.append(f"  - {format_event_brief(ev)}")
        if len(events) > 10:
            lines.append(f"  ...and {len(events) - 10} more")
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"_get_calendar_summary: {e}")
        return ""


def _get_todos_summary(svc) -> str:
    """Get completed todos from Google Tasks this week."""
    import pytz, datetime as _dt
    tz = pytz.timezone(TIMEZONE)
    now = _dt.datetime.now(tz)
    week_start = (now - _dt.timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    try:
        from adapters.google_tasks import list_todos
        todos = list_todos(svc, include_done=True)
        # Filter completed this week — Google Tasks doesn't have a
        # "completed date" easily accessible, so we approximate
        # by checking if status == "completed" (recent completions are likely this week)
        completed = [t for t in todos if t.get("status") == "completed"]
        if not completed:
            return "No todos completed this week."
        lines = ["Completed todos:"]
        for t in completed[:10]:
            lines.append(f"  - {t.get('title', '(untitled)')}")
        if len(completed) > 10:
            lines.append(f"  ...and {len(completed) - 10} more")
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"_get_todos_summary: {e}")
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# GPT SUMMARY GENERATION
# ─────────────────────────────────────────────────────────────────────────────

_SUMMARY_SYSTEM = (
    "You are {bot_name}, a personal assistant writing a warm, friendly weekly review. "
    "Keep it to 3–5 short paragraphs. Cover what the week looked like, habit performance "
    "(highlight wins, gently note misses), and close with one forward-looking observation "
    "or nudge for next week. Do not use bullet points. Write in a warm, direct tone."
)

_SUMMARY_USER = """Here's the data from this week ({week_start} to {week_end}):

{habit_block}

{calendar_block}

{todos_block}

{memory_block}

Write the weekly summary now."""


async def _generate_summary(
    week_start:     str,
    week_end:       str,
    habit_block:    str,
    calendar_block: str,
    todos_block:    str,
    memory_block:   str,
) -> str:
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=OPENAI_API_KEY)

    system = _SUMMARY_SYSTEM.format(bot_name=BOT_NAME)
    user   = _SUMMARY_USER.format(
        week_start=week_start,
        week_end=week_end,
        habit_block=habit_block or "No habit data.",
        calendar_block=calendar_block or "No calendar data.",
        todos_block=todos_block or "No completed todos.",
        memory_block=(
            f"User context:\n{memory_block}" if memory_block else ""
        ),
    )

    try:
        resp = await client.chat.completions.create(
            model=GPT_CHAT_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            temperature=0.7,
            max_tokens=600,
            timeout=30,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"_generate_summary GPT error: {e}")
        return (
            "Here's a quick look at your week:\n\n"
            f"{habit_block or 'No habit data.'}\n\n"
            f"{calendar_block or 'No calendar events.'}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC: send_weekly_summary
# ─────────────────────────────────────────────────────────────────────────────

async def send_weekly_summary(context, chat_id: int) -> None:
    """
    Compile and send the weekly summary.
    """
    from core.data import get_week_summary_data
    from features.memory import get_full_context
    from core.google_auth import is_authorized, get_calendar_service, get_tasks_service

    # Always gather habit/local data
    week_data = get_week_summary_data()
    habit_block = _get_habit_summary(week_data.get("completed_habits", {}))

    week_start = week_data.get("week_start", "")
    week_end   = week_data.get("week_end", "")

    # Calendar and tasks need Google auth
    calendar_block = ""
    todos_block    = ""

    if is_authorized():
        cal_svc = get_calendar_service()
        if cal_svc:
            calendar_block = _get_calendar_summary(cal_svc)

        tasks_svc = get_tasks_service()
        if tasks_svc:
            todos_block = _get_todos_summary(tasks_svc)

    # Full memory context for summary
    memory_block = get_full_context()

    # Generate GPT summary
    summary = await _generate_summary(
        week_start=week_start,
        week_end=week_end,
        habit_block=habit_block,
        calendar_block=calendar_block,
        todos_block=todos_block,
        memory_block=memory_block,
    )

    now = _now_local()
    header = f"📊 *Weekly Summary — Week of {week_start}*\n\n"

    await context.bot.send_message(
        chat_id=chat_id,
        text=header + summary,
        parse_mode="Markdown",
    )

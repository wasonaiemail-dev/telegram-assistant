"""
alfred/features/proactive.py
=============================
Proactive intelligence layer — Alfred notices things without being asked.

All 25 notification types, organised into four categories:
  - Daily checks        (fire each day when relevant)
  - Pattern recognition (weekly, cross-data correlations)
  - Calendar intel      (calendar-aware nudges)
  - Weekly reflections  (Monday + Sunday summaries)

SCHEDULE
────────
  Daily analysis  → _job_proactive_daily   (configurable, default 8:30am)
  Weekly analysis → _job_proactive_weekly  (Monday morning, after briefing)

Each check is de-duplicated: a check won't fire again for the same calendar
day (or week) unless its data has meaningfully changed. Tracked in
userdata.json["proactive_sent"] = {check_key: "YYYY-MM-DD"}.

COMMANDS
────────
  /proactive              — show all toggles + current state
  "turn off [check]"      — NL toggle off
  "enable [check]"        — NL toggle on
  "proactive settings"    — same as /proactive

TOGGLE KEYS
───────────
  habit_streak_risk, overdue_todos, priority_todos, back_to_back_meetings,
  reminder_overload, sleep_mood_correlation, sleep_declining,
  workout_frequency, expense_spike, mood_trend_low, todo_bloat,
  recurring_todo_stuck, mood_habit_correlation, expense_pacing,
  meeting_prep, calendar_gap_workout, travel_time_missing,
  sleep_important_event, empty_calendar, monday_planning,
  weekly_completion, habit_best_day, streak_recognition,
  shopping_weekend, smart_note_resurface

PUBLIC
──────
  cmd_proactive(ctx)                   — /proactive command handler
  handle_proactive_toggle(intent, entities, ctx)
  run_daily_checks(ctx)                — called by bot.py job
  run_weekly_analysis(ctx)             — called by bot.py job
"""

from __future__ import annotations

import datetime
import logging
from zoneinfo import ZoneInfo

from core.alfred_context import AlfredContext
from core.config import TIMEZONE, HABITS, HABIT_LABELS, BOT_NAME
from core.data import load_data, save_data, get_proactive_settings, get_sleep_schedule_settings

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _now() -> datetime.datetime:
    return datetime.datetime.now(ZoneInfo(TIMEZONE))

def _today() -> str:
    return _now().strftime("%Y-%m-%d")

def _this_week_start() -> str:
    """Return ISO date string for Monday of the current week."""
    n = _now()
    monday = n - datetime.timedelta(days=n.weekday())
    return monday.strftime("%Y-%m-%d")

def _label(habit_id: str) -> str:
    return HABIT_LABELS.get(habit_id, habit_id.replace("_", " ").title())

def _is_quiet_hours(data: dict) -> bool:
    """
    Return True if the current time falls inside the user's DND window.
    When True, all proactive jobs skip silently.

    DND is stored as "HH:MM" strings and can span midnight (e.g. 22:00 – 07:00).
    If DND is disabled or settings are missing, always returns False.
    """
    ss = get_sleep_schedule_settings(data)
    if not ss.get("dnd_enabled", True):
        return False

    start_str = ss.get("dnd_start", "22:00")
    end_str   = ss.get("dnd_end",   "07:00")

    try:
        sh, sm = (int(x) for x in start_str.split(":"))
        eh, em = (int(x) for x in end_str.split(":"))
    except (ValueError, AttributeError):
        return False

    now   = _now()
    now_m = now.hour * 60 + now.minute
    s_m   = sh * 60 + sm
    e_m   = eh * 60 + em

    if s_m <= e_m:
        # Same-day window (e.g. 02:00 – 06:00)
        return s_m <= now_m < e_m
    else:
        # Spans midnight (e.g. 22:00 – 07:00)
        return now_m >= s_m or now_m < e_m


def _already_sent_today(data: dict, key: str) -> bool:
    """Return True if this check already fired today."""
    return data.get("proactive_sent", {}).get(key) == _today()

def _already_sent_this_week(data: dict, key: str) -> bool:
    """Return True if this check already fired this week (Mon–Sun)."""
    sent = data.get("proactive_sent", {}).get(key, "")
    return sent >= _this_week_start()

def _mark_sent(data: dict, key: str) -> None:
    data.setdefault("proactive_sent", {})[key] = _today()

def _habit_streak(habit_log: list, habit_id: str) -> int:
    """Count consecutive days (ending yesterday) a habit was logged."""
    today = _now().date()
    streak = 0
    for i in range(1, 60):
        day = (today - datetime.timedelta(days=i)).isoformat()
        if any(e.get("habit") == habit_id and e.get("date") == day for e in habit_log):
            streak += 1
        else:
            break
    return streak

def _avg(values: list) -> float:
    return sum(values) / len(values) if values else 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# DAILY CHECKS (1–5)
# ═══════════════════════════════════════════════════════════════════════════════

def _check_habit_streak_risk(data: dict, ps: dict) -> str | None:
    """Check 1 — Habit streak at risk: high streak, not yet logged today."""
    if not ps.get("habit_streak_risk", True):
        return None
    if _already_sent_today(data, "habit_streak_risk"):
        return None

    today = _today()
    habit_log = data.get("habit_log", [])
    logged_today = {e.get("habit") for e in habit_log if e.get("date") == today}

    at_risk = []
    for habit_id in HABITS:
        if habit_id in logged_today:
            continue
        streak = _habit_streak(habit_log, habit_id)
        if streak >= 3:
            at_risk.append((habit_id, streak))

    if not at_risk:
        return None

    lines = []
    for habit_id, streak in sorted(at_risk, key=lambda x: -x[1]):
        lines.append(f"  • {_label(habit_id)}: {streak}-day streak")

    return (
        f"⚠️ <b>Streak at risk</b>\n"
        f"These habits haven't been logged yet today:\n"
        + "\n".join(lines)
    )


def _check_overdue_todos(data: dict, ps: dict) -> str | None:
    """Check 2 — Overdue todos (due date in the past, not done)."""
    if not ps.get("overdue_todos", True):
        return None
    if _already_sent_today(data, "overdue_todos"):
        return None

    today = _today()
    # Pull from local cache if no Google auth
    todos = data.get("todos", [])
    overdue = [
        t for t in todos
        if not t.get("done")
        and t.get("due")
        and str(t.get("due", ""))[:10] < today
    ]

    if not overdue:
        return None

    high = [t for t in overdue if t.get("priority") == "high"]
    if not high and len(overdue) < 2:
        return None  # Only nag if high-priority or multiple overdue

    lines = [f"  • {t.get('text', '')}" for t in overdue[:5]]
    suffix = f" (and {len(overdue)-5} more)" if len(overdue) > 5 else ""
    return (
        f"🔴 <b>{len(overdue)} overdue todo{'s' if len(overdue)>1 else ''}</b>{suffix}\n"
        + "\n".join(lines)
        + "\n\nWant to clear any of these?"
    )


def _check_priority_todos(data: dict, ps: dict) -> str | None:
    """Check 3 — Surface high-priority todos due this week."""
    if not ps.get("priority_todos", True):
        return None
    if _already_sent_today(data, "priority_todos"):
        return None

    today = _today()
    week_end = (datetime.date.fromisoformat(today) + datetime.timedelta(days=7)).isoformat()
    todos = data.get("todos", [])

    high_due = [
        t for t in todos
        if not t.get("done")
        and t.get("priority") == "high"
        and t.get("due")
        and today <= str(t.get("due", ""))[:10] <= week_end
    ]
    total_open = sum(1 for t in todos if not t.get("done"))

    if not high_due or total_open < 5:
        return None  # Only useful context when list is substantial

    lines = [f"  • {t.get('text', '')} — due {t.get('due', '')[:10]}" for t in high_due[:5]]
    return (
        f"📌 <b>{total_open} todos open</b> — {len(high_due)} high-priority due this week:\n"
        + "\n".join(lines)
    )


async def _check_back_to_back(data: dict, ps: dict) -> str | None:
    """Check 4 — Back-to-back meetings with no break tomorrow."""
    if not ps.get("back_to_back_meetings", True):
        return None
    if _already_sent_today(data, "back_to_back_meetings"):
        return None

    try:
        from core.google_auth import get_creds
        from adapters.google_calendar import get_events_range, get_event_start_dt, get_event_end_dt
        import googleapiclient.discovery as _disc

        creds = get_creds()
        if not creds:
            return None
        svc = _disc.build("calendar", "v3", credentials=creds, cache_discovery=False)

        tz = ZoneInfo(TIMEZONE)
        tomorrow = _now().date() + datetime.timedelta(days=1)
        start = datetime.datetime.combine(tomorrow, datetime.time(0, 0), tzinfo=tz)
        end   = datetime.datetime.combine(tomorrow, datetime.time(23, 59), tzinfo=tz)
        events = get_events_range(svc, start, end)

        if len(events) < 3:
            return None

        # Sort by start time
        timed = []
        for e in events:
            s = get_event_start_dt(e, tz)
            en = get_event_end_dt(e, tz)
            if s and en:
                timed.append((s, en, e.get("summary", "Event")))
        timed.sort(key=lambda x: x[0])

        # Find back-to-back: gap < 15 minutes between events
        back_to_back_count = 0
        for i in range(len(timed) - 1):
            gap = (timed[i+1][0] - timed[i][1]).total_seconds() / 60
            if gap < 15:
                back_to_back_count += 1

        if back_to_back_count < 2:
            return None

        start_t = timed[0][0].strftime("%-I:%M %p")
        end_t   = timed[-1][1].strftime("%-I:%M %p")
        return (
            f"📅 <b>Busy day tomorrow</b>\n"
            f"{len(timed)} events from {start_t} to {end_t} with little breathing room.\n"
            f"Consider blocking a break."
        )
    except Exception as e:
        logger.debug(f"back_to_back check failed: {e}")
        return None


def _check_reminder_overload(data: dict, ps: dict) -> str | None:
    """Check 5 — Too many reminders due today."""
    if not ps.get("reminder_overload", True):
        return None
    if _already_sent_today(data, "reminder_overload"):
        return None

    today = _today()
    reminders = data.get("reminders", [])
    due_today = [
        r for r in reminders
        if not r.get("done")
        and str(r.get("time", ""))[:10] == today
    ]

    if len(due_today) < 4:
        return None

    return (
        f"⏰ <b>{len(due_today)} reminders due today</b>\n"
        f"Want to review and snooze any before your day starts?"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# PATTERN RECOGNITION (6–14)
# ═══════════════════════════════════════════════════════════════════════════════

def _check_sleep_mood_correlation(data: dict, ps: dict) -> str | None:
    """Check 6 — When sleep <7hrs, mood next day is lower. Surface if pattern holds."""
    if not ps.get("sleep_mood_correlation", True):
        return None
    if _already_sent_this_week(data, "sleep_mood_correlation"):
        return None

    sleep_log = data.get("sleep_log", [])
    mood_log  = data.get("mood_log", [])
    if len(sleep_log) < 7 or len(mood_log) < 7:
        return None

    # Build date → values maps
    sleep_by_date = {e["date"]: e["hours"] for e in sleep_log if "date" in e and "hours" in e}
    mood_by_date  = {e["date"]: e["mood"]  for e in mood_log  if "date" in e and "mood"  in e}

    low_sleep_moods, good_sleep_moods = [], []
    short_nights_this_week = 0
    week_start = _this_week_start()

    for date, hrs in sleep_by_date.items():
        # Next day mood
        try:
            next_day = (datetime.date.fromisoformat(date) + datetime.timedelta(days=1)).isoformat()
        except ValueError:
            continue
        if next_day in mood_by_date:
            if hrs < 7:
                low_sleep_moods.append(mood_by_date[next_day])
            else:
                good_sleep_moods.append(mood_by_date[next_day])
        if hrs < 7 and date >= week_start:
            short_nights_this_week += 1

    if len(low_sleep_moods) < 3 or not good_sleep_moods:
        return None

    avg_low  = _avg(low_sleep_moods)
    avg_good = _avg(good_sleep_moods)

    if avg_good - avg_low < 1.5:
        return None  # Difference not meaningful

    msg = (
        f"💤 <b>Sleep → mood pattern</b>\n"
        f"When you sleep under 7 hours, your mood the next day averages "
        f"{avg_low:.1f}/10 vs {avg_good:.1f}/10 on good nights."
    )
    if short_nights_this_week >= 2:
        msg += f"\n\n{short_nights_this_week} short nights so far this week."
    return msg


def _check_sleep_declining(data: dict, ps: dict) -> str | None:
    """Check 7 — Sleep average this week lower than last week."""
    if not ps.get("sleep_declining", True):
        return None
    if _already_sent_this_week(data, "sleep_declining"):
        return None

    sleep_log = data.get("sleep_log", [])
    today = _now().date()
    week_start  = today - datetime.timedelta(days=today.weekday())
    lweek_start = week_start - datetime.timedelta(days=7)

    this_week  = [e["hours"] for e in sleep_log
                  if "hours" in e and "date" in e
                  and e["date"] >= week_start.isoformat()]
    last_week  = [e["hours"] for e in sleep_log
                  if "hours" in e and "date" in e
                  and lweek_start.isoformat() <= e["date"] < week_start.isoformat()]

    if len(this_week) < 3 or len(last_week) < 3:
        return None

    avg_this = _avg(this_week)
    avg_last = _avg(last_week)

    if avg_last - avg_this < 0.75:
        return None

    return (
        f"😴 <b>Sleep declining</b>\n"
        f"Average this week: {avg_this:.1f} hrs — down from {avg_last:.1f} hrs last week."
    )


def _check_workout_frequency(data: dict, ps: dict) -> str | None:
    """Check 8 — Workout frequency down vs. usual."""
    if not ps.get("workout_frequency", True):
        return None
    if _already_sent_this_week(data, "workout_frequency"):
        return None

    habit_log = data.get("habit_log", [])
    workout_id = next((h for h in HABITS if "workout" in h.lower()), None)
    if not workout_id:
        return None

    today = _now().date()
    # Days since last workout
    days_since = 0
    for i in range(1, 30):
        day = (today - datetime.timedelta(days=i)).isoformat()
        if any(e.get("habit") == workout_id and e.get("date") == day for e in habit_log):
            break
        days_since += 1

    if days_since < 4:
        return None

    # Calculate usual weekly frequency (last 4 weeks)
    logs_28d = [
        e for e in habit_log
        if e.get("habit") == workout_id
        and e.get("date", "") >= (today - datetime.timedelta(days=28)).isoformat()
    ]
    usual_per_week = len(logs_28d) / 4

    if usual_per_week < 2:
        return None  # Not frequent enough to matter

    return (
        f"💪 <b>Workout gap</b>\n"
        f"No {_label(workout_id)} logged in {days_since} days. "
        f"You usually average {usual_per_week:.1f} a week."
    )


def _check_expense_spike(data: dict, ps: dict) -> str | None:
    """Check 9 — A category is way above its 4-week average this week."""
    if not ps.get("expense_spike", True):
        return None
    if _already_sent_this_week(data, "expense_spike"):
        return None

    expenses = data.get("expenses", [])
    if not expenses:
        return None

    today = _now().date()
    week_start = today - datetime.timedelta(days=today.weekday())

    # Sum this week by category
    this_week: dict[str, float] = {}
    for e in expenses:
        if e.get("date", "") >= week_start.isoformat():
            cat = e.get("category", "other")
            this_week[cat] = this_week.get(cat, 0) + e.get("amount", 0)

    if not this_week:
        return None

    # 4-week average by category (excluding this week)
    four_weeks_ago = (week_start - datetime.timedelta(days=28)).isoformat()
    hist: dict[str, list] = {}
    for e in expenses:
        if four_weeks_ago <= e.get("date", "") < week_start.isoformat():
            cat = e.get("category", "other")
            hist.setdefault(cat, []).append(e.get("amount", 0))

    spikes = []
    for cat, total in this_week.items():
        hist_vals = hist.get(cat, [])
        if not hist_vals:
            continue
        weekly_avg = sum(hist_vals) / 4  # sum over 4 weeks / 4
        if total > weekly_avg * 2.5 and total > 30:
            spikes.append((cat, total, weekly_avg))

    if not spikes:
        return None

    cat, total, avg = max(spikes, key=lambda x: x[1] / max(x[2], 1))
    from features.expenses import _CAT_LABELS
    label = _CAT_LABELS.get(cat, cat.title())
    return (
        f"💸 <b>Expense spike: {label}</b>\n"
        f"${total:.0f} this week — {total/max(avg,1):.1f}× your usual ${avg:.0f}/week."
    )


def _check_mood_trend_low(data: dict, ps: dict) -> str | None:
    """Check 10 — Mood has been low this week vs. usual."""
    if not ps.get("mood_trend_low", True):
        return None
    if _already_sent_this_week(data, "mood_trend_low"):
        return None

    mood_log = data.get("mood_log", [])
    today = _now().date()
    week_start = (today - datetime.timedelta(days=today.weekday())).isoformat()

    this_week  = [e["mood"] for e in mood_log if e.get("date", "") >= week_start]
    all_recent = [e["mood"] for e in mood_log
                  if e.get("date", "") >= (today - datetime.timedelta(days=30)).isoformat()]

    if len(this_week) < 3 or len(all_recent) < 7:
        return None

    avg_week   = _avg(this_week)
    avg_recent = _avg(all_recent)

    if avg_recent - avg_week < 1.5:
        return None

    return (
        f"😔 <b>Mood trend</b>\n"
        f"Your mood has averaged {avg_week:.1f}/10 this week — "
        f"lower than your usual {avg_recent:.1f}/10. Anything going on?"
    )


def _check_todo_bloat(data: dict, ps: dict) -> str | None:
    """Check 11 — Todo list has been large for multiple weeks."""
    if not ps.get("todo_bloat", True):
        return None
    if _already_sent_this_week(data, "todo_bloat"):
        return None

    todos = data.get("todos", [])
    open_count = sum(1 for t in todos if not t.get("done"))

    if open_count < 15:
        return None

    # Check if it was also large last week (approximation: items older than 7 days still open)
    cutoff = (_now().date() - datetime.timedelta(days=7)).isoformat()
    old_open = sum(
        1 for t in todos
        if not t.get("done") and str(t.get("added", ""))[:10] < cutoff
    )

    if old_open < 10:
        return None

    return (
        f"📋 <b>Todo overload</b>\n"
        f"You have {open_count} open todos, {old_open} of which have been sitting "
        f"for over a week. Want to do a quick priority review and clear the stale ones?"
    )


def _check_recurring_todo_stuck(data: dict, ps: dict) -> str | None:
    """Check 12 — A specific todo has been open for 3+ weeks without progress."""
    if not ps.get("recurring_todo_stuck", True):
        return None
    if _already_sent_this_week(data, "recurring_todo_stuck"):
        return None

    todos = data.get("todos", [])
    cutoff = (_now().date() - datetime.timedelta(days=21)).isoformat()

    stuck = [
        t for t in todos
        if not t.get("done")
        and t.get("added")
        and str(t.get("added", ""))[:10] <= cutoff
        and t.get("priority") in ("high", "normal")
    ]

    if not stuck:
        return None

    # Show up to 3 most stuck items
    stuck_sorted = sorted(stuck, key=lambda t: str(t.get("added", "")))[:3]
    lines = [f"  • {t.get('text', '')}" for t in stuck_sorted]
    return (
        f"🔁 <b>Stuck todos</b>\n"
        f"{'These tasks have' if len(stuck_sorted)>1 else 'This task has'} "
        f"been on your list for 3+ weeks:\n"
        + "\n".join(lines)
        + "\n\nStill relevant, or time to drop them?"
    )


def _check_mood_habit_correlation(data: dict, ps: dict) -> str | None:
    """Check 13 — Mood is meaningfully higher on workout days."""
    if not ps.get("mood_habit_correlation", True):
        return None
    if _already_sent_this_week(data, "mood_habit_correlation"):
        return None

    habit_log = data.get("habit_log", [])
    mood_log  = data.get("mood_log", [])
    workout_id = next((h for h in HABITS if "workout" in h.lower()), None)

    if not workout_id or len(mood_log) < 10:
        return None

    workout_dates = {e["date"] for e in habit_log if e.get("habit") == workout_id}
    workout_moods, rest_moods = [], []

    for e in mood_log:
        d = e.get("date", "")
        m = e.get("mood")
        if m is None:
            continue
        if d in workout_dates:
            workout_moods.append(m)
        else:
            rest_moods.append(m)

    if len(workout_moods) < 5 or len(rest_moods) < 5:
        return None

    avg_workout = _avg(workout_moods)
    avg_rest    = _avg(rest_moods)

    if avg_workout - avg_rest < 1.2:
        return None

    return (
        f"📊 <b>Pattern spotted</b>\n"
        f"Your mood averages {avg_workout:.1f}/10 on days you log a "
        f"{_label(workout_id)}, vs {avg_rest:.1f}/10 on other days. "
        f"That's a pattern worth leaning into."
    )


def _check_expense_pacing(data: dict, ps: dict) -> str | None:
    """Check 14 — Monthly expense pacing: ahead of last month's pace."""
    if not ps.get("expense_pacing", True):
        return None
    if _already_sent_this_week(data, "expense_pacing"):
        return None

    expenses = data.get("expenses", [])
    if not expenses:
        return None

    today = _now().date()
    this_month  = today.strftime("%Y-%m")
    last_month  = (today.replace(day=1) - datetime.timedelta(days=1)).strftime("%Y-%m")
    day_of_month = today.day

    this_total = sum(e.get("amount", 0) for e in expenses if e.get("date", "").startswith(this_month))
    last_total = sum(e.get("amount", 0) for e in expenses if e.get("date", "").startswith(last_month))

    if last_total < 50 or this_total < 20:
        return None

    # Days in last month
    last_month_days = (today.replace(day=1) - datetime.timedelta(days=1)).day
    last_daily_avg = last_total / last_month_days
    expected_this = last_daily_avg * day_of_month

    if this_total < expected_this * 1.4:
        return None

    pct = int((this_total / max(expected_this, 1) - 1) * 100)
    return (
        f"📈 <b>Expense pacing</b>\n"
        f"Day {day_of_month} of the month and you've spent ${this_total:.0f} — "
        f"{pct}% ahead of where you were last month at this point."
    )


# ═══════════════════════════════════════════════════════════════════════════════
# CALENDAR INTELLIGENCE (15–19)
# ═══════════════════════════════════════════════════════════════════════════════

async def _check_meeting_prep(data: dict, ps: dict) -> str | None:
    """Check 15 — Meeting tomorrow with someone in contacts: surface last note."""
    if not ps.get("meeting_prep", True):
        return None
    if _already_sent_today(data, "meeting_prep"):
        return None

    try:
        from core.google_auth import get_creds
        from adapters.google_calendar import get_events_range, get_event_start_dt
        import googleapiclient.discovery as _disc
        import json as _json, os as _os
        from core.config import CONTACTS_FILE

        creds = get_creds()
        if not creds:
            return None
        svc = _disc.build("calendar", "v3", credentials=creds, cache_discovery=False)

        tz = ZoneInfo(TIMEZONE)
        tomorrow = _now().date() + datetime.timedelta(days=1)
        start = datetime.datetime.combine(tomorrow, datetime.time(0, 0), tzinfo=tz)
        end   = datetime.datetime.combine(tomorrow, datetime.time(23, 59), tzinfo=tz)
        events = get_events_range(svc, start, end)

        if not events:
            return None

        # Load contacts
        contacts: dict = {}
        if _os.path.exists(CONTACTS_FILE):
            try:
                with open(CONTACTS_FILE) as f:
                    contacts = _json.load(f)
            except Exception:
                pass

        if not contacts:
            return None

        # Check if any contact name appears in event summaries
        matched = []
        for event in events:
            title = event.get("summary", "").lower()
            for name, facts in contacts.items():
                if name.lower() in title and facts:
                    last_fact = facts[-1] if isinstance(facts, list) else str(facts)
                    matched.append((event.get("summary", "Event"), name, last_fact))
                    break

        if not matched:
            return None

        lines = []
        for ev_title, name, last_fact in matched[:3]:
            lines.append(f"  • <b>{ev_title}</b> — last note about {name}: <i>{last_fact}</i>")

        return (
            f"🗓️ <b>Meeting prep for tomorrow</b>\n"
            + "\n".join(lines)
        )
    except Exception as e:
        logger.debug(f"meeting_prep check failed: {e}")
        return None


async def _check_calendar_gap_workout(data: dict, ps: dict) -> str | None:
    """Check 16 — Open 2hr+ block in next 3 days: suggest scheduling workout."""
    if not ps.get("calendar_gap_workout", True):
        return None
    if _already_sent_today(data, "calendar_gap_workout"):
        return None

    workout_id = next((h for h in HABITS if "workout" in h.lower()), None)
    if not workout_id:
        return None

    # Check if already worked out today or yesterday
    today = _today()
    yesterday = (_now().date() - datetime.timedelta(days=1)).isoformat()
    habit_log = data.get("habit_log", [])
    recent_workout = any(
        e.get("habit") == workout_id and e.get("date") in (today, yesterday)
        for e in habit_log
    )
    if recent_workout:
        return None

    try:
        from core.google_auth import get_creds
        from adapters.google_calendar import get_events_range, get_event_start_dt, get_event_end_dt
        import googleapiclient.discovery as _disc

        creds = get_creds()
        if not creds:
            return None
        svc = _disc.build("calendar", "v3", credentials=creds, cache_discovery=False)

        tz = ZoneInfo(TIMEZONE)
        for days_ahead in range(1, 4):
            check_date = _now().date() + datetime.timedelta(days=days_ahead)
            start = datetime.datetime.combine(check_date, datetime.time(8, 0), tzinfo=tz)
            end   = datetime.datetime.combine(check_date, datetime.time(21, 0), tzinfo=tz)
            events = get_events_range(svc, start, end)

            # Build busy blocks
            busy = []
            for e in events:
                s = get_event_start_dt(e, tz)
                en = get_event_end_dt(e, tz)
                if s and en:
                    busy.append((s, en))
            busy.sort()

            # Find gaps >= 2 hours
            prev_end = start
            for ev_start, ev_end in busy:
                gap = (ev_start - prev_end).total_seconds() / 3600
                if gap >= 2:
                    day_label = "tomorrow" if days_ahead == 1 else check_date.strftime("%A")
                    gap_start = prev_end.strftime("%-I:%M %p")
                    gap_end   = ev_start.strftime("%-I:%M %p")
                    return (
                        f"💪 <b>Open block {day_label}</b>\n"
                        f"{gap_start}–{gap_end} is free. "
                        f"Want to schedule a {_label(workout_id)}?"
                    )
                prev_end = max(prev_end, ev_end)

            # Check gap after last event
            if busy:
                gap = (end - busy[-1][1]).total_seconds() / 3600
                if gap >= 2:
                    day_label = "tomorrow" if days_ahead == 1 else check_date.strftime("%A")
                    return (
                        f"💪 <b>Open block {day_label}</b>\n"
                        f"{busy[-1][1].strftime('%-I:%M %p')} onward is free. "
                        f"Good time for a {_label(workout_id)}?"
                    )
    except Exception as e:
        logger.debug(f"calendar_gap_workout check failed: {e}")
    return None


async def _check_travel_time_missing(data: dict, ps: dict) -> str | None:
    """Check 17 — Upcoming event with no travel buffer before it."""
    if not ps.get("travel_time_missing", True):
        return None
    if _already_sent_today(data, "travel_time_missing"):
        return None

    try:
        from core.google_auth import get_creds
        from adapters.google_calendar import (
            get_events_range, get_event_start_dt, get_event_end_dt,
            extract_event_location, is_travel_event,
        )
        from core.config import HOME_CITY_KEYWORDS
        import googleapiclient.discovery as _disc

        creds = get_creds()
        if not creds:
            return None
        svc = _disc.build("calendar", "v3", credentials=creds, cache_discovery=False)

        tz = ZoneInfo(TIMEZONE)
        now = _now()
        end = now + datetime.timedelta(days=3)
        events = get_events_range(svc, now, end)

        flagged = []
        for event in events:
            location = extract_event_location(event)
            if not location:
                continue
            # Skip if location looks like a home/online location
            loc_lower = location.lower()
            if any(kw in loc_lower for kw in HOME_CITY_KEYWORDS + ["zoom", "teams", "meet", "online", "remote"]):
                continue
            ev_start = get_event_start_dt(event, tz)
            if not ev_start or ev_start < now:
                continue
            # Check if the 30 min before is free
            buffer_start = ev_start - datetime.timedelta(minutes=30)
            nearby = get_events_range(svc, buffer_start, ev_start)
            if nearby:
                continue  # Something already there
            hours_away = (ev_start - now).total_seconds() / 3600
            if hours_away < 48:
                flagged.append((event.get("summary", "Event"), ev_start, location))

        if not flagged:
            return None

        title, start, loc = flagged[0]
        day_str = "tomorrow" if (start.date() - now.date()).days == 1 else start.strftime("%A")
        return (
            f"🚗 <b>Travel time not blocked</b>\n"
            f"<b>{title}</b> is {day_str} at {start.strftime('%-I:%M %p')} "
            f"at {loc}. No travel buffer before it."
        )
    except Exception as e:
        logger.debug(f"travel_time check failed: {e}")
        return None


async def _check_sleep_important_event(data: dict, ps: dict) -> str | None:
    """Check 18 — Short sleep recent nights + important event tomorrow."""
    if not ps.get("sleep_important_event", True):
        return None
    if _already_sent_today(data, "sleep_important_event"):
        return None

    sleep_log = data.get("sleep_log", [])
    today = _now().date()
    recent_nights = []
    for i in range(1, 4):
        day = (today - datetime.timedelta(days=i)).isoformat()
        entry = next((e for e in sleep_log if e.get("date") == day), None)
        if entry:
            recent_nights.append(entry.get("hours", 8))

    if not recent_nights or _avg(recent_nights) >= 6.5:
        return None

    short_count = sum(1 for h in recent_nights if h < 6.5)
    if short_count < 2:
        return None

    try:
        from core.google_auth import get_creds
        from adapters.google_calendar import (
            get_events_range, get_event_start_dt, is_significant_event,
        )
        import googleapiclient.discovery as _disc

        creds = get_creds()
        if not creds:
            return None
        svc = _disc.build("calendar", "v3", credentials=creds, cache_discovery=False)

        tz = ZoneInfo(TIMEZONE)
        tomorrow = today + datetime.timedelta(days=1)
        start = datetime.datetime.combine(tomorrow, datetime.time(0, 0), tzinfo=tz)
        end   = datetime.datetime.combine(tomorrow, datetime.time(23, 59), tzinfo=tz)
        events = get_events_range(svc, start, end)

        sig = [e for e in events if is_significant_event(e)]
        if not sig:
            return None

        ev_title = sig[0].get("summary", "an event")
        ev_start = get_event_start_dt(sig[0], tz)
        time_str = ev_start.strftime("%-I:%M %p") if ev_start else ""

        avg_hrs = _avg(recent_nights)
        return (
            f"😴 <b>Sleep heads-up</b>\n"
            f"You've averaged {avg_hrs:.1f} hrs over the last {short_count} nights "
            f"and have <b>{ev_title}</b>{(' at ' + time_str) if time_str else ''} tomorrow. "
            f"Worth getting to bed early tonight."
        )
    except Exception as e:
        logger.debug(f"sleep_important_event check failed: {e}")
        return None


async def _check_empty_calendar(data: dict, ps: dict) -> str | None:
    """Check 19 — Nothing on the calendar this week."""
    if not ps.get("empty_calendar", True):
        return None
    if _already_sent_this_week(data, "empty_calendar"):
        return None

    try:
        from core.google_auth import get_creds
        from adapters.google_calendar import get_weeks_events
        import googleapiclient.discovery as _disc

        creds = get_creds()
        if not creds:
            return None
        svc = _disc.build("calendar", "v3", credentials=creds, cache_discovery=False)
        events = get_weeks_events(svc)

        if events:
            return None

        return (
            f"📭 <b>Empty calendar this week</b>\n"
            f"Nothing scheduled. Intentional, or did something not make it onto the calendar?"
        )
    except Exception as e:
        logger.debug(f"empty_calendar check failed: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# WEEKLY REFLECTIONS (20–25)
# ═══════════════════════════════════════════════════════════════════════════════

async def _check_monday_planning(data: dict, ps: dict) -> str | None:
    """Check 20 — Monday morning planning nudge (only fires on Mondays)."""
    if not ps.get("monday_planning", True):
        return None
    if _now().weekday() != 0:  # 0 = Monday
        return None
    if _already_sent_today(data, "monday_planning"):
        return None

    todos = data.get("todos", [])
    open_todos = [t for t in todos if not t.get("done")]
    high_todos  = [t for t in open_todos if t.get("priority") == "high"]

    meeting_count = 0
    try:
        from core.google_auth import get_creds
        from adapters.google_calendar import get_weeks_events
        import googleapiclient.discovery as _disc
        creds = get_creds()
        if creds:
            svc = _disc.build("calendar", "v3", credentials=creds, cache_discovery=False)
            meeting_count = len(get_weeks_events(svc))
    except Exception:
        pass

    parts = []
    if open_todos:
        parts.append(f"{len(open_todos)} open todos")
    if high_todos:
        parts.append(f"{len(high_todos)} high-priority")
    if meeting_count:
        parts.append(f"{meeting_count} meetings this week")

    if not parts:
        return None

    return (
        f"📅 <b>New week</b>\n"
        f"{', '.join(parts)}. "
        f"Want to do a quick priority review before the week kicks off?"
    )


def _check_weekly_completion(data: dict, ps: dict) -> str | None:
    """Check 21 — Weekly todo completion rate (fires Sunday)."""
    if not ps.get("weekly_completion", True):
        return None
    if _now().weekday() != 6:  # 6 = Sunday
        return None
    if _already_sent_today(data, "weekly_completion"):
        return None

    todos = data.get("todos", [])
    week_start = _this_week_start()
    completed_this_week = sum(
        1 for t in todos
        if t.get("done") and str(t.get("completed_at", ""))[:10] >= week_start
    )
    still_open = sum(1 for t in todos if not t.get("done"))

    if completed_this_week < 3:
        return None

    total_touched = completed_this_week + still_open
    msg = (
        f"✅ <b>Week in review</b>\n"
        f"Completed {completed_this_week}/{total_touched} todos this week."
    )
    if still_open > 5:
        msg += f" {still_open} carried into next week."
    return msg


def _check_habit_best_day(data: dict, ps: dict) -> str | None:
    """Check 22 — Surface the day of week with best habit consistency."""
    if not ps.get("habit_best_day", True):
        return None
    if _already_sent_this_week(data, "habit_best_day"):
        return None

    habit_log = data.get("habit_log", [])
    if len(habit_log) < 28:
        return None

    day_counts: dict[int, int] = {i: 0 for i in range(7)}
    day_totals: dict[int, int] = {i: 0 for i in range(7)}
    seen_dates: set = set()

    for e in habit_log:
        date_str = e.get("date", "")
        try:
            d = datetime.date.fromisoformat(date_str)
            dow = d.weekday()
            day_counts[dow] = day_counts.get(dow, 0) + 1
            if date_str not in seen_dates:
                seen_dates.add(date_str)
                day_totals[dow] = day_totals.get(dow, 0) + 1
        except ValueError:
            continue

    if not any(day_totals.values()):
        return None

    # Average habits per day of week
    avg_by_day = {}
    for dow in range(7):
        if day_totals[dow] >= 3:
            avg_by_day[dow] = day_counts[dow] / day_totals[dow]

    if len(avg_by_day) < 4:
        return None

    best_dow  = max(avg_by_day, key=avg_by_day.get)
    worst_dow = min(avg_by_day, key=avg_by_day.get)
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    best_avg  = avg_by_day[best_dow]
    worst_avg = avg_by_day[worst_dow]

    if best_avg - worst_avg < 1.0:
        return None

    return (
        f"📊 <b>Habit pattern</b>\n"
        f"You're most consistent on {day_names[best_dow]}s "
        f"(avg {best_avg:.1f} habits/day) and least consistent on "
        f"{day_names[worst_dow]}s (avg {worst_avg:.1f}/day)."
    )


def _check_streak_recognition(data: dict, ps: dict) -> str | None:
    """Check 23 — Recognize a personal-best or noteworthy streak."""
    if not ps.get("streak_recognition", True):
        return None
    if _already_sent_this_week(data, "streak_recognition"):
        return None

    habit_log = data.get("habit_log", [])
    best_streaks = []

    for habit_id in HABITS:
        streak = _habit_streak(habit_log, habit_id)
        if streak >= 7:
            best_streaks.append((habit_id, streak))

    if not best_streaks:
        return None

    habit_id, streak = max(best_streaks, key=lambda x: x[1])
    weeks = streak // 7
    label = f"{streak} days" if streak < 14 else f"{weeks} weeks straight"

    return (
        f"🔥 <b>Streak milestone</b>\n"
        f"{_label(habit_id)}: {label}. "
        f"{'Longest streak yet.' if streak >= 21 else 'Keep it going.'}"
    )


def _check_shopping_weekend(data: dict, ps: dict) -> str | None:
    """Check 24 — Shopping list has items + weekend is coming up."""
    if not ps.get("shopping_weekend", True):
        return None
    if _already_sent_today(data, "shopping_weekend"):
        return None

    dow = _now().weekday()
    if dow not in (3, 4):  # Only Thursday (3) or Friday (4)
        return None

    shopping_lists = data.get("shopping_lists", {})
    pending_items = []
    for list_name, items in shopping_lists.items():
        pending = [i for i in items if not i.get("done")]
        if pending:
            pending_items.append((list_name.title(), len(pending)))

    if not pending_items:
        return None

    total = sum(c for _, c in pending_items)
    day_label = "tomorrow" if dow == 4 else "this weekend"
    list_summary = ", ".join(f"{c} {name} items" for name, c in pending_items[:3])

    return (
        f"🛒 <b>Shopping heads-up</b>\n"
        f"{total} items across your lists ({list_summary}). "
        f"Weekend is {day_label} — want me to send the full list?"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN RUNNERS
# ═══════════════════════════════════════════════════════════════════════════════

async def run_daily_checks(ctx: AlfredContext) -> None:
    """Run all daily proactive checks. Called by bot.py scheduled job."""
    data = load_data()

    # Respect the user's DND / quiet-hours window
    if _is_quiet_hours(data):
        logger.debug("Proactive daily checks skipped — quiet hours active.")
        return

    ps = get_proactive_settings(data)

    # Check if vacation mode is active — skip most checks
    vacation_active = ps.get("vacation_active", False)

    checks_to_run = [
        ("habit_streak_risk",     lambda: _check_habit_streak_risk(data, ps)),
        ("overdue_todos",         lambda: _check_overdue_todos(data, ps)),
        ("priority_todos",        lambda: _check_priority_todos(data, ps)),
        ("back_to_back_meetings", lambda: _check_back_to_back(data, ps)),
        ("reminder_overload",     lambda: _check_reminder_overload(data, ps)),
        ("sleep_important_event", lambda: _check_sleep_important_event(data, ps)),
        ("meeting_prep",          lambda: _check_meeting_prep(data, ps)),
        ("calendar_gap_workout",  lambda: _check_calendar_gap_workout(data, ps)),
        ("travel_time_missing",   lambda: _check_travel_time_missing(data, ps)),
        ("shopping_weekend",      lambda: _check_shopping_weekend(data, ps)),
        ("monday_planning",       lambda: _check_monday_planning(data, ps)),
    ]

    for key, check_fn in checks_to_run:
        if vacation_active and key not in ("reminder_overload", "shopping_weekend"):
            continue
        try:
            import asyncio
            if asyncio.iscoroutinefunction(check_fn.__wrapped__ if hasattr(check_fn, '__wrapped__') else check_fn):
                msg = await check_fn()
            else:
                result = check_fn()
                if asyncio.iscoroutine(result):
                    msg = await result
                else:
                    msg = result

            if msg:
                await ctx.reply_html(msg)
                _mark_sent(data, key)
                save_data(data)
        except Exception as e:
            logger.error(f"Proactive check {key} failed: {e}")


async def run_weekly_analysis(ctx: AlfredContext) -> None:
    """Run weekly pattern-recognition checks. Called by bot.py on Sunday/Monday."""
    data = load_data()

    if _is_quiet_hours(data):
        logger.debug("Proactive weekly analysis skipped — quiet hours active.")
        return

    ps = get_proactive_settings(data)

    weekly_checks = [
        ("sleep_mood_correlation", lambda: _check_sleep_mood_correlation(data, ps)),
        ("sleep_declining",        lambda: _check_sleep_declining(data, ps)),
        ("workout_frequency",      lambda: _check_workout_frequency(data, ps)),
        ("expense_spike",          lambda: _check_expense_spike(data, ps)),
        ("mood_trend_low",         lambda: _check_mood_trend_low(data, ps)),
        ("todo_bloat",             lambda: _check_todo_bloat(data, ps)),
        ("recurring_todo_stuck",   lambda: _check_recurring_todo_stuck(data, ps)),
        ("mood_habit_correlation", lambda: _check_mood_habit_correlation(data, ps)),
        ("expense_pacing",         lambda: _check_expense_pacing(data, ps)),
        ("empty_calendar",         lambda: _check_empty_calendar(data, ps)),
        ("weekly_completion",      lambda: _check_weekly_completion(data, ps)),
        ("habit_best_day",         lambda: _check_habit_best_day(data, ps)),
        ("streak_recognition",     lambda: _check_streak_recognition(data, ps)),
    ]

    for key, check_fn in weekly_checks:
        try:
            import asyncio
            result = check_fn()
            msg = await result if asyncio.iscoroutine(result) else result
            if msg:
                await ctx.reply_html(msg)
                _mark_sent(data, key)
                save_data(data)
        except Exception as e:
            logger.error(f"Proactive weekly check {key} failed: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# /PROACTIVE COMMAND — Show and toggle settings
# ═══════════════════════════════════════════════════════════════════════════════

_TOGGLE_LABELS = {
    "habit_streak_risk":      "Habit streak at risk",
    "overdue_todos":          "Overdue todo alerts",
    "priority_todos":         "Priority todos this week",
    "back_to_back_meetings":  "Back-to-back meeting warnings",
    "reminder_overload":      "Reminder overload alerts",
    "sleep_mood_correlation": "Sleep → mood correlation",
    "sleep_declining":        "Sleep average declining",
    "workout_frequency":      "Workout frequency nudge",
    "expense_spike":          "Expense category spike",
    "mood_trend_low":         "Mood trend low",
    "todo_bloat":             "Todo list bloat",
    "recurring_todo_stuck":   "Stuck recurring todos",
    "mood_habit_correlation": "Mood + habit correlation",
    "expense_pacing":         "Monthly expense pacing",
    "meeting_prep":           "Meeting prep (contact notes)",
    "calendar_gap_workout":   "Open block → workout suggestion",
    "travel_time_missing":    "Missing travel buffer",
    "sleep_important_event":  "Low sleep + big event ahead",
    "empty_calendar":         "Empty calendar week",
    "monday_planning":        "Monday planning nudge",
    "weekly_completion":      "Weekly completion rate",
    "habit_best_day":         "Best habit day pattern",
    "streak_recognition":     "Streak milestones",
    "shopping_weekend":       "Weekend shopping reminder",
    "smart_note_resurface":   "Smart note resurface",
    "tomorrow_prep":          "Night-before briefing",
    "travel_alerts":          "Smart travel system",
    "vacation_mode":          "Vacation mode (auto-detect)",
    "pre_meeting_brief":      "30-min pre-meeting brief",
}

_TOGGLE_KEYS_BOOL = list(_TOGGLE_LABELS.keys())

# NL alias map: partial phrases → toggle key
_NL_ALIASES: dict[str, str] = {
    "habit streak":       "habit_streak_risk",
    "overdue":            "overdue_todos",
    "priority todo":      "priority_todos",
    "back to back":       "back_to_back_meetings",
    "reminder overload":  "reminder_overload",
    "sleep mood":         "sleep_mood_correlation",
    "sleep declining":    "sleep_declining",
    "sleep drop":         "sleep_declining",
    "workout":            "workout_frequency",
    "expense spike":      "expense_spike",
    "spending spike":     "expense_spike",
    "mood trend":         "mood_trend_low",
    "mood low":           "mood_trend_low",
    "todo bloat":         "todo_bloat",
    "stuck todo":         "recurring_todo_stuck",
    "mood habit":         "mood_habit_correlation",
    "expense pacing":     "expense_pacing",
    "spending pace":      "expense_pacing",
    "meeting prep":       "meeting_prep",
    "calendar gap":       "calendar_gap_workout",
    "travel time":        "travel_time_missing",
    "travel buffer":      "travel_time_missing",
    "sleep event":        "sleep_important_event",
    "empty calendar":     "empty_calendar",
    "monday":             "monday_planning",
    "weekly completion":  "weekly_completion",
    "best day":           "habit_best_day",
    "streak":             "streak_recognition",
    "shopping":           "shopping_weekend",
    "note resurface":     "smart_note_resurface",
    "tomorrow prep":      "tomorrow_prep",
    "night before":       "tomorrow_prep",
    "travel alert":       "travel_alerts",
    "vacation":           "vacation_mode",
    "pre meeting":        "pre_meeting_brief",
    "before meeting":     "pre_meeting_brief",
}


async def cmd_proactive(ctx: AlfredContext) -> None:
    """Show all proactive toggle settings with current on/off state."""
    data = load_data()
    ps   = get_proactive_settings(data)

    on_icon  = "🟢"
    off_icon = "⚫"

    sections = [
        ("Daily Checks", [
            "habit_streak_risk", "overdue_todos", "priority_todos",
            "back_to_back_meetings", "reminder_overload",
        ]),
        ("Pattern Recognition (Weekly)", [
            "sleep_mood_correlation", "sleep_declining", "workout_frequency",
            "expense_spike", "mood_trend_low", "todo_bloat",
            "recurring_todo_stuck", "mood_habit_correlation", "expense_pacing",
        ]),
        ("Calendar Intelligence", [
            "meeting_prep", "calendar_gap_workout", "travel_time_missing",
            "sleep_important_event", "empty_calendar",
        ]),
        ("Weekly Reflections", [
            "monday_planning", "weekly_completion", "habit_best_day",
            "streak_recognition", "shopping_weekend", "smart_note_resurface",
        ]),
        ("Modules", [
            "tomorrow_prep", "travel_alerts", "vacation_mode", "pre_meeting_brief",
        ]),
    ]

    lines = [f"⚡ <b>Proactive Settings</b>\n"]
    for section_name, keys in sections:
        lines.append(f"\n<b>{section_name}</b>")
        for key in keys:
            icon = on_icon if ps.get(key, True) else off_icon
            label = _TOGGLE_LABELS.get(key, key)
            lines.append(f"  {icon} {label}")

    lines.append(
        "\n\n<i>To toggle: \"turn off [name]\" or \"enable [name]\"\n"
        "Example: \"turn off expense spike\"</i>"
    )

    await ctx.reply_html("\n".join(lines))


async def handle_proactive_toggle(intent: str, entities: dict, ctx: AlfredContext) -> None:
    """Handle NL toggle: 'turn off expense alerts', 'enable meeting prep'."""
    text = (entities.get("text") or entities.get("raw") or "").lower()

    # Determine on/off
    enable = any(w in text for w in ("enable", "turn on", "on", "activate"))
    disable = any(w in text for w in ("disable", "turn off", "off", "deactivate", "pause", "stop"))

    if not enable and not disable:
        await ctx.reply("Say \"turn off [feature]\" or \"enable [feature]\". Use /proactive to see all options.")
        return

    # Find matching key
    matched_key = None
    for alias, key in _NL_ALIASES.items():
        if alias in text:
            matched_key = key
            break

    # Fallback: scan toggle labels directly
    if not matched_key:
        for key, label in _TOGGLE_LABELS.items():
            if label.lower() in text or key.replace("_", " ") in text:
                matched_key = key
                break

    if not matched_key:
        await ctx.reply(
            "Not sure which setting you mean. Use /proactive to see the full list."
        )
        return

    data = load_data()
    ps   = get_proactive_settings(data)
    new_val = enable
    ps[matched_key] = new_val
    save_data(data)

    label = _TOGGLE_LABELS.get(matched_key, matched_key)
    state = "enabled" if new_val else "disabled"
    await ctx.reply(f"{'🟢' if new_val else '⚫'} <b>{label}</b> {state}.", parse_mode="HTML")

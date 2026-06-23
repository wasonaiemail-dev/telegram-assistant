"""
marvin/features/vacation.py
=============================
Vacation mode — Marvin knows when you're away and adjusts accordingly.

WHAT VACATION MODE DOES
────────────────────────
When active:
  • Most daily proactive checks are silenced (streak risk, overdue todos, etc.)
  • Morning briefing skips habit section and to-do section
  • Night-before briefing (tomorrow_prep) is suppressed
  • Only "keep-on-vacation" items remain active (user-selected habits,
    shopping weekend, reminder overload)
  • A daily "vacation check-in" message can optionally be sent instead
    (just a friendly good-morning with weather at the destination)

On return:
  • Vacation mode auto-deactivates on vacation_end_date
  • Marvin sends a "welcome back" recovery nudge with:
      - How many habits were missed
      - Overdue to-dos that piled up
      - A gentle "ease back in" message rather than a stress dump

ACTIVATION FLOWS
─────────────────
Auto-detect:
  Marvin scans for multi-day travel events (duration ≥2 days).
  If found, it asks: "Looks like you're travelling to {X} from {start} to {end}.
  Want me to turn on vacation mode?"

Manual NL:
  "turn on vacation mode" / "I'm going on vacation"
  "going on vacation until [date]"
  "back from vacation" / "vacation mode off"

Slash command:
  /vacation            — show current status + toggle
  /vacation on [date]  — activate until date
  /vacation off        — deactivate now

HABIT HANDLING
──────────────
User can choose which habits to keep tracking on vacation:
  "keep tracking water on vacation"
  "pause all habits on vacation"
  Stored in settings["proactive"]["vacation_paused_habits"]

PACKING OVERRIDE
─────────────────
  "add [item] to my packing list for [trip type]"
  Stored in userdata["travel_packing_overrides"][trip_type]

PUBLIC
──────
  handle_vacation_intent(intent, entities, ctx)  — NL handler
  cmd_vacation(ctx, args)                        — /vacation command
  check_vacation_auto_detect(ctx)                — daily calendar scan
  check_vacation_auto_resume(ctx)                — daily end-date check
"""

from __future__ import annotations

import asyncio
import datetime
import logging
from zoneinfo import ZoneInfo

from core.marvin_context import MarvinContext
from core.config import TIMEZONE, HABITS, HABIT_LABELS
from core.data import load_data, save_data, get_proactive_settings
from core.intent import VACATION_MODE, PACKING_OVERRIDE

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _today() -> datetime.date:
    return datetime.datetime.now(ZoneInfo(TIMEZONE)).date()


def _parse_date_str(raw: str) -> datetime.date | None:
    """
    Parse a date string like "June 15", "2025-06-15", "June 15th", etc.
    Returns None on failure.
    """
    if not raw:
        return None
    raw = raw.strip().rstrip(".,").lower()
    # ISO format
    try:
        return datetime.date.fromisoformat(raw)
    except ValueError:
        pass
    # Try GPT-returned formats: "june 15", "june 15th", "jun 15"
    import re
    raw = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", raw)  # strip ordinals
    for fmt in ("%B %d %Y", "%b %d %Y", "%B %d", "%b %d"):
        try:
            parsed = datetime.datetime.strptime(raw, fmt)
            # If no year, assume current or next year
            if parsed.year == 1900:
                today = _today()
                parsed = parsed.replace(year=today.year)
                if parsed.date() < today:
                    parsed = parsed.replace(year=today.year + 1)
            return parsed.date()
        except ValueError:
            continue
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# STATUS HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _is_vacation_active(data: dict) -> bool:
    ps = get_proactive_settings(data)
    return bool(ps.get("vacation_active", False))


def _get_vacation_end(data: dict) -> datetime.date | None:
    ps = get_proactive_settings(data)
    raw = ps.get("vacation_end_date", "")
    return _parse_date_str(raw) if raw else None


def _paused_habits(data: dict) -> list[str]:
    ps = get_proactive_settings(data)
    return ps.get("vacation_paused_habits", [])


def _activate_vacation(data: dict, end_date: datetime.date | None = None) -> None:
    ps = get_proactive_settings(data)
    ps["vacation_active"] = True
    ps["vacation_end_date"] = str(end_date) if end_date else ""


def _deactivate_vacation(data: dict) -> None:
    ps = get_proactive_settings(data)
    ps["vacation_active"] = False
    ps["vacation_end_date"] = ""
    ps["vacation_paused_habits"] = []


# ═══════════════════════════════════════════════════════════════════════════════
# WELCOME BACK NUDGE
# ═══════════════════════════════════════════════════════════════════════════════

async def _send_welcome_back(ctx: MarvinContext, data: dict) -> None:
    """
    Send a friendly recovery message after vacation mode deactivates.
    Shows overdue to-dos + missed habits, with a gentle re-entry tone.
    """
    today = _today()
    lines = [
        "🏠 <b>Welcome back!</b>",
        "",
        "Vacation mode is now off. Here's a gentle re-entry summary:",
        "",
    ]

    # Count overdue todos
    overdue: list[str] = []
    for task in data.get("todos", []):
        if task.get("done"):
            continue
        due = task.get("due", "")
        if due and due < str(today):
            overdue.append(task.get("title", "Unknown task"))
    if overdue:
        lines.append(f"📋 <b>{len(overdue)} to-do{'s' if len(overdue) != 1 else ''} waiting:</b>")
        for t in overdue[:5]:
            lines.append(f"  • {t}")
        if len(overdue) > 5:
            lines.append(f"  • …and {len(overdue) - 5} more")
        lines.append("")

    # Paused habits reminder
    paused = _paused_habits(data)
    if paused:
        habit_names = [HABIT_LABELS.get(h, h.replace("_", " ").title()) for h in paused]
        lines.append(f"💪 <b>Habits to restart:</b> {', '.join(habit_names)}")
        lines.append("")

    lines += [
        "Take it easy — no need to catch up on everything at once. 🌿",
        "<i>Use /briefing for your full morning rundown.</i>",
    ]
    await ctx.reply_html("\n".join(lines))


# ═══════════════════════════════════════════════════════════════════════════════
# AUTO-DETECT FROM CALENDAR
# ═══════════════════════════════════════════════════════════════════════════════

async def check_vacation_auto_detect(ctx: MarvinContext) -> None:
    """
    Scan the calendar for multi-day travel events starting in the next 3 days.
    If found and vacation mode is not already active, ask the user if they
    want to activate it.
    """
    data = load_data()
    ps   = get_proactive_settings(data)

    if ps.get("vacation_active", False):
        return   # already on

    sent_key = "vacation_auto_detect"
    sent = data.get("proactive_sent", {})
    if sent.get(sent_key) == str(_today()):
        return   # already asked today

    try:
        from core.google_auth import get_creds
        from googleapiclient.discovery import build
        from adapters.google_calendar import get_events_range, is_all_day_event

        creds = get_creds(data)
        if not creds:
            return

        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        tz    = ZoneInfo(TIMEZONE)
        today = _today()
        start = datetime.datetime.combine(today, datetime.time.min, tzinfo=tz)
        end   = start + datetime.timedelta(days=3)
        events = get_events_range(service, start, end) or []

        from features.travel import _TRAVEL_KEYWORDS, _event_start_date, _detect_destination

        for ev in events:
            text = " ".join([
                ev.get("summary", ""),
                ev.get("description", ""),
                ev.get("location", ""),
            ]).lower()
            if not any(k in text for k in _TRAVEL_KEYWORDS):
                continue

            # Check multi-day (all-day events spanning ≥2 days, or long events)
            ev_start = _event_start_date(ev)
            ev_end_raw = (ev.get("end", {}).get("date") or
                          (ev.get("end", {}).get("dateTime", "") or "")[:10])
            ev_end = datetime.date.fromisoformat(ev_end_raw) if ev_end_raw else ev_start

            if not ev_start or not ev_end:
                continue
            duration_days = (ev_end - ev_start).days if ev_end > ev_start else 1
            if duration_days < 2:
                continue

            # Ask user
            destination = _detect_destination(ev)
            start_str   = ev_start.strftime("%B %-d")
            end_str     = ev_end.strftime("%B %-d")
            await ctx.reply(
                f"✈️ Looks like you're headed to {destination} from {start_str}–{end_str}. "
                f"Want me to turn on vacation mode until {end_str}? "
                f"Reply \"vacation on until {end_str}\" or \"yes vacation\" to activate."
            )

            data.setdefault("proactive_sent", {})[sent_key] = str(_today())
            save_data(data)
            return   # one prompt per day max

    except Exception as exc:
        logger.debug("vacation: auto-detect failed: %s", exc)


async def check_vacation_auto_resume(ctx: MarvinContext) -> None:
    """
    Called daily. If vacation_end_date has passed, deactivate vacation mode
    and send a welcome-back message.
    """
    data = load_data()
    ps   = get_proactive_settings(data)

    if not ps.get("vacation_active", False):
        return

    end_date = _get_vacation_end(data)
    if end_date and _today() >= end_date:
        _deactivate_vacation(data)
        save_data(data)
        await _send_welcome_back(ctx, data)


# ═══════════════════════════════════════════════════════════════════════════════
# INTENT HANDLERS
# ═══════════════════════════════════════════════════════════════════════════════

async def handle_vacation_intent(
    intent: str,
    entities: dict,
    ctx: MarvinContext,
) -> None:
    """
    Handles VACATION_MODE and PACKING_OVERRIDE intents.
    Entities expected:
      VACATION_MODE   : action="on"|"off"|"status", end_date="...", habit="..."
      PACKING_OVERRIDE: item="...", trip_type="..."
    """
    if intent == PACKING_OVERRIDE:
        await _handle_packing_override(entities, ctx)
        return

    action   = (entities.get("action") or "status").lower()
    end_raw  = entities.get("end_date", "")
    habit    = entities.get("habit", "")

    data = load_data()
    ps   = get_proactive_settings(data)

    # ── STATUS ────────────────────────────────────────────────────────────────
    if action == "status" or not action:
        await cmd_vacation(ctx, args=[])
        return

    # ── ACTIVATE ──────────────────────────────────────────────────────────────
    if action in ("on", "activate", "start", "enable"):
        end_date = _parse_date_str(end_raw) if end_raw else None
        _activate_vacation(data, end_date)
        save_data(data)

        end_msg = f" until {end_date.strftime('%B %-d')}" if end_date else ""
        await ctx.reply(
            f"🏖️ Vacation mode is ON{end_msg}. "
            "Most proactive alerts are paused. "
            "Use \"vacation off\" or \"I'm back\" to deactivate. "
            "Want to choose which habits to keep tracking? Say "
            "\"keep tracking [habit] on vacation\"."
        )
        return

    # ── DEACTIVATE ────────────────────────────────────────────────────────────
    if action in ("off", "deactivate", "stop", "disable", "back", "return"):
        if not ps.get("vacation_active", False):
            await ctx.reply("Vacation mode is already off.")
            return
        _deactivate_vacation(data)
        save_data(data)
        await _send_welcome_back(ctx, data)
        return

    # ── KEEP HABIT ────────────────────────────────────────────────────────────
    if action in ("keep", "track"):
        if not habit:
            await ctx.reply("Which habit do you want to keep tracking on vacation?")
            return
        paused = ps.get("vacation_paused_habits", [])
        # "keep" means remove from paused list
        if habit in paused:
            paused.remove(habit)
            ps["vacation_paused_habits"] = paused
            save_data(data)
            label = HABIT_LABELS.get(habit, habit.replace("_", " ").title())
            await ctx.reply(f"✅ {label} will stay active during vacation.")
        else:
            label = HABIT_LABELS.get(habit, habit.replace("_", " ").title())
            await ctx.reply(f"{label} is already active during vacation.")
        return

    # ── PAUSE HABIT ───────────────────────────────────────────────────────────
    if action == "pause":
        if not habit:
            # Pause all habits
            ps["vacation_paused_habits"] = list(HABITS)
            save_data(data)
            await ctx.reply("⏸️ All habits will be paused during vacation.")
        else:
            paused = ps.get("vacation_paused_habits", [])
            if habit not in paused:
                paused.append(habit)
                ps["vacation_paused_habits"] = paused
                save_data(data)
            label = HABIT_LABELS.get(habit, habit.replace("_", " ").title())
            await ctx.reply(f"⏸️ {label} will be paused during vacation.")
        return

    # Fallback
    await cmd_vacation(ctx, args=[])


async def _handle_packing_override(entities: dict, ctx: MarvinContext) -> None:
    """Add a custom item to the packing list for a trip type."""
    item      = (entities.get("item") or "").strip()
    trip_type = (entities.get("trip_type") or "generic").lower().replace(" ", "_")

    if not item:
        await ctx.reply("What item do you want to add to the packing list?")
        return

    data = load_data()
    overrides: dict = data.setdefault("travel_packing_overrides", {})
    trip_list: list = overrides.setdefault(trip_type, [])

    if item in trip_list:
        await ctx.reply(f'"{item}" is already on the {trip_type} packing list.')
    else:
        trip_list.append(item)
        save_data(data)
        await ctx.reply(
            f"✅ Added \"{item}\" to your {trip_type.replace('_', ' ')} packing list. "
            "Marvin will include it in future trip reminders."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# /vacation COMMAND
# ═══════════════════════════════════════════════════════════════════════════════

async def cmd_vacation(ctx: MarvinContext, args: list[str] | None = None) -> None:
    """/vacation — show status or toggle vacation mode."""
    args = args or []
    arg_str = " ".join(args).strip().lower()

    # Parse sub-commands from slash command args
    if arg_str.startswith("on"):
        date_part = arg_str.removeprefix("on").strip()
        entities = {"action": "on", "end_date": date_part}
        await handle_vacation_intent(VACATION_MODE, entities, ctx)
        return
    if arg_str in ("off", "end", "stop", "back"):
        await handle_vacation_intent(VACATION_MODE, {"action": "off"}, ctx)
        return

    # Status display
    data = load_data()
    ps   = get_proactive_settings(data)
    active = ps.get("vacation_active", False)
    end_date = _get_vacation_end(data)
    paused = _paused_habits(data)

    lines = ["🏖️ <b>Vacation Mode</b>", ""]

    if active:
        lines.append("Status: <b>🟢 ON</b>")
        if end_date:
            days_left = (end_date - _today()).days
            lines.append(
                f"Returns: {end_date.strftime('%B %-d')} "
                f"({days_left} day{'s' if days_left != 1 else ''} away)"
            )
        else:
            lines.append("Returns: Not set — say \"vacation off\" or \"I'm back\" when home.")
    else:
        lines.append("Status: <b>⚫ OFF</b>")

    lines.append("")

    if paused:
        labels = [HABIT_LABELS.get(h, h.replace("_", " ").title()) for h in paused]
        lines.append(f"Paused habits: {', '.join(labels)}")
    else:
        if active:
            lines.append("All habits are still tracking (use \"pause [habit] on vacation\" to snooze one).")

    lines += [
        "",
        "<b>Commands</b>",
        "• \"vacation on until June 20\" — activate with end date",
        "• \"vacation off\" / \"I'm back\" — deactivate",
        "• \"pause [habit] on vacation\" — snooze a habit",
        "• \"keep tracking [habit] on vacation\" — keep a habit active",
        "• \"add [item] to packing list\" — customize packing lists",
    ]

    await ctx.reply_html("\n".join(lines))

"""
marvin/features/sleep.py
=========================
Sleep tracking for Marvin.

STORAGE  (userdata.json["sleep_log"])
──────────────────────────────────────
Each entry:
  {
    "hours":   float,
    "quality": int | None,   ← 1–5 scale (optional)
    "date":    "YYYY-MM-DD",
    "note":    str
  }

COMMANDS
─────────
  /sleep           — show recent sleep history (7 days)
  /sleep 7.5       — log 7.5 hours for tonight

NATURAL LANGUAGE
─────────────────
  "slept 7 hours"          → log sleep
  "got 6.5 hours of sleep" → log sleep
  "sleep 8"                → log sleep
  "show my sleep"          → view history
  "how much did I sleep"   → view history

WEEKLY SUMMARY INTEGRATION
───────────────────────────
  get_sleep_weekly_section(data) → str  (called by summary.py)
"""

from __future__ import annotations

import datetime
import logging
from zoneinfo import ZoneInfo

from core.marvin_context import MarvinContext
from core.config import TIMEZONE
from core.data import load_data, save_data

logger = logging.getLogger(__name__)


def _today() -> str:
    return datetime.datetime.now(ZoneInfo(TIMEZONE)).strftime("%Y-%m-%d")


def _quality_emoji(q: int | None) -> str:
    if q is None:
        return ""
    return {1: " 😴", 2: " 😪", 3: " 😐", 4: " 🙂", 5: " 😄"}.get(q, "")


def _sleep_bar(hours: float) -> str:
    """Visual bar showing sleep vs 8-hour target."""
    filled = min(int(hours), 10)
    return "█" * filled + "░" * (8 - filled) if hours < 8 else "█" * 8


# ════════════════════════════════════════════════════════════════════════════
# COMMAND HANDLER
# ════════════════════════════════════════════════════════════════════════════

async def cmd_sleep(ctx: MarvinContext, args: str = "") -> None:
    """
    /sleep           → show recent sleep history
    /sleep 7.5       → log 7.5 hours
    /sleep 7.5 3     → log 7.5 hours, quality 3/5
    """
    data = load_data()
    parts = args.strip().split() if args.strip() else []

    if parts:
        # Parse hours (and optionally quality)
        try:
            hours = float(parts[0])
        except ValueError:
            await ctx.reply("Use `/sleep 7.5` to log hours, or `/sleep` to view history.")
            return

        quality = None
        if len(parts) >= 2:
            try:
                quality = int(parts[1])
                quality = max(1, min(5, quality))
            except ValueError:
                pass

        ents = {"hours": hours, "quality": quality, "note": " ".join(parts[2:]) if len(parts) > 2 else ""}
        await _log_sleep(ctx, data, ents)
    else:
        await _send_sleep_history(ctx, data, days=7)


# ════════════════════════════════════════════════════════════════════════════
# INTENT HANDLER
# ════════════════════════════════════════════════════════════════════════════

async def handle_sleep_intent(intent: str, ents: dict, ctx: MarvinContext) -> None:
    from core.intent import SLEEP_LOG, SLEEP_VIEW

    data = load_data()

    if intent == SLEEP_LOG:
        await _log_sleep(ctx, data, ents)

    elif intent == SLEEP_VIEW:
        days = int(ents.get("days", 7))
        await _send_sleep_history(ctx, data, days=days)


# ════════════════════════════════════════════════════════════════════════════
# INTERNAL — LOG
# ════════════════════════════════════════════════════════════════════════════

async def _log_sleep(ctx: MarvinContext, data: dict, ents: dict) -> None:
    hours = ents.get("hours")
    if not hours:
        await ctx.reply(
            'Tell me how many hours. Try: *"slept 7 hours"* or */sleep 7.5*'
        )
        return

    hours   = round(float(hours), 1)
    quality = ents.get("quality")
    note    = (ents.get("note") or "").strip()
    today   = _today()

    # Overwrite if already logged today
    sleep_log = data.get("sleep_log", [])
    existing  = next((e for e in sleep_log if e["date"] == today), None)
    if existing:
        existing["hours"]   = hours
        existing["quality"] = quality
        existing["note"]    = note
    else:
        sleep_log.append({
            "hours":   hours,
            "quality": quality,
            "date":    today,
            "note":    note,
        })
        data["sleep_log"] = sleep_log

    save_data(data)

    # Build confirmation
    bar        = _sleep_bar(hours)
    q_str      = _quality_emoji(quality)
    note_str   = f" — {note}" if note else ""
    vs_target  = ""
    if hours < 7:
        vs_target = f" (_{7 - hours:.1f} hrs under target_)"
    elif hours >= 8:
        vs_target = " ✓"

    await ctx.reply_markdown(
        f"😴 Logged *{hours} hrs* of sleep{q_str}{note_str}\n"
        f"`{bar}` {vs_target}"
    )


# ════════════════════════════════════════════════════════════════════════════
# INTERNAL — VIEW HISTORY
# ════════════════════════════════════════════════════════════════════════════

async def _send_sleep_history(ctx: MarvinContext, data: dict, days: int = 7) -> None:
    tz     = ZoneInfo(TIMEZONE)
    today  = datetime.datetime.now(tz).date()
    cutoff = today - datetime.timedelta(days=days - 1)

    log = [
        e for e in data.get("sleep_log", [])
        if datetime.date.fromisoformat(e["date"]) >= cutoff
    ]
    log = sorted(log, key=lambda x: x["date"], reverse=True)

    if not log:
        await ctx.reply_markdown(
            f"No sleep logged in the last {days} days.\n"
            f'Try: *"slept 7 hours"*'
        )
        return

    avg_hours = sum(e["hours"] for e in log) / len(log)
    lines = [f"😴 *Sleep — Last {days} Days*  _(avg {avg_hours:.1f} hrs)_\n"]

    for e in log:
        d      = datetime.date.fromisoformat(e["date"])
        label  = "Today" if d == today else d.strftime("%a %b %-d")
        q_str  = _quality_emoji(e.get("quality"))
        note_s = f" — {e['note']}" if e.get("note") else ""
        bar    = _sleep_bar(e["hours"])
        lines.append(f"*{label}:* {e['hours']} hrs {q_str}\n  `{bar}`{note_s}")

    await ctx.reply_markdown("\n".join(lines))


# ════════════════════════════════════════════════════════════════════════════
# WEEKLY SUMMARY INTEGRATION
# ════════════════════════════════════════════════════════════════════════════

def get_sleep_weekly_section(data: dict) -> str:
    """
    Returns a weekly sleep summary for inclusion in the Sunday weekly summary.
    Returns empty string if no sleep logged this week.
    """
    tz     = ZoneInfo(TIMEZONE)
    today  = datetime.datetime.now(tz).date()
    monday = today - datetime.timedelta(days=today.weekday())

    log = [
        e for e in data.get("sleep_log", [])
        if datetime.date.fromisoformat(e["date"]) >= monday
    ]

    if not log:
        return ""

    avg_hours = sum(e["hours"] for e in log) / len(log)
    nights    = len(log)
    low       = min(e["hours"] for e in log)
    high      = max(e["hours"] for e in log)

    emoji  = "😄" if avg_hours >= 8 else ("🙂" if avg_hours >= 7 else ("😪" if avg_hours >= 6 else "😴"))
    lines  = [
        f"😴 <b>Sleep</b> — {nights} nights logged",
        f"  Avg: <b>{avg_hours:.1f} hrs</b> {emoji}   Low: {low} hrs   High: {high} hrs",
    ]

    return "\n".join(lines)

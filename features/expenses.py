"""
alfred/features/expenses.py
============================
Expense tracking for Alfred.

STORAGE  (userdata.json["expenses"])
─────────────────────────────────────
Each entry:
  {
    "id":       int,
    "amount":   float,
    "category": str,   ← groceries | dining | transport | health | entertainment |
                          shopping | household | subscriptions | other
    "note":     str,
    "date":     "YYYY-MM-DD"
  }

COMMANDS
─────────
  /expenses           — view recent expense summary (30 days)
  /expenses today     — today's expenses
  /expenses week      — this week's expenses

NATURAL LANGUAGE
─────────────────
  "$45 groceries"                  → add expense
  "spent $12 on coffee"            → add expense
  "show my expenses"               → view summary
  "how much did I spend this week" → view summary

BRIEFING INTEGRATION
─────────────────────
  get_expense_briefing_section(data) → str  (called by briefing.py)

WEEKLY SUMMARY INTEGRATION
───────────────────────────
  get_expense_weekly_section(data) → str   (called by summary.py)
"""

from __future__ import annotations

import datetime
import logging
from zoneinfo import ZoneInfo

from core.alfred_context import AlfredContext
from core.config import TIMEZONE
from core.data import load_data, save_data

logger = logging.getLogger(__name__)

EXPENSE_CATEGORIES = [
    "groceries", "dining", "transport", "health",
    "entertainment", "shopping", "household", "subscriptions", "other",
]

# ── category display names ──────────────────────────────────────────────────
_CAT_LABELS = {
    "groceries":     "🛒 Groceries",
    "dining":        "🍽️ Dining",
    "transport":     "🚗 Transport",
    "health":        "💊 Health",
    "entertainment": "🎬 Entertainment",
    "shopping":      "🛍️ Shopping",
    "household":     "🏠 Household",
    "subscriptions": "📱 Subscriptions",
    "other":         "📌 Other",
}


def _today() -> str:
    return datetime.datetime.now(ZoneInfo(TIMEZONE)).strftime("%Y-%m-%d")


def _next_id(expenses: list) -> int:
    if not expenses:
        return 1
    return max((e.get("id", 0) for e in expenses), default=0) + 1


def _parse_category(raw: str) -> str:
    """Normalize a raw category string to a known key, defaulting to 'other'."""
    raw = raw.lower().strip()
    # direct match
    if raw in EXPENSE_CATEGORIES:
        return raw
    # fuzzy matches
    aliases = {
        "grocery": "groceries",
        "restaurant": "dining",
        "food": "dining",
        "coffee": "dining",
        "uber": "transport",
        "lyft": "transport",
        "gas": "transport",
        "gym": "health",
        "pharmacy": "health",
        "sub": "subscriptions",
        "subscription": "subscriptions",
    }
    return aliases.get(raw, "other")


def _label(cat: str) -> str:
    return _CAT_LABELS.get(cat, f"📌 {cat.title()}")


# ════════════════════════════════════════════════════════════════════════════
# COMMAND HANDLER  (slash command entry point for both Telegram + Discord)
# ════════════════════════════════════════════════════════════════════════════

async def cmd_expenses(ctx: AlfredContext, period: str = "month") -> None:
    """
    /expenses [today|week|month]
    Shows expense summary for the requested period.
    """
    data = load_data()
    await _send_expense_summary(ctx, data, period)


# ════════════════════════════════════════════════════════════════════════════
# INTENT HANDLER  (NL dispatch entry point)
# ════════════════════════════════════════════════════════════════════════════

async def handle_expense_intent(intent: str, ents: dict, ctx: AlfredContext) -> None:
    from core.intent import EXPENSE_ADD, EXPENSE_VIEW, EXPENSE_DELETE

    data = load_data()

    if intent == EXPENSE_ADD:
        await _add_expense(ctx, data, ents)

    elif intent == EXPENSE_VIEW:
        days = int(ents.get("days", 30))
        period = "today" if days <= 1 else ("week" if days <= 7 else "month")
        await _send_expense_summary(ctx, data, period)

    elif intent == EXPENSE_DELETE:
        await _delete_expense(ctx, data, ents)


# ════════════════════════════════════════════════════════════════════════════
# INTERNAL — ADD
# ════════════════════════════════════════════════════════════════════════════

async def _add_expense(ctx: AlfredContext, data: dict, ents: dict) -> None:
    amount = ents.get("amount")
    if not amount:
        await ctx.reply(
            "I need an amount. Try: *$45 groceries* or *spent $12 on coffee*"
        )
        return

    raw_cat  = ents.get("category", "other")
    category = _parse_category(str(raw_cat))
    note     = ents.get("note", "").strip()
    today    = _today()

    expense = {
        "id":       _next_id(data["expenses"]),
        "amount":   round(float(amount), 2),
        "category": category,
        "note":     note,
        "date":     today,
    }
    data["expenses"].append(expense)
    save_data(data)

    note_part = f" — {note}" if note else ""
    await ctx.reply_markdown(
        f"💰 Logged *${expense['amount']:.2f}* under *{_label(category)}*{note_part}."
    )


# ════════════════════════════════════════════════════════════════════════════
# INTERNAL — VIEW / SUMMARY
# ════════════════════════════════════════════════════════════════════════════

async def _send_expense_summary(ctx: AlfredContext, data: dict, period: str) -> None:
    tz      = ZoneInfo(TIMEZONE)
    now     = datetime.datetime.now(tz)
    today   = now.date()

    if period == "today":
        cutoff = today
        label  = "Today"
    elif period == "week":
        cutoff = today - datetime.timedelta(days=today.weekday())  # Monday
        label  = "This Week"
    else:  # month
        cutoff = today.replace(day=1)
        label  = "This Month"

    expenses = [
        e for e in data.get("expenses", [])
        if datetime.date.fromisoformat(e["date"]) >= cutoff
    ]

    if not expenses:
        await ctx.reply_markdown(f"No expenses logged {label.lower()} yet.")
        return

    # Totals by category
    totals: dict[str, float] = {}
    for e in expenses:
        totals[e["category"]] = totals.get(e["category"], 0.0) + e["amount"]

    grand_total = sum(totals.values())

    lines = [f"💰 *Expenses — {label}*\n"]
    for cat in EXPENSE_CATEGORIES:
        if cat in totals:
            lines.append(f"{_label(cat)}: *${totals[cat]:.2f}*")

    lines.append(f"\n*Total: ${grand_total:.2f}*")

    # Show last 5 individual entries if "today" or few entries
    if period == "today" or len(expenses) <= 10:
        lines.append("\n_Recent entries:_")
        for e in sorted(expenses, key=lambda x: x["date"], reverse=True)[:10]:
            note_str = f" — {e['note']}" if e.get("note") else ""
            lines.append(f"  • ${e['amount']:.2f} {_label(e['category'])}{note_str}")

    await ctx.reply_markdown("\n".join(lines))


# ════════════════════════════════════════════════════════════════════════════
# INTERNAL — DELETE
# ════════════════════════════════════════════════════════════════════════════

async def _delete_expense(ctx: AlfredContext, data: dict, ents: dict) -> None:
    # Show recent expenses and ask user to specify by number
    expenses = data.get("expenses", [])
    recent   = sorted(expenses, key=lambda x: x["date"], reverse=True)[:5]
    if not recent:
        await ctx.reply("No expenses logged yet.")
        return

    lines = ["Which expense would you like to delete? Reply with the number.\n"]
    for i, e in enumerate(recent, 1):
        note_str = f" — {e['note']}" if e.get("note") else ""
        lines.append(f"{i}. ${e['amount']:.2f} {_label(e['category'])} ({e['date']}){note_str}")
    await ctx.reply_markdown("\n".join(lines))


# ════════════════════════════════════════════════════════════════════════════
# BRIEFING INTEGRATION
# ════════════════════════════════════════════════════════════════════════════

def get_expense_briefing_section(data: dict) -> str:
    """
    Returns a compact expense summary for today to include in the morning briefing.
    Returns empty string if no expenses today.
    """
    today    = datetime.datetime.now(ZoneInfo(TIMEZONE)).date()
    today_s  = today.isoformat()
    expenses = [e for e in data.get("expenses", []) if e["date"] == today_s]

    if not expenses:
        return ""

    total = sum(e["amount"] for e in expenses)
    lines = [f"💰 <b>Today's Expenses</b> — ${total:.2f}"]
    totals: dict[str, float] = {}
    for e in expenses:
        totals[e["category"]] = totals.get(e["category"], 0.0) + e["amount"]
    for cat, amt in totals.items():
        lines.append(f"  • {_label(cat)}: ${amt:.2f}")
    return "\n".join(lines)


# ════════════════════════════════════════════════════════════════════════════
# WEEKLY SUMMARY INTEGRATION
# ════════════════════════════════════════════════════════════════════════════

def get_expense_weekly_section(data: dict) -> str:
    """
    Returns a weekly expense summary for inclusion in the Sunday weekly summary.
    Returns empty string if no expenses this week.
    """
    tz    = ZoneInfo(TIMEZONE)
    today = datetime.datetime.now(tz).date()
    # Go back to the most recent Monday
    monday = today - datetime.timedelta(days=today.weekday())

    expenses = [
        e for e in data.get("expenses", [])
        if datetime.date.fromisoformat(e["date"]) >= monday
    ]

    if not expenses:
        return ""

    totals: dict[str, float] = {}
    for e in expenses:
        totals[e["category"]] = totals.get(e["category"], 0.0) + e["amount"]
    grand_total = sum(totals.values())

    lines = [f"💰 <b>Expenses This Week</b> — ${grand_total:.2f}"]
    for cat in EXPENSE_CATEGORIES:
        if cat in totals:
            lines.append(f"  • {_label(cat)}: ${totals[cat]:.2f}")

    return "\n".join(lines)

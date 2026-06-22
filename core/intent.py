"""
alfred/core/intent.py
=====================
Two-layer intent classifier for Alfred.

HOW IT WORKS
────────────
Layer 1 — Keyword bypass
    Fast regex + string matching against common patterns.
    If a rule fires, no GPT call is made — instant classification.
    Covers: all HABIT_KEYWORDS from config, shopping list patterns,
    todo phrases, calendar queries, note patterns, weather, briefing,
    weekly summary.

Layer 2 — GPT classification
    Called only when no keyword rule fires.
    Sends the message to GPT with a structured system prompt listing
    every intent and its entity schema. Returns JSON only.
    Falls back to ASK on parse failure so the message is never dropped.

PUBLIC INTERFACE
────────────────
  classify(text: str) → IntentResult      (async)

  IntentResult attributes:
    .intent      str — one of the INTENT_* constants below
    .entities    dict — extracted values (schema varies by intent)
    .confidence  str — "keyword" | "gpt" | "fallback"
    .raw         str — original text passed to classify()
    .get(key, default=None)  — convenience accessor for entities

INTENT CONSTANTS (importable from this module)
────────────────────────────────────────────────
  TODO_ADD, TODO_LIST, TODO_COMPLETE, TODO_DELETE, TODO_UPDATE
  SHOP_ADD, SHOP_LIST, SHOP_COMPLETE, SHOP_DELETE, SHOP_CLEAR
  NOTE_ADD, NOTE_LIST, NOTE_DELETE
  CAL_VIEW, CAL_ADD, CAL_DELETE, CAL_UPDATE
  HABIT_LOG, HABIT_VIEW
  REMINDER_ADD, REMINDER_LIST, REMINDER_DONE, REMINDER_DELETE
  GIFT_ADD, GIFT_LIST, GIFT_DONE, GIFT_DELETE
  MEMORY_ADD, MEMORY_VIEW, MEMORY_REMOVE
  CONTACT_VIEW, CONTACT_ADD, CONTACT_UPDATE
  BRIEFING, WEATHER, WEEKLY_SUMMARY
  ASK, UNKNOWN
"""

import re
import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

from core.config import (
    HABITS,
    HABIT_KEYWORDS,
    SHOPPING_LISTS,
    SHOPPING_KEYWORDS,
    MEMORY_CATEGORIES,
    GPT_CHAT_MODEL,
    OPENAI_API_KEY,
    BOT_NAME,
)


# ═══════════════════════════════════════════════════════════════════════════════
# INTENT CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════

# Todos
TODO_ADD        = "todo_add"
TODO_LIST       = "todo_list"
TODO_COMPLETE   = "todo_complete"
TODO_DELETE     = "todo_delete"
TODO_UPDATE     = "todo_update"

# Shopping
SHOP_ADD        = "shop_add"
SHOP_LIST       = "shop_list"
SHOP_COMPLETE   = "shop_complete"
SHOP_DELETE     = "shop_delete"
SHOP_CLEAR      = "shop_clear_done"

# Notes
NOTE_ADD        = "note_add"
NOTE_LIST       = "note_list"
NOTE_DELETE     = "note_delete"
NOTE_SEARCH     = "note_search"

# Calendar
CAL_VIEW        = "cal_view"
CAL_ADD         = "cal_add"
CAL_DELETE      = "cal_delete"
CAL_UPDATE      = "cal_update"
CAL_EMOJI_SET      = "cal_emoji_set"
CAL_REPEAT_FILTER  = "cal_repeat_filter"

# Habits
HABIT_LOG       = "habit_log"
HABIT_VIEW      = "habit_view"

# Reminders
REMINDER_ADD    = "reminder_add"
REMINDER_LIST   = "reminder_list"
REMINDER_DONE   = "reminder_done"
REMINDER_DELETE = "reminder_delete"

# Gifts
GIFT_ADD        = "gift_add"
GIFT_LIST       = "gift_list"
GIFT_DONE       = "gift_done"
GIFT_DELETE     = "gift_delete"

# Memory
MEMORY_ADD      = "memory_add"
MEMORY_VIEW     = "memory_view"
MEMORY_REMOVE   = "memory_remove"

# Contacts
CONTACT_VIEW    = "contact_view"
CONTACT_ADD     = "contact_add"
CONTACT_UPDATE  = "contact_update"

# Utility intents
BRIEFING        = "briefing"
WEATHER         = "weather"
WEEKLY_SUMMARY  = "weekly_summary"

# Notes (extended)
NOTE_EDIT       = "note_edit"
NOTE_APPEND     = "note_append"

# Meals
MEAL_PLAN       = "meal_plan"
MEAL_VIEW       = "meal_view"
MEAL_ADD        = "meal_add"
MEAL_RECIPE     = "meal_recipe"
MEAL_GENERATE   = "meal_generate"
MEAL_IMPORT     = "meal_import_url"
MEAL_NUTRITION  = "meal_nutrition"
MEAL_ADHERENCE  = "meal_adherence"
MEAL_EXPORT     = "meal_export"
MEAL_LEFTOVERS  = "meal_leftovers"

# Workout
WORKOUT_LOG     = "workout_log"
WORKOUT_VIEW    = "workout_view"
WORKOUT_ASK     = "workout_suggest"
WORKOUT_PLAN    = "workout_plan_view"
WORKOUT_REBUILD = "workout_rebuild"
WORKOUT_TEMPLATE= "workout_template"
WORKOUT_EXPORT  = "workout_export"
WORKOUT_BODY    = "workout_body_stats"

# Journal
JOURNAL_PROMPT  = "journal_prompt"
JOURNAL_VIEW    = "journal_view"
JOURNAL_SEARCH  = "journal_search"
JOURNAL_MONTH   = "journal_month"
JOURNAL_WINS    = "journal_wins"

# Reply / email assist
REPLY_ASSIST    = "reply_assist"
EMAIL_ASSIST    = "email_assist"
REPLY_STYLE_ADD = "reply_style_add"

# Mood tracking
MOOD_LOG    = "mood_log"
MOOD_VIEW   = "mood_view"
MOOD_DELETE = "mood_delete"

# Link / read-later
LINK_SAVE      = "link_save"
LINK_VIEW      = "link_view"
LINK_SEARCH    = "link_search"
LINK_MARK_READ = "link_mark_read"
LINK_SNOOZE    = "link_snooze"

# Export
EXPORT_DATA = "export_data"

# Expense tracking
EXPENSE_ADD     = "expense_add"
EXPENSE_VIEW    = "expense_view"
EXPENSE_DELETE  = "expense_delete"

# Sleep tracking
SLEEP_LOG       = "sleep_log"
SLEEP_VIEW      = "sleep_view"

# Brain dump
BRAINDUMP       = "braindump"

# Undo
UNDO            = "undo"

# Proactive layer
PROACTIVE_TOGGLE    = "proactive_toggle"       # "turn off habit streak risk"
VACATION_MODE       = "vacation_mode"          # "vacation on until June 20"
PACKING_OVERRIDE    = "packing_override"       # "add sunscreen to beach packing list"

# Gmail
GMAIL_SEND      = "gmail_send"     # "email John that I'll be late"
GMAIL_DRAFT     = "gmail_draft"    # "draft an email to my landlord about..."
GMAIL_UNREAD    = "gmail_unread"   # "how many unread emails do I have?"

# Catch-all
ASK             = "ask"
UNKNOWN         = "unknown"

# All known intents (used for GPT validation)
_ALL_INTENTS = {
    TODO_ADD, TODO_LIST, TODO_COMPLETE, TODO_DELETE, TODO_UPDATE,
    SHOP_ADD, SHOP_LIST, SHOP_COMPLETE, SHOP_DELETE, SHOP_CLEAR,
    NOTE_ADD, NOTE_LIST, NOTE_DELETE, NOTE_SEARCH, NOTE_EDIT, NOTE_APPEND,
    CAL_VIEW, CAL_ADD, CAL_DELETE, CAL_UPDATE, CAL_EMOJI_SET, CAL_REPEAT_FILTER,
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
    MOOD_LOG, MOOD_VIEW, MOOD_DELETE,
    LINK_SAVE, LINK_VIEW, LINK_SEARCH, LINK_MARK_READ, LINK_SNOOZE,
    EXPORT_DATA,
    EXPENSE_ADD, EXPENSE_VIEW, EXPENSE_DELETE,
    SLEEP_LOG, SLEEP_VIEW,
    BRAINDUMP, UNDO,
    PROACTIVE_TOGGLE, VACATION_MODE, PACKING_OVERRIDE,
    GMAIL_SEND, GMAIL_DRAFT, GMAIL_UNREAD,
    BRIEFING, WEATHER, WEEKLY_SUMMARY,
    ASK, UNKNOWN,
}


# ═══════════════════════════════════════════════════════════════════════════════
# INTENT RESULT
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class IntentResult:
    """
    Returned by classify(). Always populated — never raises.

    intent      : one of the INTENT_* constants above
    entities    : dict of extracted values (varies by intent; see GPT prompt)
    confidence  : "keyword" (Layer 1 hit), "gpt" (Layer 2), "fallback" (error)
    raw         : original text passed to classify()
    """
    intent:     str
    entities:   dict = field(default_factory=dict)
    confidence: str  = "gpt"
    raw:        str  = ""

    def get(self, key: str, default: Any = None) -> Any:
        """Convenience accessor: result.get("item") instead of result.entities.get("item")."""
        return self.entities.get(key, default)


# ═══════════════════════════════════════════════════════════════════════════════
# LAYER 1 — KEYWORD BYPASS
# ═══════════════════════════════════════════════════════════════════════════════

def _r(pattern: str) -> re.Pattern:
    """Compile a case-insensitive regex pattern."""
    return re.compile(pattern, re.IGNORECASE)


def _detect_list_key(text: str) -> str:
    """
    Infer which shopping list a piece of text refers to.

    Priority:
      1. Direct key match ("grocery", "household", etc.)
      2. Direct label match ("Grocery", "Household", etc.)
      3. SHOPPING_KEYWORDS match (e.g. "toilet paper" → household)
      4. Default: "grocery"
    """
    tl = text.lower()

    for key, label in SHOPPING_LISTS.items():
        if key in tl or label.lower() in tl:
            return key

    for key, kw_list in SHOPPING_KEYWORDS.items():
        for kw in kw_list:
            if kw in tl:
                return key

    return "grocery"


def _build_keyword_rules() -> list:
    """
    Build and return the ordered list of (pattern, handler_fn) keyword rules.
    Rules are evaluated in order; first match wins.
    Called once at module load.
    """
    rules: list = []

    # ── SLEEP — LOG (must come BEFORE habit rules so "slept 7 hours" → sleep_log
    #    not habit_log, since "slept" is a sleep habit keyword that would match first)
    # Pattern deliberately requires a number so plain "slept" still hits habit_log.
    _p_sleep_log_early = _r(
        r"^(?:slept|sleep|got|logged?)\s+(?:for\s+)?(\d+(?:\.\d)?)\s*(?:hours?|hrs?)(?:\s+(?:of\s+)?sleep)?\s*$"
        r"|^(\d+(?:\.\d)?)\s*(?:hours?|hrs?)\s+(?:of\s+)?sleep\s*$"
    )

    def _sleep_log_early(m, t):
        hours = float(m.group(1) or m.group(2))
        return IntentResult(
            intent=SLEEP_LOG,
            entities={"hours": hours},
            confidence="keyword", raw=t,
        )

    rules.append((_p_sleep_log_early, _sleep_log_early))

    # ── UNDO ──────────────────────────────────────────────────────────────────
    # Must be before other rules — "undo" is short and could match other things
    p = _r(r"^(?:undo|undo\s+that|take\s+it\s+back|restore\s+(?:last|that)|cancel\s+(?:last|that))$")

    def _undo(m, t):
        return IntentResult(intent=UNDO, entities={}, confidence="keyword", raw=t)

    rules.append((p, _undo))

    # ── BRAIN DUMP ────────────────────────────────────────────────────────────
    # "brain dump: ..." / "dump this: ..." / "braindump: ..."
    p = _r(r"^(?:brain\s*dump|dump\s+this)[:\s]+(.+)$")

    def _braindump(m, t):
        return IntentResult(
            intent=BRAINDUMP,
            entities={"text": m.group(1).strip()},
            confidence="keyword", raw=t,
        )

    rules.append((p, _braindump))

    # ── VACATION MODE ─────────────────────────────────────────────────────────
    # "vacation on", "vacation on until June 20", "going on vacation"
    # "vacation off", "I'm back", "back from vacation"
    # "pause running on vacation", "keep tracking water on vacation"
    p_vac_on = _r(
        r"^(?:vacation\s+(?:mode\s+)?on|(?:turn\s+on|enable|start)\s+vacation(?:\s+mode)?|"
        r"going\s+on\s+vacation|i'?m\s+(?:going\s+)?on\s+vacation)"
        r"(?:\s+until\s+(.+))?$"
    )

    def _vac_on(m, t):
        end_date = (m.group(1) or "").strip()
        return IntentResult(
            intent=VACATION_MODE,
            entities={"action": "on", "end_date": end_date},
            confidence="keyword", raw=t,
        )

    rules.append((p_vac_on, _vac_on))

    p_vac_off = _r(
        r"^(?:vacation\s+(?:mode\s+)?off|(?:turn\s+off|disable|end|stop)\s+vacation(?:\s+mode)?|"
        r"i'?m\s+back(?:\s+from\s+vacation)?|back\s+from\s+vacation|home\s+from\s+vacation)$"
    )

    def _vac_off(m, t):
        return IntentResult(
            intent=VACATION_MODE,
            entities={"action": "off"},
            confidence="keyword", raw=t,
        )

    rules.append((p_vac_off, _vac_off))

    # "pause [habit] on vacation" / "keep tracking [habit] on vacation"
    p_vac_habit = _r(
        r"^(pause|keep\s+tracking|keep)\s+(.+?)\s+(?:on\s+vacation|during\s+vacation)$"
    )

    def _vac_habit(m, t):
        action_raw = m.group(1).lower()
        action = "pause" if "pause" in action_raw else "keep"
        habit  = m.group(2).strip().lower().replace(" ", "_")
        return IntentResult(
            intent=VACATION_MODE,
            entities={"action": action, "habit": habit},
            confidence="keyword", raw=t,
        )

    rules.append((p_vac_habit, _vac_habit))

    # "vacation on until June 20" — explicit until form
    p_vac_until = _r(r"^(?:vacation|holiday|away)\s+until\s+(.+)$")

    def _vac_until(m, t):
        return IntentResult(
            intent=VACATION_MODE,
            entities={"action": "on", "end_date": m.group(1).strip()},
            confidence="keyword", raw=t,
        )

    rules.append((p_vac_until, _vac_until))

    # ── PACKING OVERRIDE ─────────────────────────────────────────────────────
    # "add [item] to [trip type] packing list"
    # "add [item] to my packing list"
    p_pack = _r(
        r"^add\s+(.+?)\s+to\s+(?:my\s+)?(?:(\w+(?:\s+\w+)?)\s+)?packing\s+list$"
    )

    def _packing(m, t):
        item      = m.group(1).strip()
        trip_type = (m.group(2) or "generic").strip().lower().replace(" ", "_")
        return IntentResult(
            intent=PACKING_OVERRIDE,
            entities={"item": item, "trip_type": trip_type},
            confidence="keyword", raw=t,
        )

    rules.append((p_pack, _packing))

    # ── PROACTIVE TOGGLE ──────────────────────────────────────────────────────
    # "turn off habit streak risk", "enable expense spike alerts",
    # "disable back to back meetings", "turn on meeting prep"
    p_proactive_toggle = _r(
        r"^(?:(turn\s+off|disable|stop|mute)\s+|(turn\s+on|enable|unmute|resume)\s+)"
        r"([\w\s]+?)(?:\s+(?:alerts?|notifications?|check|nudge|reminder))?$"
    )

    def _proactive_toggle(m, t):
        action = "off" if m.group(1) else "on"
        label  = (m.group(3) or "").strip().lower()
        return IntentResult(
            intent=PROACTIVE_TOGGLE,
            entities={"action": action, "label": label},
            confidence="keyword", raw=t,
        )

    # Only append if the text contains "proactive", "alerts", or one of the
    # known toggle labels — avoids stealing generic "turn off X" phrases
    _PROACTIVE_HINT_WORDS = [
        "habit streak", "overdue todo", "priority todo", "back to back",
        "reminder overload", "sleep mood", "sleep declining", "workout frequency",
        "expense spike", "mood trend", "todo bloat", "recurring todo",
        "mood habit", "expense pacing", "meeting prep", "calendar gap",
        "travel time", "sleep event", "empty calendar", "monday planning",
        "weekly completion", "habit best day", "streak recognition",
        "shopping weekend", "smart note", "proactive", "travel alert",
        "vacation alert", "tomorrow prep", "night brief",
    ]

    def _proactive_toggle_guarded(m, t):
        tl = t.lower()
        if not any(h in tl for h in _PROACTIVE_HINT_WORDS):
            return None   # let GPT handle unrelated "turn off X" phrases
        return _proactive_toggle(m, t)

    rules.append((p_proactive_toggle, _proactive_toggle_guarded))

    # ── HABIT LOGGING ─────────────────────────────────────────────────────────
    # Built dynamically from HABIT_KEYWORDS so they stay in sync with config.
    # Match whole words only (word-boundary anchors).

    for habit_id, phrases in HABIT_KEYWORDS.items():
        for phrase in phrases:
            pattern = _r(r"(?<![a-zA-Z0-9])" + re.escape(phrase) + r"(?![a-zA-Z0-9])")
            _hid = habit_id  # capture in closure

            def _habit_handler(m, t, hid=_hid):
                return IntentResult(
                    intent=HABIT_LOG,
                    entities={"habit_id": hid},
                    confidence="keyword",
                    raw=t,
                )

            rules.append((pattern, _habit_handler))

    # ── SHOPPING — ADD ────────────────────────────────────────────────────────
    # "add almond milk to grocery list"
    # "add 2 avocados to the shopping list"
    # "add milk to my shopping list"
    _list_names = "|".join(re.escape(k) for k in SHOPPING_LISTS) + "|shopping"
    p = _r(rf"^add\s+(.+?)\s+to\s+(?:(?:the|my)\s+)?(?:{_list_names})\s*(?:list)?$")

    def _shop_add(m, t):
        item     = m.group(1).strip()
        list_key = _detect_list_key(t)
        return IntentResult(
            intent=SHOP_ADD,
            entities={"item": item, "list_key": list_key},
            confidence="keyword",
            raw=t,
        )

    rules.append((p, _shop_add))

    # "[item] on the grocery list" / "[item] for the grocery list"
    p = _r(rf"^(.+?)\s+(?:on|for)(?:\s+the)?\s+(?:{_list_names})\s+list$")

    def _shop_add2(m, t):
        return IntentResult(
            intent=SHOP_ADD,
            entities={"item": m.group(1).strip(), "list_key": _detect_list_key(t)},
            confidence="keyword",
            raw=t,
        )

    rules.append((p, _shop_add2))

    # "add X to the list" / "add X to my list" — generic fallback, list inferred from item
    p = _r(r"^add\s+(.+?)\s+to\s+(?:the|my)\s+list$")

    def _shop_add3(m, t):
        item     = m.group(1).strip()
        list_key = _detect_list_key(item)  # infer from the item itself
        return IntentResult(
            intent=SHOP_ADD,
            entities={"item": item, "list_key": list_key},
            confidence="keyword",
            raw=t,
        )

    rules.append((p, _shop_add3))

    # "show/what's on the grocery list" / "grocery list" alone
    p = _r(rf"(?:show|view|what(?:'s| is)(?: on)?)?\s*(?:my\s+|the\s+)?(?:{_list_names})\s+list\s*$")

    def _shop_list(m, t):
        return IntentResult(
            intent=SHOP_LIST,
            entities={"list_key": _detect_list_key(t)},
            confidence="keyword",
            raw=t,
        )

    rules.append((p, _shop_list))

    # "show all shopping lists" / "all lists"
    p = _r(r"(?:show|view|list)\s+all\s+(?:shopping\s+)?lists?")

    def _shop_list_all(m, t):
        return IntentResult(
            intent=SHOP_LIST,
            entities={"list_key": "all"},
            confidence="keyword",
            raw=t,
        )

    rules.append((p, _shop_list_all))

    # ── TODOS — ADD ───────────────────────────────────────────────────────────
    # "add todo X" / "add task X" / "add X to my todo list"
    p = _r(r"^(?:add\s+(?:todo|task)\s+(.+)|add\s+(.+?)\s+to\s+(?:my\s+)?(?:todo|task)s?(?:\s+list)?)$")

    def _todo_add(m, t):
        text = (m.group(1) or m.group(2) or "").strip()
        return IntentResult(
            intent=TODO_ADD,
            entities={"text": text},
            confidence="keyword",
            raw=t,
        )

    rules.append((p, _todo_add))

    # ── REMINDERS ─────────────────────────────────────────────────────────────
    # "remind me to X" — simple form (no date)
    # Date/time extraction is deferred to GPT for full parsing
    p = _r(r"^remind\s+me\s+to\s+(.+)$")

    def _reminder_add(m, t):
        return IntentResult(
            intent=REMINDER_ADD,
            entities={"text": m.group(1).strip()},
            confidence="keyword",
            raw=t,
        )

    rules.append((p, _reminder_add))

    # ── TODOS — LIST ──────────────────────────────────────────────────────────
    p = _r(r"^(?:show|list|what(?:'s| are)?)\s+(?:my\s+)?(?:todo|task)s?(?:\s+list)?$")

    def _todo_list(m, t):
        return IntentResult(intent=TODO_LIST, entities={}, confidence="keyword", raw=t)

    rules.append((p, _todo_list))

    # ── CALENDAR — VIEW ───────────────────────────────────────────────────────
    # "what's on my calendar today/this week/tomorrow"
    p = _r(r"what(?:'s| is)?\s+on\s+(?:my\s+)?(?:calendar|schedule)"
           r"|(?:show|check)\s+(?:my\s+)?(?:calendar|schedule)(?!\s+emojis?)(?!\s+(?:event\s+)?(?:filter|whitelist|repeat))")

    def _cal_view(m, t):
        import re as _re
        tl = t.lower()
        if "week" in tl:
            range_val = "week"
        elif "tomorrow" in tl:
            range_val = "tomorrow"
        elif "today" in tl or "today's" in tl:
            range_val = "today"
        else:
            # Try to extract a specific date mention: "May 10", "May 10th", "Jan 3rd"
            _date_re = _re.compile(
                r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
                r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
                r"\s+(\d{1,2})(?:st|nd|rd|th)?\b",
                _re.IGNORECASE,
            )
            date_match = _date_re.search(tl)
            if date_match:
                range_val = date_match.group(0).strip()  # e.g. "may 10"
            else:
                range_val = "today"
        return IntentResult(
            intent=CAL_VIEW,
            entities={"range": range_val},
            confidence="keyword",
            raw=t,
        )

    rules.append((p, _cal_view))

    # ── CALENDAR EMOJI SET ────────────────────────────────────────────────────
    # "use 💪 for workout" / "set trading emoji to 📊" / "show calendar emojis" / "reset calendar emojis"
    p = _r(
        r"^(?:use|set|change|make)\s+(.+?)\s+(?:emoji|icon|symbol)\s+(?:to|as)\s+(\S+)$"
        r"|^(?:use|set)\s+(\S+)\s+(?:for|on)\s+(.+?)(?:\s+events?)?$"
        r"|^(?:show|list|view)\s+(?:my\s+)?(?:calendar\s+)?(?:custom\s+)?emojis?$"
        r"|^reset\s+(?:calendar\s+)?emojis?$"
    )

    def _cal_emoji_set(m, t):
        tl = t.lower().strip()
        # show / reset commands
        if tl.startswith(("show", "list", "view")):
            return IntentResult(intent=CAL_EMOJI_SET, entities={"keyword": "show", "emoji": ""}, confidence="keyword", raw=t)
        if tl.startswith("reset"):
            return IntentResult(intent=CAL_EMOJI_SET, entities={"keyword": "reset", "emoji": ""}, confidence="keyword", raw=t)
        groups = m.groups()
        # Pattern 1: "use X emoji to 💪"  → groups (X, 💪, None, None)
        # Pattern 2: "use 💪 for workout" → groups (None, None, 💪, workout)
        if groups[0] and groups[1]:
            return IntentResult(intent=CAL_EMOJI_SET, entities={"keyword": groups[0].strip().lower(), "emoji": groups[1].strip()}, confidence="keyword", raw=t)
        if groups[2] and groups[3]:
            # Detect which is emoji and which is keyword (emoji is a single char or short string)
            a, b = groups[2].strip(), groups[3].strip().lower()
            if len(a) <= 4:   # likely the emoji
                return IntentResult(intent=CAL_EMOJI_SET, entities={"keyword": b, "emoji": a}, confidence="keyword", raw=t)
            else:
                return IntentResult(intent=CAL_EMOJI_SET, entities={"keyword": a.lower(), "emoji": b}, confidence="keyword", raw=t)
        return IntentResult(intent=CAL_EMOJI_SET, entities={}, confidence="keyword", raw=t)

    rules.append((p, _cal_emoji_set))

    # ── CAL REPEAT FILTER ─────────────────────────────────────────────────────
    # Matches: hide/show repeating events, always show [title], remove from whitelist
    p = _r(
        r"hide\s+(?:repeating|daily|recurring)\s+events?"
        r"|filter\s+(?:out\s+)?(?:repeating|daily|recurring)\s+events?"
        r"|show\s+(?:all|every)\s+(?:week\s+)?events?"
        r"|show\s+repeating\s+events?"
        r"|disable\s+(?:event\s+)?(?:repeat\s+)?filter"
        r"|always\s+show\s+.+"
        r"|never\s+hide\s+.+"
        r"|(?:whitelist|exempt)\s+.+"
        r"|remove\s+.+?\s+from\s+(?:the\s+)?whitelist"
        r"|stop\s+always\s+showing\s+.+"
        r"|show\s+(?:calendar\s+)?(?:event\s+)?(?:filter|whitelist)"
        r"|calendar\s+filter\s+settings?"
    )
    def _cal_repeat_filter(m, t):
        tl = t.lower().strip()
        # Whitelist add: "always show X" / "never hide X" — check BEFORE show/hide
        add_m = re.search(r"(?:always\s+show|never\s+hide|(?:whitelist|exempt))\s+(.+)", tl)
        if add_m:
            return IntentResult(intent=CAL_REPEAT_FILTER, entities={"action": "whitelist_add", "title": add_m.group(1).strip()}, confidence="keyword", raw=t)
        # Whitelist remove
        rem_m = re.search(r"remove\s+(.+?)\s+from\s+(?:the\s+)?whitelist|stop\s+always\s+showing\s+(.+)", tl)
        if rem_m:
            title = (rem_m.group(1) or rem_m.group(2) or "").strip()
            return IntentResult(intent=CAL_REPEAT_FILTER, entities={"action": "whitelist_remove", "title": title}, confidence="keyword", raw=t)
        # List filter settings
        if re.search(r"show\s+(?:calendar\s+)?(?:event\s+)?(?:filter|whitelist)|calendar\s+filter\s+settings?", tl):
            return IntentResult(intent=CAL_REPEAT_FILTER, entities={"action": "list"}, confidence="keyword", raw=t)
        # Show all
        if re.search(r"show\s+(?:all|every)\s+(?:week\s+)?events?|show\s+repeating\s+events?|disable\s+(?:event\s+)?(?:repeat\s+)?filter", tl):
            return IntentResult(intent=CAL_REPEAT_FILTER, entities={"action": "show"}, confidence="keyword", raw=t)
        # Default: hide
        return IntentResult(intent=CAL_REPEAT_FILTER, entities={"action": "hide"}, confidence="keyword", raw=t)
    rules.append((p, _cal_repeat_filter))

    # ── HABIT VIEW ────────────────────────────────────────────────────────────
    p = _r(r"(?:show|check|how(?:'s| are)?)\s+(?:my\s+)?habits?"
           r"|habit\s+(?:progress|check|summary|status)")

    def _habit_view(m, t):
        return IntentResult(intent=HABIT_VIEW, entities={}, confidence="keyword", raw=t)

    rules.append((p, _habit_view))

    # ── NOTES — ADD ───────────────────────────────────────────────────────────
    # "note: …" / "add note: …" / "note to self: …" / "save a note: …"
    p = _r(r"^(?:add\s+(?:a\s+)?note|note(?:\s+to\s+self)?|save\s+(?:a\s+)?note)"
           r"[:\s]+(.+)$")

    def _note_add(m, t):
        return IntentResult(
            intent=NOTE_ADD,
            entities={"text": m.group(1).strip()},
            confidence="keyword",
            raw=t,
        )

    rules.append((p, _note_add))

    # ── NOTES — LIST ──────────────────────────────────────────────────────────
    p = _r(r"(?:show|list|what are)\s+(?:my\s+)?notes?$")

    def _note_list(m, t):
        return IntentResult(intent=NOTE_LIST, entities={}, confidence="keyword", raw=t)

    rules.append((p, _note_list))

    # ── NOTES — DELETE ────────────────────────────────────────────────────────
    # "delete note 2" / "remove note about dry cleaning". MUST be appended before
    # the SEARCH rule below — otherwise "note about X" gets captured as a search.
    # Anchored with ^ so it never catches "find notes about X".
    p = _r(r"^(?:delete|remove)\s+(?:my\s+)?notes?\s+(.+)$")

    def _note_delete(m, t):
        q = m.group(1).strip()
        # Strip a leading "about/on/regarding" so the text match works on the topic.
        q = re.sub(r"^(?:about|on|regarding|the\s+one\s+about)\s+", "", q, flags=re.I).strip()
        return IntentResult(
            intent=NOTE_DELETE,
            entities={"query": q},
            confidence="keyword",
            raw=t,
        )

    rules.append((p, _note_delete))

    # ── NOTES — SEARCH ────────────────────────────────────────────────────────
    # "find notes about dentist" / "search notes for budget" / "notes about X"
    p = _r(r"(?:find|search|look\s+(?:up|for))\s+(?:my\s+)?notes?\s+(?:about|for|on|with)\s+(.+)"
           r"|notes?\s+(?:about|on|mentioning|with)\s+(.+)"
           r"|(?:find|search)\s+(?:in\s+)?(?:my\s+)?notes?\s+(.+)")

    def _note_search(m, t):
        # Pull first non-None capture group
        query = next((g for g in m.groups() if g), "").strip()
        return IntentResult(
            intent=NOTE_SEARCH,
            entities={"query": query},
            confidence="keyword",
            raw=t,
        )

    rules.append((p, _note_search))

    # ── WEATHER ───────────────────────────────────────────────────────────────
    p = _r(r"(?:what(?:'s| is)|how(?:'s)?)\s+the\s+weather"
           r"|weather\s+(?:today|forecast|report|tomorrow)"
           r"|will\s+it\s+rain"
           r"|is\s+it\s+going\s+to\s+(?:rain|snow|be\s+cold|be\s+hot|be\s+warm)")

    def _weather(m, t):
        return IntentResult(intent=WEATHER, entities={}, confidence="keyword", raw=t)

    rules.append((p, _weather))

    # ── BRIEFING ──────────────────────────────────────────────────────────────
    p = _r(r"^(?:morning\s+)?briefing"
           r"|send\s+(?:me\s+)?(?:my\s+)?briefing"
           r"|what(?:'s|\s+is)\s+(?:my\s+)?(?:morning\s+)?update")

    def _briefing(m, t):
        return IntentResult(intent=BRIEFING, entities={}, confidence="keyword", raw=t)

    rules.append((p, _briefing))

    # ── WEEKLY SUMMARY ────────────────────────────────────────────────────────
    p = _r(r"what\s+did\s+i\s+(?:do|accomplish)"
           r"|weekly\s+(?:summary|review|recap)"
           r"|week\s+in\s+review"
           r"|how\s+(?:was|did)\s+(?:my\s+)?week")

    def _weekly(m, t):
        return IntentResult(intent=WEEKLY_SUMMARY, entities={}, confidence="keyword", raw=t)

    rules.append((p, _weekly))

    # ── TODO — COMPLETE (mark done) ───────────────────────────────────────
    # "mark buy groceries done" / "check off buy groceries" / "done with laundry"
    # "complete my todo about dentist" / "finished the report"
    p = _r(r"^(?:mark|check)\s+(?:off\s+)?(.+?)\s+(?:as\s+)?(?:done|complete|off|finished)$"
           r"|^(?:done|finished)\s+(?:with\s+)?(.+)$"
           r"|^(?:complete|finish)\s+(?:my\s+)?(?:todo|task)?\s*(?:about\s+|for\s+)?(.+)$")

    def _todo_complete(m, t):
        query = (m.group(1) or m.group(2) or m.group(3) or "").strip()
        return IntentResult(
            intent=TODO_COMPLETE,
            entities={"query": query},
            confidence="keyword",
            raw=t,
        )

    rules.append((p, _todo_complete))

    # ── TODO — DELETE ─────────────────────────────────────────────────────
    # "delete todo buy milk" / "remove task dentist"
    p = _r(r"^(?:delete|remove)\s+(?:my\s+)?(?:todo|task)\s+(.+)$")

    def _todo_delete(m, t):
        return IntentResult(
            intent=TODO_DELETE,
            entities={"query": m.group(1).strip()},
            confidence="keyword",
            raw=t,
        )

    rules.append((p, _todo_delete))

    # ── SHOP — COMPLETE (cross off) ───────────────────────────────────────
    # "got the milk" / "crossed off eggs" / "got almond milk"
    p = _r(r"^(?:got|crossed\s+off|picked\s+up|bought)\s+(?:the\s+)?(.+)$")

    def _shop_complete(m, t):
        item = m.group(1).strip()
        return IntentResult(
            intent=SHOP_COMPLETE,
            entities={"item": item, "list_key": _detect_list_key(item)},
            confidence="keyword",
            raw=t,
        )

    rules.append((p, _shop_complete))

    # ── WORKOUT — LOG ─────────────────────────────────────────────────────
    # "just finished my workout" / "workout done" / "did a workout"
    # "did chest and triceps" / "lifted for 45 minutes"
    p = _r(r"^(?:just\s+)?(?:finished|completed|did)\s+(?:my\s+|a\s+)?workout"
           r"|^workout\s+(?:done|complete|finished)"
           r"|^(?:just\s+)?(?:finished|completed|did)\s+(?:my\s+|a\s+)?(.+?)\s+workout$"
           r"|^lifted\s+(?:weights?\s+)?(?:for\s+)?(.+)$"
           r"|^(?:just\s+)?(?:did|finished|completed)\s+(chest|back|legs|shoulders|arms|cardio|abs|push|pull|upper|lower)")

    def _workout_log(m, t):
        desc = (m.group(1) or m.group(2) or m.group(3) or "").strip()
        entities = {"description": desc} if desc else {}
        return IntentResult(
            intent=WORKOUT_LOG,
            entities=entities,
            confidence="keyword",
            raw=t,
        )

    rules.append((p, _workout_log))

    # ── MOOD — LOG ────────────────────────────────────────────────────────
    # "mood 7" / "feeling 8" / "i feel great" / "i'm feeling happy"
    p = _r(r"^(?:mood|feeling)\s+(\d{1,2})(?:\s+(.+))?$"
           r"|^i(?:'m|\s+am)\s+feeling\s+(.+)$")

    def _mood_log(m, t):
        if m.group(1):
            return IntentResult(
                intent=MOOD_LOG,
                entities={"rating": int(m.group(1)), "note": (m.group(2) or "").strip()},
                confidence="keyword",
                raw=t,
            )
        return IntentResult(
            intent=MOOD_LOG,
            entities={"note": (m.group(3) or "").strip()},
            confidence="keyword",
            raw=t,
        )

    rules.append((p, _mood_log))

    # ── MOOD — DELETE ─────────────────────────────────────────────────────
    # "delete my mood" / "delete today's mood entry" / "remove mood for 2026-06-09"
    p = _r(r"^(?:delete|remove|clear)\s+(?:my\s+|the\s+)?(?:today'?s\s+)?mood"
           r"(?:\s+(?:entry|log|rating))?(?:\s+(?:for|on)\s+(.+))?$")

    def _mood_delete(m, t):
        return IntentResult(
            intent=MOOD_DELETE,
            entities={"date": (m.group(1) or "").strip()},
            confidence="keyword",
            raw=t,
        )

    rules.append((p, _mood_delete))

    # ── MEMORY — ADD (quick) ──────────────────────────────────────────────
    # "remember that I hate cilantro" / "remember my favorite color is blue"
    p = _r(r"^remember\s+(?:that\s+)?(.+)$")

    def _memory_add(m, t):
        return IntentResult(
            intent=MEMORY_ADD,
            entities={"fact": m.group(1).strip()},
            confidence="keyword",
            raw=t,
        )

    rules.append((p, _memory_add))

    # ── MEMORY — REMOVE ──────────────────────────────────────────────────
    # "forget that I hate cilantro" / "forget about my allergy"
    p = _r(r"^forget\s+(?:that\s+|about\s+)?(.+)$")

    def _memory_remove(m, t):
        return IntentResult(
            intent=MEMORY_REMOVE,
            entities={"fact": m.group(1).strip()},
            confidence="keyword",
            raw=t,
        )

    rules.append((p, _memory_remove))

    # ── LINK — SAVE ───────────────────────────────────────────────────────
    # "save this link https://..." / "read later https://..."
    p = _r(r"^(?:save|bookmark|read\s+later)\s+(?:this\s+)?(?:link\s+|url\s+)?(https?://\S+)(?:\s+(.+))?$")

    def _link_save(m, t):
        return IntentResult(
            intent=LINK_SAVE,
            entities={"url": m.group(1).strip(), "note": (m.group(2) or "").strip()},
            confidence="keyword",
            raw=t,
        )

    rules.append((p, _link_save))

    # ── EXPORT ────────────────────────────────────────────────────────────
    # "export my data" / "export everything" / "download my data"
    p = _r(r"^(?:export|download)\s+(?:my\s+|all\s+)?(?:data|everything)$")

    def _export(m, t):
        return IntentResult(intent=EXPORT_DATA, entities={}, confidence="keyword", raw=t)

    rules.append((p, _export))

    # ── EXPENSE — ADD ─────────────────────────────────────────────────────
    # "$45 groceries" / "spent $12 on coffee" / "logged $100 dining"
    # "expense $25 gas" / "$8.50 lunch"
    _EXPENSE_CATS = r"(?:groceries|grocery|dining|restaurant|food|coffee|transport|uber|lyft|gas|health|gym|entertainment|shopping|household|subscriptions?|misc|other)"
    p = _r(
        rf"^\$(\d+(?:\.\d{{1,2}})?)\s+({_EXPENSE_CATS})(?:\s+(.+))?$"
        rf"|^(?:spent|paid|logged?|expense)\s+\$?(\d+(?:\.\d{{1,2}})?)\s+(?:on\s+|for\s+)?(.+?)(?:\s+(.+))?$"
        rf"|^(?:expense)\s+(.+?)\s+\$(\d+(?:\.\d{{1,2}})?)"
    )

    def _expense_add(m, t):
        # Pattern 1: "$45 groceries [note]"
        if m.group(1):
            return IntentResult(
                intent=EXPENSE_ADD,
                entities={"amount": float(m.group(1)), "category": m.group(2).strip().lower(), "note": (m.group(3) or "").strip()},
                confidence="keyword", raw=t,
            )
        # Pattern 2: "spent $25 on coffee [note]"
        if m.group(4):
            return IntentResult(
                intent=EXPENSE_ADD,
                entities={"amount": float(m.group(4)), "category": m.group(5).strip().lower(), "note": (m.group(6) or "").strip()},
                confidence="keyword", raw=t,
            )
        # Pattern 3: "expense coffee $25"
        return IntentResult(
            intent=EXPENSE_ADD,
            entities={"amount": float(m.group(8)), "category": m.group(7).strip().lower(), "note": ""},
            confidence="keyword", raw=t,
        )

    rules.append((p, _expense_add))

    # ── EXPENSE — VIEW ────────────────────────────────────────────────────
    # "show my expenses" / "how much did I spend" / "expense summary"
    p = _r(r"(?:show|view|list|check)\s+(?:my\s+)?expenses?"
           r"|how\s+much\s+(?:did\s+i\s+|have\s+i\s+)?spent?"
           r"|expense\s+(?:summary|report|history|total)"
           r"|what\s+did\s+i\s+spend")

    def _expense_view(m, t):
        return IntentResult(intent=EXPENSE_VIEW, entities={}, confidence="keyword", raw=t)

    rules.append((p, _expense_view))

    # ── SLEEP — LOG ───────────────────────────────────────────────────────
    # "slept 7 hours" / "slept for 6.5 hours" / "got 8 hours of sleep"
    # "sleep 7" / "logged 7 hours sleep"
    p = _r(r"^(?:slept|sleep|got|logged?)\s+(?:for\s+)?(\d+(?:\.\d)?)\s*(?:hours?\s+(?:of\s+)?(?:sleep)?|hrs?)"
           r"|^(\d+(?:\.\d)?)\s*(?:hours?\s+(?:of\s+)?sleep|hrs?\s+sleep)")

    def _sleep_log(m, t):
        hours = float(m.group(1) or m.group(2))
        return IntentResult(
            intent=SLEEP_LOG,
            entities={"hours": hours},
            confidence="keyword", raw=t,
        )

    rules.append((p, _sleep_log))

    # ── SLEEP — VIEW ──────────────────────────────────────────────────────
    # "show my sleep" / "sleep history" / "how much did I sleep"
    p = _r(r"(?:show|view|check|list)\s+(?:my\s+)?sleep(?:\s+(?:log|history|stats?))?"
           r"|how\s+(?:much|well|long)\s+(?:did\s+i\s+|have\s+i\s+)?slept?"
           r"|sleep\s+(?:summary|stats?|history|average)")

    def _sleep_view(m, t):
        return IntentResult(intent=SLEEP_VIEW, entities={}, confidence="keyword", raw=t)

    rules.append((p, _sleep_view))

    # ── GMAIL — UNREAD ────────────────────────────────────────────────────
    # "how many unread emails" / "check my inbox" / "any emails"
    p = _r(r"(?:how\s+many\s+(?:unread\s+)?emails?|check\s+(?:my\s+)?(?:email|inbox|gmail)|"
           r"any\s+(?:new\s+|unread\s+)?emails?|what(?:'s|\s+is)\s+in\s+my\s+(?:inbox|email))")

    def _gmail_unread(m, t):
        return IntentResult(intent=GMAIL_UNREAD, entities={}, confidence="keyword", raw=t)

    rules.append((p, _gmail_unread))

    # ── GMAIL — DRAFT ─────────────────────────────────────────────────────
    # "draft an email to..." / "compose an email to..." / "write an email to..."
    p = _r(r"^(?:draft|compose|write)\s+(?:an?\s+)?email\s+to\s+")

    def _gmail_draft(m, t):
        return IntentResult(intent=GMAIL_DRAFT, entities={"to": "", "subject": "", "body": t}, confidence="keyword", raw=t)

    rules.append((p, _gmail_draft))

    # ── GMAIL — SEND ──────────────────────────────────────────────────────
    # "email john@example.com that..." / "email John that..." / "send an email to..."
    # Must fire BEFORE email_assist grabs it. email_assist = drafting a REPLY
    # to an email you received. gmail_send = composing a NEW email.
    p = _r(r"^(?:send\s+(?:an?\s+)?email\s+to\s+|email\s+\S+@\S+|"
           r"email\s+\w+\s+(?:that|about|saying|to\s+say|to\s+tell|letting))")

    def _gmail_send(m, t):
        return IntentResult(intent=GMAIL_SEND, entities={"to": "", "subject": "", "body": t}, confidence="keyword", raw=t)

    rules.append((p, _gmail_send))

    return rules


# Build rules once at module load
_KEYWORD_RULES = _build_keyword_rules()


def _keyword_classify(text: str) -> "IntentResult | None":
    """
    Layer 1: scan keyword rules. Returns the first match or None.
    Never raises — errors per-rule are caught and skipped.
    """
    stripped = text.strip()
    for pattern, handler in _KEYWORD_RULES:
        try:
            m = pattern.search(stripped)
            if m:
                return handler(m, stripped)
        except Exception as e:
            logger.warning(f"intent: keyword rule error ({pattern.pattern!r}): {e}")
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# LAYER 2 — GPT CLASSIFICATION
# ═══════════════════════════════════════════════════════════════════════════════

_SHOPPING_KEYS = "|".join(f'"{k}"' for k in SHOPPING_LISTS)
_HABIT_IDS     = ", ".join(f'"{h}"' for h in HABITS)

# _gpt_system_prompt is set at module load using the default MEMORY_CATEGORIES.
# Call refresh_intent_prompt(categories) at bot startup (after alfred_memory.json
# is loaded) so it reflects any custom categories the buyer added during /setup.
_gpt_system_prompt: str = ""


def _build_gpt_system(memory_categories: list) -> str:
    """
    Build the GPT classification system prompt.

    Called once at import time with config defaults, then again at bot startup
    with the live category list from alfred_memory.json.

    Args:
        memory_categories: The current active list of memory categories.
    """
    import datetime as _dt
    from zoneinfo import ZoneInfo as _ZI
    from core.config import TIMEZONE as _TZ
    _today_str = _dt.datetime.now(_ZI(_TZ)).strftime("%Y-%m-%d")
    memory_cats = "|".join(f'"{c}"' for c in memory_categories)
    return f"""You are the intent classifier for {BOT_NAME}, a personal assistant Telegram bot.
Classify the user's message into exactly one intent and extract relevant entities.
Return ONLY valid JSON — no markdown, no explanation, nothing else.

INTENTS AND ENTITY SCHEMAS:

todo_add        Add a task/todo.
                Entities: text (required), due (date str or null), recur ("daily"|"weekdays"|"weekly"|"monthly"|null), notes (str or null)

todo_list       Show the todo list.
                Entities: {{}}

todo_complete   Mark a todo as done.
                Entities: query (what task to search for)

todo_delete     Delete a todo.
                Entities: query

todo_update     Edit a todo (text, due date, or recurrence).
                Entities: query, new_text (optional), new_due (optional), new_recur (optional)

shop_add        Add an item to a shopping list.
                Entities: item, list_key (one of: {_SHOPPING_KEYS}, default "grocery"), quantity (optional str)

shop_list       View a shopping list.
                Entities: list_key (one of: {_SHOPPING_KEYS} or "all")

shop_complete   Cross off / mark a shopping item as gotten.
                Entities: item, list_key (optional)

shop_delete     Remove a shopping item entirely.
                Entities: item, list_key (optional)

shop_clear_done Clear all completed items from a shopping list.
                Entities: list_key

note_add        Save a note.
                Entities: text (required), title (optional)

note_list       List saved notes.
                Entities: {{}}

note_delete     Delete a note.
                Entities: query

note_search     Search notes by keyword.
                Entities: query (required — the search term)

cal_view        Show calendar events.
                Entities: period ("today"|"tomorrow"|"week"|"upcoming"), days (int, optional for "upcoming")

cal_add         Create a calendar event.
                Entities: title (required), start (ISO "YYYY-MM-DDTHH:MM" — always resolve relative dates like "next Monday at noon" to absolute ISO using today={_today_str}),
                          end (ISO, optional), location (optional), description (optional),
                          recur (optional: "daily"|"weekdays"|"weekly"|"monthly"|"yearly"),
                          all_day (bool, default false), attendees (list of emails, optional),
                          calendar (optional — e.g. "work" or "family" if user specifies a calendar).
                Note: "add X at time" (no "remind me") → cal_add. "schedule X" → cal_add. Only use reminder_add when user explicitly says "remind me".

cal_delete      Delete / cancel a calendar event.
                Entities: query

cal_update      Modify a calendar event — reschedule, rename, or change details.
                Entities: title (required — event to find, the CURRENT name),
                          new_start (ISO "YYYY-MM-DDTHH:MM" for new start time — always include date),
                          new_end (ISO "YYYY-MM-DDTHH:MM" for new end time, optional),
                          new_title (str — new event name, only if user wants to rename it),
                          new_location (str — new location, only if changing location),
                          new_description (str — new description, only if changing description).
                Note: today is {_today_str}. Always resolve relative times like "4pm tomorrow" or "next Monday at 2pm" to absolute ISO datetime strings.

habit_log       Log a habit as completed today.
                Entities: habit_id (one of: {_HABIT_IDS})

habit_view      Show today's habit progress.
                Entities: {{}}

reminder_add    Add a reminder or recurring reminder.
                Entities: text (required), due (date/time str or null),
                          recur ("daily"|"weekdays"|"weekly"|"monthly"|null),
                          recur_day (int 0–6, Mon=0…Sun=6, only when a specific weekday is mentioned e.g. "every Monday"→0, "every Friday"→4)

reminder_list   List active reminders.
                Entities: {{}}

reminder_done   Mark a reminder as complete.
                Entities: query

reminder_delete Delete a reminder.
                Entities: query

gift_add        Add a gift idea.
                Entities: recipient (required), idea (required), occasion (optional), date (optional)

gift_list       Show gift ideas.
                Entities: recipient (or "all")

gift_done       Mark a gift idea as purchased.
                Entities: query

gift_delete     Remove a gift idea.
                Entities: query

memory_add      Add a long-term fact to Alfred's memory.
                Entities: category (one of: {memory_cats}), fact (str)

memory_view     View Alfred's stored memory.
                Entities: category (one of: {memory_cats}, or "all")

memory_remove   Remove a specific fact from Alfred's memory.
                Entities: category (one of: {memory_cats}), fact (str)

contact_view    Look up information about a person.
                Entities: name

contact_add     Add a new contact.
                Entities: name (required), notes (str)

contact_update  Update notes for an existing contact.
                Entities: name (required), updates (str)

cal_emoji_set   Customize which emoji Alfred uses for a calendar event keyword.
                Entities: keyword (str — the word to match in event titles, e.g. "workout"),
                          emoji (str — the emoji to use, e.g. "💪").
                Special keywords: "show"/"list" → display overrides. "reset"/"clear" → restore defaults.

note_edit       Replace the content of an existing note.
                Entities: ref (int or keyword str), new_text (str)

note_append     Add more text to an existing note.
                Entities: ref (int or keyword str), append_text (str)

meal_plan       Set or view a meal plan for a day or week.
                Entities: action ("set"|"view"), date (str, optional), meals (dict day->meal list)

meal_view       Show meals planned for today or a given day.
                Entities: date (str, default "today")

meal_add        Add a recipe or meal to the library.
                Entities: name (str), ingredients (str), instructions (str), prep_min (int), cook_min (int), calories (int), protein_g (int), carbs_g (int), fat_g (int)

meal_recipe     Look up a stored recipe.
                Entities: name (str)

meal_generate   Ask Alfred to create a recipe using GPT.
                Entities: description (str), save (bool)

meal_import_url Import a recipe from a URL.
                Entities: url (str)

meal_nutrition  Get nutrition summary for today's planned meals.
                Entities: date (str, default "today")

meal_adherence  Log what was actually eaten vs the plan.
                Entities: date (str), notes (str)

meal_export     Export the meals Excel file.
                Entities: {{}}

meal_leftovers  Log or check leftovers.
                Entities: action ("log"|"view"), details (str)

workout_log     Log a completed workout session.
                Entities: description (str), duration_min (int), energy (int 1-5), exercises (list of {{exercise, sets, reps, weight_lb}}), cardio ({{distance_km, pace_min_km}})

workout_view    View recent workout history.
                Entities: days (int, default 7)

workout_suggest Ask Alfred for a workout suggestion for today.
                Entities: muscle_group (str, optional)

workout_plan_view  View the current workout program.
                Entities: {{}}

workout_rebuild Rebuild the GPT-generated workout program.
                Entities: {{}}

workout_template Manage named workout templates.
                Entities: action ("save"|"load"|"list"), name (str)

workout_export  Export the workout log Excel file.
                Entities: {{}}

workout_body_stats Log or view body weight and measurements.
                Entities: action ("log"|"view"), weight_lb (float), measurements (dict)

journal_prompt  Start the nightly journal session (prompted mode).
                Entities: {{}}

journal_view    View a past journal entry.
                Entities: date (str, default "today")

journal_search  Search past journal entries by keyword or date.
                Entities: query (str), date (str, optional)

journal_month   Get a GPT summary of the current month's journal entries.
                Entities: month (str, optional, default current month)

journal_wins    Show positive highlights extracted from journal entries.
                Entities: days (int, default 30)

gmail_send      Send a new email from the user's Gmail account.
                Entities: to (str, required — recipient name or email address),
                          subject (str — infer from context if not stated),
                          body (str — the full message instruction or text)
                Use this when the user says "email [name/address] that..." or "send an email to...".
                Do NOT use for replying to received emails — that is email_assist.

gmail_draft     Save an email to Gmail Drafts without sending.
                Entities: to (str, required), subject (str), body (str)
                Use this when the user says "draft/compose/write an email to...".

gmail_unread    Check unread email count and VIP inbox highlights.
                Entities: {{}}
                Use for "how many unread emails", "check my inbox", "any new emails".

reply_assist    Draft reply suggestions for a text message screenshot or description.
                Entities: context (str, optional description the user typed before sending photo)

email_assist    Draft a reply to an email the user RECEIVED (screenshot or pasted text).
                Entities: email_text (str, optional), context (str, optional)
                Do NOT use when the user wants to SEND or COMPOSE a new email — use gmail_send or gmail_draft.

reply_style_add Save a writing style example to the reply style library.
                Entities: example (str)

mood_log        Log the user's current mood/emotional state (1-10 rating).
                Entities: rating (int 1-10), note (str optional)

mood_view       Show the user's recent mood history or trends.
                Entities: days (int, default 7)

mood_delete     Delete a logged mood entry (defaults to today's entry).
                Entities: date (str, optional — ISO date like 2026-06-09; empty means today)

link_save       Save a URL to the read-later list.
                Entities: url (str), note (str optional)

link_view       Show the user's saved/unread links.
                Entities: {{}}

link_search     Search saved links by keyword.
                Entities: query (str)

link_mark_read  Mark a saved link as read.
                Entities: query (str, optional)

link_snooze     Snooze a saved link for later.
                Entities: query (str, optional), days (int, default 3)

export_data     Export all user data (journal, habits, mood, etc.) to a file.
                Entities: {{}}

braindump       Sort a messy stream-of-consciousness into todos, reminders, notes, and shopping.
                Entities: text (the raw dump text)

undo            Undo the last deletion (todo, note, shopping item, expense, or mood).
                Entities: {{}}

expense_add     Log a new expense.
                Entities: amount (float, required), category (str: groceries|dining|transport|health|entertainment|shopping|household|subscriptions|other), note (str optional)

expense_view    Show expense history or summary.
                Entities: days (int, default 30), category (str optional)

expense_delete  Delete a logged expense.
                Entities: query (str)

sleep_log       Log hours of sleep.
                Entities: hours (float, required), quality (int 1-5, optional), note (str optional)

sleep_view      Show recent sleep history or average.
                Entities: days (int, default 7)

briefing        Request the morning briefing right now.
                Entities: {{}}

weather         Ask about the weather.
                Entities: location (optional; omit to default to home city)

weekly_summary  Show a summary of the current week.
                Entities: {{}}

ask             General question, search, conversation, or anything that doesn't fit above.
                Entities: query (the full message text)

unknown         Cannot determine intent at all.
                Entities: {{}}

CLASSIFICATION RULES:
- When in doubt between a specific intent and "ask", prefer the specific intent.
- If the message is a general knowledge question (not about the user's data), use "ask".
- If the message references the user's personal data (todos, calendar, habits, etc.), use the specific intent.
- "remind me to X" always maps to reminder_add, not todo_add.
- "add X at [time]" or "add X on [date]" or "schedule X" (without "remind me") → cal_add, not reminder_add.
- "add daily X at [time]" where X is an activity → cal_add with recur="daily", not reminder_add.
- "add X to my list" without a specific list → shop_add with list_key "grocery".
- Always resolve dates/times to absolute ISO format. Today is {_today_str}. Use "YYYY-MM-DD" for date-only, "YYYY-MM-DDTHH:MM" for date+time. Example: "remind me tomorrow at 3pm" → due "YYYY-MM-DDTHH:MM" using tomorrow's date.

DISAMBIGUATION:
- "I worked out" / "hit the gym" / "exercised" → habit_log (quick check-in for the habit streak).
- "Did chest and triceps for 45 min" / "just finished 5x5 squats at 225" → workout_log (detailed session with description/exercises).
- Rule of thumb: short acknowledgments of exercise → habit_log. Detailed workout descriptions → workout_log.
- "done with X" / "mark X done" / "finished X" → todo_complete (not workout_log unless it explicitly says "workout").
- "forget X" → memory_remove. "remember X" → memory_add.
- "mood 7" or "feeling 8" → mood_log. "how's my mood" / "mood history" → mood_view. "delete today's mood" / "remove my mood entry" → mood_delete.
- "$45 groceries" / "spent $12 on coffee" → expense_add. "show my expenses" / "how much did I spend" → expense_view.
- "slept 7 hours" / "got 6 hours of sleep" → sleep_log. "show my sleep" / "sleep history" → sleep_view.
- "undo" / "undo that" / "take it back" → undo.
- "brain dump:" or "dump this:" followed by text → braindump. "/braindump" alone → braindump with empty text.
- "email [person/address] that/about/saying [content]" / "send an email to [person]" → gmail_send (composing a new outbound email). Use email_assist ONLY when the user pastes or describes an email they RECEIVED and wants a reply drafted.
- "draft/compose/write an email to [person] about [topic]" → gmail_draft.
- "how many unread emails" / "check my inbox" → gmail_unread.

EXAMPLES:
{{"user": "what's on my calendar today", "response": {{"intent": "cal_view", "entities": {{"range": "today"}}}}}}
{{"user": "show me my calendar for May 10", "response": {{"intent": "cal_view", "entities": {{"range": "May 10"}}}}}}
{{"user": "what's on my schedule this week", "response": {{"intent": "cal_view", "entities": {{"range": "week"}}}}}}
{{"user": "add almond milk to the grocery list", "response": {{"intent": "shop_add", "entities": {{"item": "almond milk", "list_key": "grocery"}}}}}}
{{"user": "schedule dentist next Tuesday at 2pm", "response": {{"intent": "cal_add", "entities": {{"title": "Dentist", "start": "2026-04-21T14:00"}}}}}}
{{"user": "add lunch with Sarah next Monday at noon", "response": {{"intent": "cal_add", "entities": {{"title": "Lunch with Sarah", "start": "2026-04-20T12:00"}}}}}}
{{"user": "add daily workout at 7am", "response": {{"intent": "cal_add", "entities": {{"title": "Workout", "start": "{_today_str}T07:00", "recur": "daily"}}}}}}
{{"user": "add team standup every weekday at 9am", "response": {{"intent": "cal_add", "entities": {{"title": "Team Standup", "start": "{_today_str}T09:00", "recur": "weekdays"}}}}}}
{{"user": "I worked out this morning", "response": {{"intent": "habit_log", "entities": {{"habit_id": "workout"}}}}}}
{{"user": "remember that I'm lactose intolerant", "response": {{"intent": "memory_add", "entities": {{"category": "Me", "fact": "I am lactose intolerant"}}}}}}
{{"user": "what have I done this week", "response": {{"intent": "weekly_summary", "entities": {{}}}}}}
{{"user": "get a gift for Megan's birthday next month", "response": {{"intent": "gift_add", "entities": {{"recipient": "Megan", "idea": "", "occasion": "birthday", "date": "next month"}}}}}}
{{"user": "what is the capital of France", "response": {{"intent": "ask", "entities": {{"query": "what is the capital of France"}}}}}}
{{"user": "mark buy groceries done", "response": {{"intent": "todo_complete", "entities": {{"query": "buy groceries"}}}}}}
{{"user": "done with the laundry", "response": {{"intent": "todo_complete", "entities": {{"query": "laundry"}}}}}}
{{"user": "delete todo dentist appointment", "response": {{"intent": "todo_delete", "entities": {{"query": "dentist appointment"}}}}}}
{{"user": "got the milk", "response": {{"intent": "shop_complete", "entities": {{"item": "milk", "list_key": "grocery"}}}}}}
{{"user": "did chest and triceps for 45 min", "response": {{"intent": "workout_log", "entities": {{"description": "chest and triceps", "duration_min": 45}}}}}}
{{"user": "forget that I hate cilantro", "response": {{"intent": "memory_remove", "entities": {{"fact": "I hate cilantro"}}}}}}
{{"user": "delete today's mood entry", "response": {{"intent": "mood_delete", "entities": {{"date": ""}}}}}}
{{"user": "remove my mood log for June 9", "response": {{"intent": "mood_delete", "entities": {{"date": "2026-06-09"}}}}}}
{{"user": "find notes about dentist", "response": {{"intent": "note_search", "entities": {{"query": "dentist"}}}}}}
{{"user": "search my notes for budget", "response": {{"intent": "note_search", "entities": {{"query": "budget"}}}}}}
{{"user": "use 💪 for workout events", "response": {{"intent": "cal_emoji_set", "entities": {{"keyword": "workout", "emoji": "💪"}}}}}}
{{"user": "set the trading emoji to 📊", "response": {{"intent": "cal_emoji_set", "entities": {{"keyword": "trading", "emoji": "📊"}}}}}}
{{"user": "show my calendar emojis", "response": {{"intent": "cal_emoji_set", "entities": {{"keyword": "show", "emoji": ""}}}}}}
{{"user": "reset calendar emojis", "response": {{"intent": "cal_emoji_set", "entities": {{"keyword": "reset", "emoji": ""}}}}}}
{{"user": "move my dentist appointment to 4pm tomorrow", "response": {{"intent": "cal_update", "entities": {{"title": "Dentist", "new_start": "{_today_str}T16:00"}}}}}}
{{"user": "rename my 3pm meeting to Project Kickoff", "response": {{"intent": "cal_update", "entities": {{"title": "3pm meeting", "new_title": "Project Kickoff"}}}}}}
{{"user": "change the location of my dentist appointment to 123 Main St", "response": {{"intent": "cal_update", "entities": {{"title": "Dentist", "new_location": "123 Main St"}}}}}}
{{"user": "email you@example.com that this is a test from Alfred", "response": {{"intent": "gmail_send", "entities": {{"to": "you@example.com", "subject": "Test from Alfred", "body": "this is a test from Alfred"}}}}}}
{{"user": "email John that I'll be 10 minutes late", "response": {{"intent": "gmail_send", "entities": {{"to": "John", "subject": "Running Late", "body": "I'll be 10 minutes late"}}}}}}
{{"user": "send an email to boss@work.com saying I'm out sick today", "response": {{"intent": "gmail_send", "entities": {{"to": "boss@work.com", "subject": "Out Sick Today", "body": "I'm out sick today"}}}}}}
{{"user": "draft an email to my landlord about the broken heater", "response": {{"intent": "gmail_draft", "entities": {{"to": "landlord", "subject": "Broken Heater", "body": "broken heater needs fixing"}}}}}}
{{"user": "how many unread emails do I have", "response": {{"intent": "gmail_unread", "entities": {{}}}}}}
{{"user": "check my inbox", "response": {{"intent": "gmail_unread", "entities": {{}}}}}}

Return only the JSON for the user's message — no wrapper keys like "response"."""


# Build with defaults at module load — works even before bot.py calls refresh
_gpt_system_prompt = _build_gpt_system(MEMORY_CATEGORIES)


def refresh_intent_prompt(memory_categories: list, plugin_gpt_block: str = "") -> None:
    """
    Rebuild the GPT classification prompt with the live memory category list
    and any plugin intent definitions.

    Call this in bot.py at startup after loading alfred_memory.json:

        from core.data import get_active_categories, load_memory
        from core.intent import refresh_intent_prompt
        refresh_intent_prompt(get_active_categories(load_memory()))

    Also call it after a buyer adds or removes a custom category so the
    intent classifier knows about it immediately.

    Args:
        memory_categories: The current active list of memory categories.
        plugin_gpt_block:  Extra intent definitions from plugins, appended
                           to the core GPT prompt.
    """
    global _gpt_system_prompt
    base = _build_gpt_system(memory_categories)
    if plugin_gpt_block:
        base += "\n" + plugin_gpt_block
    _gpt_system_prompt = base
    logger.debug(f"intent: GPT prompt rebuilt with categories: {memory_categories}"
                 f"{' + plugin intents' if plugin_gpt_block else ''}")


def add_plugin_keyword_rules(rules: list) -> None:
    """
    Append plugin keyword rules to the Layer 1 rule set.

    Called from bot.py at startup after plugins are discovered.
    Each rule is a (compiled_regex, handler_fn) tuple — same format as
    _build_keyword_rules().
    """
    global _KEYWORD_RULES
    _KEYWORD_RULES = _KEYWORD_RULES + rules
    logger.info(f"intent: {len(rules)} plugin keyword rules added (total: {len(_KEYWORD_RULES)})")


def register_plugin_intents(intents: set) -> None:
    """
    Add plugin intent strings to the known-intents set.

    This prevents GPT-classified plugin intents from being demoted to 'ask'.
    """
    _ALL_INTENTS.update(intents)
    logger.info(f"intent: {len(intents)} plugin intents registered")


async def _gpt_classify(text: str) -> "IntentResult | None":
    """
    Layer 2: ask GPT to classify and extract entities.
    Returns IntentResult on success, None on any error.
    """
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=OPENAI_API_KEY)

    raw = ""
    try:
        # Compute the REAL current date at request time. The static system prompt
        # bakes in the date from when it was last built (at bot startup), which goes
        # stale on long-running deploys — making relative dates like "tomorrow"
        # resolve off the boot date. This per-request override keeps them correct.
        import datetime as _dt
        from zoneinfo import ZoneInfo as _ZI
        from core.config import TIMEZONE as _TZ
        _today_live = _dt.datetime.now(_ZI(_TZ)).strftime("%Y-%m-%d (%A)")

        resp = await client.chat.completions.create(
            model=GPT_CHAT_MODEL,
            messages=[
                {"role": "system", "content": _gpt_system_prompt},
                {"role": "system", "content": (
                    f"CURRENT DATE OVERRIDE: Today is {_today_live}. This is "
                    f"authoritative and supersedes any date mentioned earlier in "
                    f"the prompt or its examples. Resolve ALL relative dates and "
                    f"times (today, tonight, tomorrow, next Monday, in 3 days, etc.) "
                    f"from this date."
                )},
                {"role": "user",   "content": text},
            ],
            temperature=0,
            max_tokens=400,
            response_format={"type": "json_object"},
        )
        raw      = resp.choices[0].message.content.strip()
        data     = json.loads(raw)
        intent   = data.get("intent",   UNKNOWN)
        entities = data.get("entities", {})

        # Validate intent is known; degrade gracefully if GPT invents one
        if intent not in _ALL_INTENTS:
            logger.warning(
                f"intent: GPT returned unrecognised intent '{intent}' "
                f"for text {repr(text)[:80]} — demoting to 'ask'"
            )
            intent   = ASK
            entities = {"query": text}

        return IntentResult(
            intent=intent,
            entities=entities if isinstance(entities, dict) else {},
            confidence="gpt",
            raw=text,
        )

    except json.JSONDecodeError as e:
        logger.error(f"intent: GPT JSON parse error: {e} | raw={raw!r}")
        return None
    except Exception as e:
        logger.error(f"intent: GPT classify error: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC INTERFACE
# ═══════════════════════════════════════════════════════════════════════════════

async def classify(text: str) -> IntentResult:
    """
    Classify a free-form text message into an intent with extracted entities.

    Tries Layer 1 (keyword bypass) first.
    If no rule fires, falls through to Layer 2 (GPT).
    If both fail, returns IntentResult(ASK, {"query": text}) so the message
    is always handled — never silently dropped.

    This function is safe: it never raises.

    Args:
        text: The raw text from the user (already stripped of any
              command prefix like /start). Voice messages should be
              transcribed before calling classify().

    Returns:
        IntentResult with .intent, .entities, .confidence, .raw set.
    """
    if not text or not text.strip():
        return IntentResult(intent=UNKNOWN, entities={}, confidence="fallback", raw=text or "")

    # ── Layer 1: Keyword bypass ────────────────────────────────────────────
    result = _keyword_classify(text)
    if result is not None:
        logger.debug(f"intent: keyword hit '{result.intent}' for text {repr(text)[:60]}")
        return result

    # ── Layer 2: GPT classification ───────────────────────────────────────
    result = await _gpt_classify(text)
    if result is not None:
        logger.debug(f"intent: GPT classified '{result.intent}' for text {repr(text)[:60]}")
        return result

    # ── Fallback: treat as a general question ────────────────────────────
    logger.warning(f"intent: both layers failed for text {repr(text)[:60]} — fallback to ASK")
    return IntentResult(
        intent=ASK,
        entities={"query": text},
        confidence="fallback",
        raw=text,
    )

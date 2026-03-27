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

# Calendar
CAL_VIEW        = "cal_view"
CAL_ADD         = "cal_add"
CAL_DELETE      = "cal_delete"
CAL_UPDATE      = "cal_update"

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
MOOD_LOG  = "mood_log"
MOOD_VIEW = "mood_view"

# Link / read-later
LINK_SAVE      = "link_save"
LINK_VIEW      = "link_view"
LINK_SEARCH    = "link_search"
LINK_MARK_READ = "link_mark_read"
LINK_SNOOZE    = "link_snooze"

# Export
EXPORT_DATA = "export_data"

# Catch-all
ASK             = "ask"
UNKNOWN         = "unknown"

# All known intents (used for GPT validation)
_ALL_INTENTS = {
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
    _list_names = "|".join(re.escape(k) for k in SHOPPING_LISTS) + "|shopping"
    p = _r(rf"^add\s+(.+?)\s+to\s+(?:the\s+)?(?:{_list_names})\s*(?:list)?$")

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
    # "add X to my todo list" / "add X to tasks"
    p = _r(r"^add\s+(.+?)\s+to\s+(?:my\s+)?(?:todo|task)s?(?:\s+list)?$")

    def _todo_add(m, t):
        return IntentResult(
            intent=TODO_ADD,
            entities={"text": m.group(1).strip()},
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
           r"|(?:show|check)\s+(?:my\s+)?(?:calendar|schedule)")

    def _cal_view(m, t):
        tl = t.lower()
        if "week" in tl:
            period = "week"
        elif "tomorrow" in tl:
            period = "tomorrow"
        elif "today" in tl or "today's" in tl:
            period = "today"
        else:
            period = "today"
        return IntentResult(
            intent=CAL_VIEW,
            entities={"period": period},
            confidence="keyword",
            raw=t,
        )

    rules.append((p, _cal_view))

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

cal_view        Show calendar events.
                Entities: period ("today"|"tomorrow"|"week"|"upcoming"), days (int, optional for "upcoming")

cal_add         Create a calendar event.
                Entities: title (required), date (required), time (optional), duration_minutes (optional int),
                          location (optional), recur (optional: "daily"|"weekdays"|"weekly"|"monthly"|"yearly"),
                          all_day (bool, default false), attendees (list of emails, optional)

cal_delete      Delete / cancel a calendar event.
                Entities: query

cal_update      Modify a calendar event.
                Entities: query, changes (dict with any of: title, date, time, location, duration_minutes)

habit_log       Log a habit as completed today.
                Entities: habit_id (one of: {_HABIT_IDS})

habit_view      Show today's habit progress.
                Entities: {{}}

reminder_add    Add a reminder or recurring reminder.
                Entities: text (required), due (date/time str or null), recur ("daily"|"weekdays"|"weekly"|"monthly"|null)

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

reply_assist    Draft reply suggestions for a text message screenshot or description.
                Entities: context (str, optional description the user typed before sending photo)

email_assist    Draft a reply to an email (screenshot or pasted text).
                Entities: email_text (str, optional), context (str, optional)

reply_style_add Save a writing style example to the reply style library.
                Entities: example (str)

mood_log        Log the user's current mood/emotional state (1-10 rating).
                Entities: rating (int 1-10), note (str optional)

mood_view       Show the user's recent mood history or trends.
                Entities: days (int, default 7)

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
- "add X to my list" without a specific list → shop_add with list_key "grocery".
- Dates like "tomorrow", "next Monday", "in 2 days", "this Friday" are valid due values — pass them as-is.

EXAMPLES:
{{"user": "what's on my calendar today", "response": {{"intent": "cal_view", "entities": {{"period": "today"}}}}}}
{{"user": "add almond milk to the grocery list", "response": {{"intent": "shop_add", "entities": {{"item": "almond milk", "list_key": "grocery"}}}}}}
{{"user": "schedule dentist next Tuesday at 2pm", "response": {{"intent": "cal_add", "entities": {{"title": "Dentist", "date": "next Tuesday", "time": "2:00 PM"}}}}}}
{{"user": "I worked out this morning", "response": {{"intent": "habit_log", "entities": {{"habit_id": "workout"}}}}}}
{{"user": "remember that I'm lactose intolerant", "response": {{"intent": "memory_add", "entities": {{"category": "Me", "fact": "I am lactose intolerant"}}}}}}
{{"user": "what have I done this week", "response": {{"intent": "weekly_summary", "entities": {{}}}}}}
{{"user": "get a gift for Megan's birthday next month", "response": {{"intent": "gift_add", "entities": {{"recipient": "Megan", "idea": "", "occasion": "birthday", "date": "next month"}}}}}}
{{"user": "what is the capital of France", "response": {{"intent": "ask", "entities": {{"query": "what is the capital of France"}}}}}}

Return only the JSON for the user's message — no wrapper keys like "response"."""


# Build with defaults at module load — works even before bot.py calls refresh
_gpt_system_prompt = _build_gpt_system(MEMORY_CATEGORIES)


def refresh_intent_prompt(memory_categories: list) -> None:
    """
    Rebuild the GPT classification prompt with the live memory category list.

    Call this in bot.py at startup after loading alfred_memory.json:

        from core.data import get_active_categories, load_memory
        from core.intent import refresh_intent_prompt
        refresh_intent_prompt(get_active_categories(load_memory()))

    Also call it after a buyer adds or removes a custom category so the
    intent classifier knows about it immediately.
    """
    global _gpt_system_prompt
    _gpt_system_prompt = _build_gpt_system(memory_categories)
    logger.debug(f"intent: GPT prompt rebuilt with categories: {memory_categories}")


async def _gpt_classify(text: str) -> "IntentResult | None":
    """
    Layer 2: ask GPT to classify and extract entities.
    Returns IntentResult on success, None on any error.
    """
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=OPENAI_API_KEY)

    raw = ""
    try:
        resp = await client.chat.completions.create(
            model=GPT_CHAT_MODEL,
            messages=[
                {"role": "system", "content": _gpt_system_prompt},
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

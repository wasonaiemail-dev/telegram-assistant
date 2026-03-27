"""
alfred/core/data.py
===================
All data persistence for Alfred: loading, saving, migrating, and querying
user data across both Railway (local JSON) and Google Tasks.

═══════════════════════════════════════════════════════════════════════════════
PRIMARY DATA STORE SCHEMA  (userdata.json)
═══════════════════════════════════════════════════════════════════════════════
The top-level keys and their shapes:

  todos           list of todo dicts
                    {id, text, priority, done, added, completed_at, recur, recur_next}

  shopping_lists  dict of N lists (keys match SHOPPING_LISTS in config.py)
                    each item: {text, done, added}

  notes           list of note dicts
                    {id, text, added, last_surfaced}

  reminders       list of reminder dicts
                    {id, text, time, done, recur, recur_next}

  meals           list of meal strings

  workouts        list of workout dicts
                    {description, date}

  gifts           dict keyed by person name
                    {person: [{idea, occasion, date, done}]}

  habits          dict — reserved for future per-habit settings

  habit_log       list of log entries
                    {habit, date, note}

  sleep_log       list of sleep entries
                    {hours, quality, date, note}

  mood_log        list of mood entries
                    {mood, note, date}

  undo_stack      list of up to 5 undo snapshots

═══════════════════════════════════════════════════════════════════════════════
SEPARATE FILES (not in userdata.json)
═══════════════════════════════════════════════════════════════════════════════
  alfred_memory.json   Long-term facts Alfred remembers about you
                         {
                           "_categories":        [str, ...],   ← live active list
                           "_custom_categories": [str, ...],   ← buyer-added extras
                           category:             [fact_str, ...]
                         }
                         Default categories: Me, Family, Work, Preferences, Ongoing,
                           Health, Finance, Goals, Social, Travel
                         Buyer can add custom categories via /setup or /memory addcat

  ask_history.json     Active /ask conversation thread
                         {messages: [...], last_updated: ISO timestamp,
                          topic_summary: str}

  contacts.json        {name: [fact_string, ...]}

  conversation.json    {user_id_str: [message_dict, ...]}

═══════════════════════════════════════════════════════════════════════════════
MIGRATIONS
═══════════════════════════════════════════════════════════════════════════════
  load_data() automatically migrates old structures:
    v1 → v2: flat 'shopping' list → 'shopping_lists' dict
    v2 → v3: todos gain recur / recur_next fields
    v3 → v4: reminders gain recur / recur_next fields
    v4 → v5: gifts change from {name: [str]} → {name: [{idea,occasion,date,done}]}
    v4 → v5: notes gain last_surfaced field

  When adding a new schema key, add a .setdefault() line in the migration
  block of load_data() so old userdata.json files are safely upgraded.
"""

import os
import json
import copy
import logging
import datetime

from core.config import (
    DATA_FILE, TOKEN_FILE, AUTH_STATE_FILE, LOG_FILE,
    CONTACTS_FILE, CONVO_FILE, MEMORY_FILE, ASK_HISTORY_FILE,
    TIMEZONE, MEMORY_CATEGORIES, MEMORY_ALWAYS_INJECT,
    MEMORY_CATEGORY_KEYWORDS, MEMORY_MAX_FACTS_PER_CATEGORY,
    ASK_CONTEXT_HOURS,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# PRIMARY DATA STORE
# ═══════════════════════════════════════════════════════════════════════════════

def load_data():
    """
    Load userdata.json from the persistent volume.

    Runs all pending migrations automatically so older installs are
    transparently upgraded to the current schema on the next load.

    Always returns a valid, fully-keyed dict even if the file does not exist.
    """
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to load {DATA_FILE}: {e} — starting fresh")
            return _empty_data()

        # ── MIGRATION 1: flat shopping list → shopping_lists dict ──────────
        if "shopping_lists" not in data:
            old = data.pop("shopping", [])
            data["shopping_lists"] = {
                "grocery":   old if old else [],
                "household": [],
                "baby":      [],
                "wishlist":  [],
            }
            _save_raw(data)
            logger.info("Migration 1: flat shopping → shopping_lists")

        # ── ENSURE ALL CONFIGURED SHOPPING SUBLISTS EXIST ──────────────────
        from core.config import SHOPPING_LISTS
        for k in SHOPPING_LISTS:
            data["shopping_lists"].setdefault(k, [])

        # ── MIGRATION 2: todos gain recur / recur_next / completed_at ───────
        for todo in data.get("todos", []):
            todo.setdefault("recur",        "none")
            todo.setdefault("recur_next",   None)
            todo.setdefault("completed_at", None)
            todo.setdefault("id",           _next_id(data.get("todos", [])))

        # ── MIGRATION 3: reminders gain recur / recur_next ─────────────────
        for rem in data.get("reminders", []):
            rem.setdefault("recur",      "none")
            rem.setdefault("recur_next", None)
            rem.setdefault("id",         _next_id(data.get("reminders", [])))

        # ── MIGRATION 4: notes gain last_surfaced ──────────────────────────
        for note in data.get("notes", []):
            note.setdefault("last_surfaced", None)

        # ── MIGRATION 5: gifts {name: [str]} → {name: [{idea,...}]} ────────
        for person, items in data.get("gifts", {}).items():
            if items and isinstance(items[0], str):
                data["gifts"][person] = [
                    {"idea": idea, "occasion": "", "date": "", "done": False}
                    for idea in items
                ]

        # ── ADD ANY MISSING TOP-LEVEL KEYS (safe defaults) ─────────────────
        data.setdefault("todos",          [])
        data.setdefault("notes",          [])
        data.setdefault("reminders",      [])
        data.setdefault("meals",          [])
        data.setdefault("workouts",       [])
        data.setdefault("gifts",          {})
        data.setdefault("habits",         {})
        data.setdefault("habit_log",      [])
        data.setdefault("sleep_log",      [])
        data.setdefault("mood_log",       [])
        data.setdefault("undo_stack",     [])

        return data

    return _empty_data()


def save_data(data):
    """
    Atomically save userdata.json.
    Writes to a .tmp file first, then os.replace() to prevent corrupt JSON
    if the process is killed mid-write.
    """
    tmp = DATA_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, DATA_FILE)
    except IOError as e:
        logger.error(f"Failed to save data: {e}")
        raise


def _save_raw(data):
    """Used during migration — no atomic write needed."""
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _empty_data():
    """Return a fully-keyed empty data structure for new users."""
    from core.config import SHOPPING_LISTS
    shopping = {k: [] for k in SHOPPING_LISTS}
    return {
        "todos":          [],
        "shopping_lists": shopping,
        "notes":          [],
        "reminders":      [],
        "meals":          [],
        "workouts":       [],
        "gifts":          {},
        "habits":         {},
        "habit_log":      [],
        "sleep_log":      [],
        "mood_log":       [],
        "undo_stack":     [],
    }


def _next_id(item_list):
    """Generate a simple integer ID one higher than the current max."""
    if not item_list:
        return 1
    existing = [i.get("id", 0) for i in item_list if isinstance(i, dict)]
    return max(existing, default=0) + 1


# ═══════════════════════════════════════════════════════════════════════════════
# UNDO SUPPORT
# ═══════════════════════════════════════════════════════════════════════════════

def push_undo(data, action_label, snapshot_keys):
    """
    Save a snapshot of specific keys before a destructive action.

    Args:
        data:           current data dict (will be mutated)
        action_label:   human-readable label, e.g. "deleted todo 2"
        snapshot_keys:  list of top-level keys to snapshot, e.g. ["todos"]

    Only the last 5 actions are kept to limit memory use.
    """
    snapshot = {k: copy.deepcopy(data[k]) for k in snapshot_keys if k in data}
    data.setdefault("undo_stack", []).append({
        "label":    action_label,
        "snapshot": snapshot,
        "keys":     snapshot_keys,
    })
    data["undo_stack"] = data["undo_stack"][-5:]


def pop_undo(data):
    """
    Restore the most recent undo snapshot.

    Returns:
        The action label string if successful, None if nothing to undo.
    """
    stack = data.get("undo_stack", [])
    if not stack:
        return None
    entry = stack.pop()
    for key, value in entry["snapshot"].items():
        data[key] = value
    return entry["label"]


# ═══════════════════════════════════════════════════════════════════════════════
# CONTACTS
# ═══════════════════════════════════════════════════════════════════════════════

def load_contacts():
    """
    Load contacts.json.

    Returns a dict keyed by name with a list of fact strings.
    Example: {"Sarah": ["birthday April 3rd", "prefers texts over calls"]}
    """
    if os.path.exists(CONTACTS_FILE):
        try:
            with open(CONTACTS_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def save_contacts(contacts):
    with open(CONTACTS_FILE, "w") as f:
        json.dump(contacts, f, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# CONVERSATION HISTORY
# ═══════════════════════════════════════════════════════════════════════════════

def load_conversation():
    """
    Load persisted conversation history.

    Returns a dict keyed by user_id (as string) with a list of message dicts.
    """
    if os.path.exists(CONVO_FILE):
        try:
            with open(CONVO_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def save_conversation(history):
    with open(CONVO_FILE, "w") as f:
        json.dump(history, f, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# ALFRED MEMORY
# Long-term facts Alfred remembers about you. Stored in alfred_memory.json.
#
# MEMORY FILE STRUCTURE
# ─────────────────────
#   {
#     "_categories":        ["Me", "Family", ...],     ← live active list
#     "_custom_categories": ["MyCustom", ...],          ← buyer-added extras
#     "Me":         ["fact1", "fact2"],
#     "Family":     [...],
#     "MyCustom":   [...],
#     ...
#   }
#
# _categories is authoritative. config.MEMORY_CATEGORIES is the default
# fallback for new installs before /setup has run.
#
# RELEVANT-CATEGORY INJECTION
# ────────────────────────────
# Not all categories are injected into every GPT call — only:
#   - MEMORY_ALWAYS_INJECT (Me + Preferences) — always
#   - Categories whose keywords match the current message — on demand
# This keeps per-call token cost to ~100–300 tokens instead of ~12,000 worst-case.
# ═══════════════════════════════════════════════════════════════════════════════

def load_memory() -> dict:
    """
    Load Alfred's long-term memory from alfred_memory.json.

    Returns a dict with all active categories guaranteed to be present.
    The live category list is read from the '_categories' key in the file;
    falls back to config.MEMORY_CATEGORIES for new/pre-setup installs.
    """
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r") as f:
                mem = json.load(f)
        except (json.JSONDecodeError, IOError):
            mem = {}
    else:
        mem = {}

    # Determine the live category list
    active = mem.get("_categories", list(MEMORY_CATEGORIES))

    # Ensure every active category key exists (handles new categories being added)
    for cat in active:
        mem.setdefault(cat, [])

    # Ensure the _categories key is always set (handles old installs)
    if "_categories" not in mem:
        mem["_categories"] = list(MEMORY_CATEGORIES)
    if "_custom_categories" not in mem:
        mem["_custom_categories"] = []

    return mem


def save_memory(mem: dict) -> None:
    """Atomically persist Alfred's memory to disk."""
    tmp = MEMORY_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(mem, f, indent=2)
        os.replace(tmp, MEMORY_FILE)
    except IOError as e:
        logger.error(f"Failed to save memory: {e}")
        raise


def get_active_categories(mem: dict = None) -> list:
    """
    Return the current live list of memory categories.

    Uses the '_categories' key from the memory file if available;
    falls back to config.MEMORY_CATEGORIES for fresh installs.
    """
    if mem is None:
        mem = load_memory()
    return mem.get("_categories", list(MEMORY_CATEGORIES))


def add_custom_category(name: str) -> tuple:
    """
    Add a new custom memory category.

    Args:
        name: Category name (will be title-cased for consistency).

    Returns:
        (True, None)       — success
        (False, "reason")  — already exists or invalid
    """
    name = name.strip().title()
    if not name:
        return False, "Category name cannot be empty."

    mem = load_memory()
    active = mem.get("_categories", list(MEMORY_CATEGORIES))

    if name in active:
        return False, f"Category '{name}' already exists."
    if len(active) >= 20:
        return False, "Maximum of 20 categories reached."

    active.append(name)
    mem["_categories"] = active
    mem.setdefault("_custom_categories", [])
    mem["_custom_categories"].append(name)
    mem[name] = []
    save_memory(mem)
    return True, None


def remove_custom_category(name: str) -> tuple:
    """
    Remove a custom category and all its facts.
    Cannot remove built-in categories (config.MEMORY_CATEGORIES).

    Returns:
        (True, None)       — success
        (False, "reason")  — not found, or is a built-in category
    """
    mem = load_memory()
    custom = mem.get("_custom_categories", [])

    if name not in custom:
        if name in MEMORY_CATEGORIES:
            return False, f"'{name}' is a built-in category and cannot be removed."
        return False, f"Category '{name}' not found."

    active = mem.get("_categories", list(MEMORY_CATEGORIES))
    active = [c for c in active if c != name]
    custom = [c for c in custom if c != name]
    mem["_categories"]        = active
    mem["_custom_categories"] = custom
    mem.pop(name, None)
    save_memory(mem)
    return True, None


def add_memory_fact(category: str, fact: str) -> tuple:
    """
    Add a fact to the given category.

    Works with both built-in and custom categories.

    Returns:
        (True, None)       — success
        (False, "reason")  — failure with human-readable reason
    """
    mem    = load_memory()
    active = get_active_categories(mem)

    if category not in active:
        return False, (
            f"Unknown category '{category}'. "
            f"Active categories: {', '.join(active)}"
        )

    facts = mem[category]

    # Deduplicate (case-insensitive)
    if any(f.lower() == fact.lower() for f in facts):
        return False, "I already know that."

    if len(facts) >= MEMORY_MAX_FACTS_PER_CATEGORY:
        return False, (
            f"The {category} category is full ({MEMORY_MAX_FACTS_PER_CATEGORY} facts). "
            "Remove one first with /memory remove."
        )

    facts.append(fact)
    save_memory(mem)
    return True, None


def remove_memory_fact(category: str, index_1based: int) -> tuple:
    """
    Remove a fact by its 1-based index within a category.

    Returns:
        (removed_fact_string, None)  — success
        (None, "reason")             — failure
    """
    mem    = load_memory()
    active = get_active_categories(mem)

    if category not in active:
        return None, f"Unknown category '{category}'."

    facts = mem[category]
    idx   = index_1based - 1

    if idx < 0 or idx >= len(facts):
        return None, f"No fact #{index_1based} in {category}."

    removed = facts.pop(idx)
    save_memory(mem)
    return removed, None


def get_relevant_categories(text: str, mem: dict = None) -> list:
    """
    Return which memory categories are relevant for injecting into a GPT call.

    Always includes MEMORY_ALWAYS_INJECT (Me + Preferences).
    Adds other categories if any of their keywords appear in the message text.

    Args:
        text: The user's message (used for keyword matching).
        mem:  Pre-loaded memory dict, or None to load.

    Returns:
        Ordered list of category names to inject (only non-empty ones matter
        to the caller — empty categories produce no output regardless).
    """
    if mem is None:
        mem = load_memory()

    active   = get_active_categories(mem)
    tl       = (text or "").lower()
    relevant = list(MEMORY_ALWAYS_INJECT)  # start with always-inject

    for cat in active:
        if cat in relevant:
            continue  # already included
        keywords = MEMORY_CATEGORY_KEYWORDS.get(cat, [])
        if any(kw in tl for kw in keywords):
            relevant.append(cat)

    # Preserve the order they appear in the active list
    ordered = [c for c in active if c in relevant]
    return ordered


def get_memory_context(text: str = None, mem: dict = None, categories: list = None) -> str:
    """
    Build the memory block string injected into a GPT system prompt.

    Args:
        text:       User's message. If provided, only relevant categories are
                    injected (keyword-matched). Pass None to inject all non-empty
                    categories (used for briefing, weekly summary, etc.).
        mem:        Pre-loaded memory dict, or None to load from disk.
        categories: Explicit category list override. If provided, ignores text
                    and only injects these categories.

    Returns:
        Formatted string like:
            [Me]
              - Name is Tyler, lives in Salt Lake City
            [Health]
              - Lactose intolerant
        Returns empty string if no relevant facts exist.
    """
    if mem is None:
        mem = load_memory()

    if categories is not None:
        cats_to_use = categories
    elif text is not None:
        cats_to_use = get_relevant_categories(text, mem)
    else:
        cats_to_use = get_active_categories(mem)  # inject all (no text filter)

    lines = []
    for cat in cats_to_use:
        facts = mem.get(cat, [])
        if facts:
            lines.append(f"[{cat}]")
            for fact in facts:
                lines.append(f"  - {fact}")

    return "\n".join(lines) if lines else ""


# ═══════════════════════════════════════════════════════════════════════════════
# /ASK HISTORY  (8-hour persistent conversation thread)
# ═══════════════════════════════════════════════════════════════════════════════

def load_ask_history():
    """
    Load the active /ask conversation thread.

    Returns a dict:
        {
            "messages":      [...],          # list of {role, content}
            "last_updated":  "ISO string",   # when last message was added
            "topic_summary": "str",          # GPT-generated 1-line topic summary
        }

    If the thread is older than ASK_CONTEXT_HOURS, it is treated as expired
    and an empty thread is returned (the caller should start fresh).
    """
    if not os.path.exists(ASK_HISTORY_FILE):
        return _empty_ask_history()

    try:
        with open(ASK_HISTORY_FILE, "r") as f:
            hist = json.load(f)
    except (json.JSONDecodeError, IOError):
        return _empty_ask_history()

    # Check expiry
    last = hist.get("last_updated")
    if last:
        try:
            import pytz
            tz = pytz.timezone(TIMEZONE)
            last_dt = datetime.datetime.fromisoformat(last)
            now = datetime.datetime.now(tz)
            # Make last_dt timezone-aware if it isn't already
            if last_dt.tzinfo is None:
                last_dt = tz.localize(last_dt)
            age_hours = (now - last_dt).total_seconds() / 3600
            if age_hours >= ASK_CONTEXT_HOURS:
                logger.info(f"Ask thread expired ({age_hours:.1f}h old). Starting fresh.")
                return _empty_ask_history()
        except Exception as e:
            logger.warning(f"Could not parse ask_history timestamp: {e}")

    hist.setdefault("messages",      [])
    hist.setdefault("topic_summary", "")
    return hist


def save_ask_history(hist):
    """Persist the /ask thread to disk with an updated timestamp."""
    import pytz
    tz = pytz.timezone(TIMEZONE)
    hist["last_updated"] = datetime.datetime.now(tz).isoformat()
    with open(ASK_HISTORY_FILE, "w") as f:
        json.dump(hist, f, indent=2)


def clear_ask_history():
    """Wipe the /ask thread (topic shift or manual /reset)."""
    empty = _empty_ask_history()
    with open(ASK_HISTORY_FILE, "w") as f:
        json.dump(empty, f, indent=2)
    return empty


def _empty_ask_history():
    return {
        "messages":      [],
        "last_updated":  None,
        "topic_summary": "",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# SIMPLE IN-MEMORY CACHE
# Used for weather and external API calls to avoid hammering endpoints.
# ═══════════════════════════════════════════════════════════════════════════════

_cache = {}


def cache_get(key, max_age_seconds=300):
    """Return cached value if it exists and is not stale. Otherwise None."""
    import time
    entry = _cache.get(key)
    if entry and (time.time() - entry["ts"]) < max_age_seconds:
        return entry["value"]
    return None


def cache_set(key, value):
    """Store a value in the in-memory cache with a timestamp."""
    import time
    _cache[key] = {"value": value, "ts": time.time()}


def cache_clear(key=None):
    """Clear one key or the entire cache."""
    if key:
        _cache.pop(key, None)
    else:
        _cache.clear()


# ═══════════════════════════════════════════════════════════════════════════════
# AUDIT LOG
# ═══════════════════════════════════════════════════════════════════════════════

def audit_log(event):
    """Append a timestamped event to audit.log. Never raises."""
    import pytz
    try:
        tz = pytz.timezone(TIMEZONE)
        ts = datetime.datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_FILE, "a") as f:
            f.write(f"{ts} | {event}\n")
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# "WHAT DID I DO THIS WEEK" AGGREGATION HELPER
# Pulls together all logged activity for the current week (Mon–Sun).
# ═══════════════════════════════════════════════════════════════════════════════

def get_week_summary_data(data=None):
    """
    Aggregate all activity logged in the current calendar week (Mon–Sun).

    Args:
        data: pre-loaded userdata dict, or None to load from disk.

    Returns a dict with keys:
        completed_todos     list of todo text strings marked done this week
        completed_habits    dict {habit_id: count}
        sleep_entries       list of sleep dicts
        mood_entries        list of mood dicts
        workout_entries     list of workout dicts
        week_start          date string "YYYY-MM-DD" (Monday)
        week_end            date string "YYYY-MM-DD" (Sunday)
    """
    import pytz
    if data is None:
        data = load_data()

    tz = pytz.timezone(TIMEZONE)
    today = datetime.datetime.now(tz).date()
    # Monday = 0, Sunday = 6
    week_start = today - datetime.timedelta(days=today.weekday())
    week_end   = week_start + datetime.timedelta(days=6)

    def in_week(date_str):
        if not date_str:
            return False
        try:
            d = datetime.date.fromisoformat(date_str[:10])
            return week_start <= d <= week_end
        except (ValueError, TypeError):
            return False

    # Completed todos — use completed_at (when it was done), not added (when created)
    completed_todos = [
        t["text"] for t in data.get("todos", [])
        if t.get("done") and in_week(t.get("completed_at") or t.get("added"))
    ]

    # Habit log
    completed_habits: dict = {}
    for entry in data.get("habit_log", []):
        if in_week(entry.get("date")):
            h = entry.get("habit", "")
            completed_habits[h] = completed_habits.get(h, 0) + 1

    # Sleep
    sleep_entries = [
        s for s in data.get("sleep_log", []) if in_week(s.get("date"))
    ]

    # Mood
    mood_entries = [
        m for m in data.get("mood_log", []) if in_week(m.get("date"))
    ]

    # Workouts
    workout_entries = [
        w for w in data.get("workouts", []) if in_week(w.get("date"))
    ]

    return {
        "completed_todos":  completed_todos,
        "completed_habits": completed_habits,
        "sleep_entries":    sleep_entries,
        "mood_entries":     mood_entries,
        "workout_entries":  workout_entries,
        "week_start":       week_start.isoformat(),
        "week_end":         week_end.isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# RECURRING TODO / REMINDER HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def compute_next_recur_date(recur, from_date=None):
    """
    Compute the next due date for a recurring item.

    Args:
        recur:     one of "daily", "weekdays", "weekly", "monthly", "none"
        from_date: datetime.date to compute from (default: today)

    Returns:
        ISO date string "YYYY-MM-DD", or None if recur == "none".
    """
    import pytz
    if recur == "none" or not recur:
        return None

    tz = pytz.timezone(TIMEZONE)
    base = from_date or datetime.datetime.now(tz).date()

    if recur == "daily":
        next_dt = base + datetime.timedelta(days=1)

    elif recur == "weekdays":
        next_dt = base + datetime.timedelta(days=1)
        # Skip past Saturday and Sunday
        while next_dt.weekday() >= 5:
            next_dt += datetime.timedelta(days=1)

    elif recur == "weekly":
        next_dt = base + datetime.timedelta(weeks=1)

    elif recur == "monthly":
        # Same day next month; clamp to end-of-month on short months
        month = base.month + 1 if base.month < 12 else 1
        year  = base.year if base.month < 12 else base.year + 1
        import calendar
        last_day = calendar.monthrange(year, month)[1]
        day = min(base.day, last_day)
        next_dt = base.replace(year=year, month=month, day=day)

    else:
        return None

    return next_dt.isoformat()


def advance_recurring_items(data):
    """
    Called daily (e.g., as part of the morning briefing job) to reset
    completed recurring todos and reminders whose recur_next date has arrived.

    Mutates `data` in place. Caller must call save_data(data) afterward.

    Returns:
        int — number of items reset
    """
    import pytz
    tz = pytz.timezone(TIMEZONE)
    today = datetime.datetime.now(tz).date().isoformat()
    reset_count = 0

    for collection_key in ("todos", "reminders"):
        for item in data.get(collection_key, []):
            if (
                item.get("done")
                and item.get("recur", "none") != "none"
                and item.get("recur_next")
                and item["recur_next"] <= today
            ):
                item["done"]         = False
                item["completed_at"] = None   # reset for the new cycle
                item["recur_next"]   = compute_next_recur_date(
                    item["recur"],
                    from_date=datetime.date.fromisoformat(item["recur_next"]),
                )
                reset_count += 1

    return reset_count


# ═══════════════════════════════════════════════════════════════════════════════
# JOURNAL
# Stored in journal.json as {date_iso: {entries: [...], saved_at: str}}
# Each entry: {type: "prompted"|"freeform"|"voice", content: str|dict,
#              timestamp: str}
# "prompted" content is a dict {question: answer, ...}
# ═══════════════════════════════════════════════════════════════════════════════

def load_journal() -> dict:
    from core.config import JOURNAL_FILE
    if os.path.exists(JOURNAL_FILE):
        try:
            with open(JOURNAL_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def save_journal(journal: dict) -> None:
    from core.config import JOURNAL_FILE
    tmp = JOURNAL_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(journal, f, indent=2)
    os.replace(tmp, JOURNAL_FILE)


def add_journal_entry(date_iso: str, entry: dict) -> None:
    """Append an entry to a day's journal. Creates the day if missing."""
    journal = load_journal()
    day = journal.setdefault(date_iso, {"entries": [], "saved_at": date_iso})
    day["entries"].append(entry)
    import datetime as _dt
    day["saved_at"] = _dt.datetime.utcnow().isoformat()
    save_journal(journal)


def get_journal_day(date_iso: str) -> dict | None:
    """Return the journal dict for a given date, or None."""
    return load_journal().get(date_iso)


# ═══════════════════════════════════════════════════════════════════════════════
# WORKOUT PROGRAM
# Stored in workout_program.json.  The workout log lives in workout_log.xlsx.
# Schema:
#   {goal, days_per_week, equipment, preferences, progressive_overload,
#    program: {day_label: [{exercise, sets, reps, weight_lb}]},
#    templates: {name: [{exercise, sets, reps, weight_lb}]},
#    pr_log: {exercise: {weight_lb, reps, date}},
#    body_stats: [{date, weight_lb, measurements: {}}],
#    streak: int, last_workout_date: str|null}
# ═══════════════════════════════════════════════════════════════════════════════

def load_workout() -> dict:
    from core.config import WORKOUT_FILE
    if os.path.exists(WORKOUT_FILE):
        try:
            with open(WORKOUT_FILE) as f:
                d = json.load(f)
        except (json.JSONDecodeError, IOError):
            d = {}
    else:
        d = {}
    d.setdefault("goal",               "general fitness")
    d.setdefault("days_per_week",      3)
    d.setdefault("equipment",          "gym")
    d.setdefault("preferences",        "")
    d.setdefault("progressive_overload", True)
    d.setdefault("program",            {})
    d.setdefault("templates",          {})
    d.setdefault("pr_log",             {})
    d.setdefault("body_stats",         [])
    d.setdefault("streak",             0)
    d.setdefault("last_workout_date",  None)
    return d


def save_workout(w: dict) -> None:
    from core.config import WORKOUT_FILE
    tmp = WORKOUT_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(w, f, indent=2)
    os.replace(tmp, WORKOUT_FILE)


# ═══════════════════════════════════════════════════════════════════════════════
# REPLY / EMAIL STYLE LIBRARY
# Stored in style_library.json as {"examples": [str, ...]}
# ═══════════════════════════════════════════════════════════════════════════════

def load_style_library() -> dict:
    from core.config import STYLE_LIB_FILE
    if os.path.exists(STYLE_LIB_FILE):
        try:
            with open(STYLE_LIB_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {"examples": []}
    return {"examples": []}


def save_style_library(lib: dict) -> None:
    from core.config import STYLE_LIB_FILE
    with open(STYLE_LIB_FILE, "w") as f:
        json.dump(lib, f, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# SETTINGS HELPERS
# Thin wrappers around userdata["settings"] for wizard-configured preferences.
# ═══════════════════════════════════════════════════════════════════════════════

_BRIEFING_ALL_SECTIONS = [
    "weather", "calendar", "todos", "habits", "meals",
    "journal_highlight", "workout_stats", "quote", "word_of_day",
]
_BRIEFING_DEFAULT_ORDER = [
    "weather", "calendar", "todos", "habits", "quote", "word_of_day",
]


def get_briefing_settings(data: dict) -> dict:
    """Return the briefing section config, initialising defaults if missing."""
    s = data.setdefault("settings", {})
    bs = s.setdefault("briefing", {})
    bs.setdefault("enabled", list(_BRIEFING_DEFAULT_ORDER))
    bs.setdefault("order",   list(_BRIEFING_DEFAULT_ORDER))
    return bs


def get_shopping_list_names(data: dict) -> list[str]:
    """Return the buyer-configured shopping list names (default 3)."""
    s = data.setdefault("settings", {})
    return s.setdefault("shopping_lists", ["grocery", "household", "wishlist"])


def get_journal_settings(data: dict) -> dict:
    """Return journal prompts + reminder configuration."""
    s = data.setdefault("settings", {})
    js = s.setdefault("journal", {})
    # prompts_by_day: "0"=Mon … "6"=Sun → list of question strings
    default_prompts = [
        "What went well today?",
        "What was challenging?",
        "What are you grateful for?",
    ]
    js.setdefault("prompts_by_day", {str(i): list(default_prompts) for i in range(7)})
    js.setdefault("reminder_count",      1)
    js.setdefault("reminder_gap_min",    0)
    js.setdefault("reminder_times",      ["21:00"])
    js.setdefault("adherence_reminder",  "20:00")
    return js


def get_workout_settings(data: dict) -> dict:
    """Return workout setup configuration."""
    s = data.setdefault("settings", {})
    ws = s.setdefault("workout", {})
    ws.setdefault("goal",               "build_muscle")
    ws.setdefault("days_per_week",      4)
    ws.setdefault("equipment",          "gym")
    ws.setdefault("preferences",        "")
    ws.setdefault("progressive_overload", True)
    return ws


def get_reply_settings(data: dict) -> dict:
    """Return reply/email assistant settings."""
    s = data.setdefault("settings", {})
    rs = s.setdefault("reply", {})
    rs.setdefault("default_tone", "warm")
    return rs


def get_weekly_summary_settings(data: dict) -> dict:
    """Return weekly summary schedule settings."""
    s = data.setdefault("settings", {})
    ws = s.setdefault("weekly_summary", {})
    import os as _os
    ws.setdefault("hour",    int(_os.getenv("WEEKLY_SUMMARY_HOUR", "9")))
    ws.setdefault("minute",  int(_os.getenv("WEEKLY_SUMMARY_MINUTE", "0")))
    ws.setdefault("weekday", int(_os.getenv("WEEKLY_SUMMARY_WEEKDAY", "0")))
    return ws


def get_mood_trend_from_data(data: dict, days: int = 14) -> list:
    """Return last N days of mood entries from userdata."""
    _dt = datetime.date
    cutoff = (_dt.today() - datetime.timedelta(days=days)).isoformat()
    return [e for e in data.get("mood_log", []) if e.get("date", "") >= cutoff]


def get_smart_suggestion_settings(data: dict) -> dict:
    """Return smart suggestions configuration."""
    s = data.setdefault("settings", {})
    ss = s.setdefault("smart_suggestions", {})
    ss.setdefault("enabled", True)
    ss.setdefault("areas", ["habits"])
    return ss

"""
alfred/adapters/google_tasks.py
================================
Google Tasks CRUD adapter — the single source of truth for all task-list
operations in Alfred.

WHAT THIS FILE DOES
───────────────────
All four Alfred feature areas that use Google Tasks go through this module:

  Todos       → "Alfred Todos"    task list
  Notes       → "Alfred Notes"    task list
  Shopping    → one list per SHOPPING_LISTS key  e.g. "Shopping: Grocery"
  Gifts       → "Alfred Gifts"    task list

The module handles:
  • Finding or creating named task lists on first use
  • In-process list-ID caching (no repeated API lookups per session)
  • Full CRUD: add, list, complete, delete, update
  • Graceful error handling — all functions return None / [] on failure
    instead of raising, so callers don't need try/except everywhere

PUBLIC INTERFACE — LOW-LEVEL
─────────────────────────────
  ensure_all_lists(service)          Create/find all Alfred lists, cache IDs
  get_list_id(service, list_name)    Find or create one list by name
  list_tasks(service, list_id, ...)  List tasks (optionally include completed)
  add_task(service, list_id, ...)    Add a task, returns the task dict
  complete_task(service, list_id, task_id)
  delete_task(service, list_id, task_id)
  update_task(service, list_id, task_id, **fields)
  find_task_by_title(service, list_id, title)

PUBLIC INTERFACE — HIGH-LEVEL HELPERS
───────────────────────────────────────
  get_todos_list_id(service)
  get_notes_list_id(service)
  get_gifts_list_id(service)
  get_shopping_list_id(service, list_key)   list_key = "grocery" / "household" / etc.

  add_todo(service, text, priority, recur, recur_next, due_date)
  list_todos(service, include_done)
  complete_todo(service, task_id)
  delete_todo(service, task_id)

  add_note(service, text)
  list_notes(service)
  delete_note(service, task_id)

  add_shopping_item(service, list_key, text)
  list_shopping(service, list_key, include_done)
  complete_shopping_item(service, list_key, task_id)
  delete_shopping_item(service, list_key, task_id)
  clear_completed_shopping(service, list_key)

  add_gift(service, person, idea, occasion, date)
  list_gifts(service, person)
  complete_gift(service, task_id)
  delete_gift(service, task_id)
"""

import logging
import json

logger = logging.getLogger(__name__)

from core.config import (
    GTASKS_TODOS_LIST,
    GTASKS_NOTES_LIST,
    GTASKS_SHOPPING_LISTS,
    GTASKS_GIFTS_LIST,
)


# ═══════════════════════════════════════════════════════════════════════════════
# IN-PROCESS LIST-ID CACHE
# Avoids a tasklists().list() round-trip on every operation.
# Keyed by list name → Google Tasks list ID string.
# Cleared on bot restart (which is fine — Railway redeploys are infrequent).
# ═══════════════════════════════════════════════════════════════════════════════

_list_id_cache: dict[str, str] = {}


def _cache_clear():
    """Clear the list-ID cache (useful for testing or after a reauth)."""
    _list_id_cache.clear()


# ═══════════════════════════════════════════════════════════════════════════════
# LOW-LEVEL TASK LIST MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════════

def get_list_id(service, list_name: str) -> str | None:
    """
    Return the Google Tasks list ID for `list_name`.

    If the list does not exist yet, creates it automatically.
    Results are cached in-process.

    Returns:
        str  — the list ID
        None — API error
    """
    if list_name in _list_id_cache:
        return _list_id_cache[list_name]

    try:
        result = service.tasklists().list(maxResults=100).execute()
        for tl in result.get("items", []):
            if tl.get("title") == list_name:
                _list_id_cache[list_name] = tl["id"]
                return tl["id"]

        # List does not exist — create it
        new_list = service.tasklists().insert(
            body={"title": list_name}
        ).execute()
        list_id = new_list["id"]
        _list_id_cache[list_name] = list_id
        logger.info(f"Created Google Tasks list: '{list_name}' (id={list_id})")
        return list_id

    except Exception as e:
        logger.error(f"get_list_id('{list_name}'): {e}")
        return None


def ensure_all_lists(service) -> dict[str, str]:
    """
    Ensure all Alfred task lists exist in the user's Google Tasks account.
    Call this once at startup or after a reauth.

    Returns:
        dict mapping list_name → list_id for all Alfred lists.
        Missing entries indicate API errors for those lists.
    """
    all_names = (
        [GTASKS_TODOS_LIST, GTASKS_NOTES_LIST, GTASKS_GIFTS_LIST]
        + list(GTASKS_SHOPPING_LISTS.values())
    )
    ids = {}
    for name in all_names:
        lid = get_list_id(service, name)
        if lid:
            ids[name] = lid
        else:
            logger.warning(f"ensure_all_lists: could not find/create '{name}'")
    return ids


# ═══════════════════════════════════════════════════════════════════════════════
# LOW-LEVEL TASK CRUD
# ═══════════════════════════════════════════════════════════════════════════════

def list_tasks(
    service,
    list_id: str,
    include_completed: bool = False,
    max_results: int = 100,
) -> list[dict]:
    """
    Return all tasks in a list, handling Google Tasks API pagination.

    Google Tasks API hard-caps at 100 results per page. This function
    automatically follows nextPageToken to retrieve all tasks.

    Args:
        include_completed: if False (default), only returns open tasks.
        max_results: per-page cap (max 100 per Google's API limit).

    Returns:
        list of task dicts (Google Tasks resource format)
        [] on error
    """
    all_tasks = []
    page_token = None

    try:
        while True:
            kwargs = {
                "tasklist":      list_id,
                "maxResults":    min(max_results, 100),  # API hard cap
                "showCompleted": include_completed,
                "showHidden":    include_completed,
            }
            if page_token:
                kwargs["pageToken"] = page_token

            result     = service.tasks().list(**kwargs).execute()
            all_tasks.extend(result.get("items", []))
            page_token = result.get("nextPageToken")

            if not page_token:
                break

    except Exception as e:
        logger.error(f"list_tasks(list_id={list_id}): {e}")

    return all_tasks


def add_task(
    service,
    list_id:  str,
    title:    str,
    notes:    str  = "",
    due:      str  = "",   # ISO date string "YYYY-MM-DD" or ""
) -> dict | None:
    """
    Add a new task to a list.

    Args:
        title:  task text (required)
        notes:  optional extra detail (stored in the task notes field)
        due:    optional due date in "YYYY-MM-DD" format

    Returns:
        The created task dict, or None on error.
    """
    body: dict = {"title": title, "status": "needsAction"}
    if notes:
        body["notes"] = notes
    if due:
        # Google Tasks due date must be RFC 3339 UTC.
        # We use local midnight converted to UTC so the date displays
        # correctly in the user's timezone in the Google Tasks UI.
        body["due"] = _local_midnight_to_utc(due)

    try:
        task = service.tasks().insert(tasklist=list_id, body=body).execute()
        return task
    except Exception as e:
        logger.error(f"add_task('{title}'): {e}")
        return None


def complete_task(service, list_id: str, task_id: str) -> bool:
    """
    Mark a task as completed.

    Returns True on success, False on error.
    """
    try:
        service.tasks().patch(
            tasklist=list_id,
            task=task_id,
            body={"status": "completed"},
        ).execute()
        return True
    except Exception as e:
        logger.error(f"complete_task(task_id={task_id}): {e}")
        return False


def delete_task(service, list_id: str, task_id: str) -> bool:
    """
    Permanently delete a task.

    Returns True on success, False on error.
    """
    try:
        service.tasks().delete(tasklist=list_id, task=task_id).execute()
        return True
    except Exception as e:
        logger.error(f"delete_task(task_id={task_id}): {e}")
        return False


def update_task(service, list_id: str, task_id: str, **fields) -> dict | None:
    """
    Update arbitrary fields on a task.

    Common fields: title, notes, due, status
    Returns the updated task dict, or None on error.
    """
    try:
        return service.tasks().patch(
            tasklist=list_id,
            task=task_id,
            body=fields,
        ).execute()
    except Exception as e:
        logger.error(f"update_task(task_id={task_id}, fields={fields}): {e}")
        return None


def find_task_by_title(
    service,
    list_id: str,
    title:   str,
    include_completed: bool = False,
) -> dict | None:
    """
    Find the first task whose title exactly matches `title` (case-insensitive).

    Returns the task dict, or None if not found.
    """
    tasks = list_tasks(service, list_id, include_completed=include_completed)
    title_lower = title.lower()
    for t in tasks:
        if t.get("title", "").lower() == title_lower:
            return t
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# HIGH-LEVEL: LIST ID HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def get_todos_list_id(service) -> str | None:
    return get_list_id(service, GTASKS_TODOS_LIST)


def get_notes_list_id(service) -> str | None:
    return get_list_id(service, GTASKS_NOTES_LIST)


def get_gifts_list_id(service) -> str | None:
    return get_list_id(service, GTASKS_GIFTS_LIST)


def get_shopping_list_id(service, list_key: str) -> str | None:
    """
    list_key is the internal config key, e.g. "grocery", "household".
    Returns None if list_key is not in GTASKS_SHOPPING_LISTS.
    """
    list_name = GTASKS_SHOPPING_LISTS.get(list_key)
    if not list_name:
        logger.warning(f"get_shopping_list_id: unknown list key '{list_key}'")
        return None
    return get_list_id(service, list_name)


# ═══════════════════════════════════════════════════════════════════════════════
# HIGH-LEVEL: TODOS
# ═══════════════════════════════════════════════════════════════════════════════

def add_todo(
    service,
    text:       str,
    priority:   str  = "normal",   # "high" | "normal" | "low"
    recur:      str  = "none",
    recur_next: str  = "",         # ISO date "YYYY-MM-DD" or ""
    due_date:   str  = "",
) -> dict | None:
    """
    Add a todo to Google Tasks.

    Priority and recurrence are stored in the task notes field as a JSON
    string so they survive round-trips without needing a separate database.
    """
    list_id = get_todos_list_id(service)
    if not list_id:
        return None

    meta = {}
    if priority and priority != "normal":
        meta["priority"] = priority
    if recur and recur != "none":
        meta["recur"]      = recur
        meta["recur_next"] = recur_next

    notes = json.dumps(meta) if meta else ""
    due   = recur_next or due_date or ""

    return add_task(service, list_id, title=text, notes=notes, due=due)


def list_todos(service, include_done: bool = False) -> list[dict]:
    """
    Return todos from Google Tasks.

    Each returned dict is the raw Google task resource, enriched with an
    `_meta` key containing parsed priority/recurrence data from the notes field.
    """
    list_id = get_todos_list_id(service)
    if not list_id:
        return []
    tasks = list_tasks(service, list_id, include_completed=include_done)
    return [_enrich_todo(t) for t in tasks]


def complete_todo(service, task_id: str) -> bool:
    list_id = get_todos_list_id(service)
    if not list_id:
        return False
    return complete_task(service, list_id, task_id)


def delete_todo(service, task_id: str) -> bool:
    list_id = get_todos_list_id(service)
    if not list_id:
        return False
    return delete_task(service, list_id, task_id)


def _enrich_todo(task: dict) -> dict:
    """Parse the notes JSON back into a _meta dict on the task."""
    notes = task.get("notes", "")
    try:
        task["_meta"] = json.loads(notes) if notes else {}
    except (json.JSONDecodeError, TypeError):
        task["_meta"] = {}
    return task


# ═══════════════════════════════════════════════════════════════════════════════
# HIGH-LEVEL: NOTES
# ═══════════════════════════════════════════════════════════════════════════════

def add_note(service, text: str) -> dict | None:
    """Add a note to the Alfred Notes list."""
    list_id = get_notes_list_id(service)
    if not list_id:
        return None
    return add_task(service, list_id, title=text)


def list_notes(service) -> list[dict]:
    """Return all open notes."""
    list_id = get_notes_list_id(service)
    if not list_id:
        return []
    return list_tasks(service, list_id, include_completed=False)


def delete_note(service, task_id: str) -> bool:
    list_id = get_notes_list_id(service)
    if not list_id:
        return False
    return delete_task(service, list_id, task_id)


# ═══════════════════════════════════════════════════════════════════════════════
# HIGH-LEVEL: SHOPPING
# ═══════════════════════════════════════════════════════════════════════════════

def add_shopping_item(service, list_key: str, text: str) -> dict | None:
    """
    Add an item to a shopping list.

    list_key: "grocery" | "household" | "baby" | "wishlist" (or any key
    configured in SHOPPING_LISTS in config.py).
    """
    list_id = get_shopping_list_id(service, list_key)
    if not list_id:
        return None
    return add_task(service, list_id, title=text)


def list_shopping(
    service,
    list_key:     str,
    include_done: bool = False,
) -> list[dict]:
    """Return items in a shopping list."""
    list_id = get_shopping_list_id(service, list_key)
    if not list_id:
        return []
    return list_tasks(service, list_id, include_completed=include_done)


def complete_shopping_item(service, list_key: str, task_id: str) -> bool:
    list_id = get_shopping_list_id(service, list_key)
    if not list_id:
        return False
    return complete_task(service, list_id, task_id)


def delete_shopping_item(service, list_key: str, task_id: str) -> bool:
    list_id = get_shopping_list_id(service, list_key)
    if not list_id:
        return False
    return delete_task(service, list_id, task_id)


def clear_completed_shopping(service, list_key: str) -> int:
    """
    Delete all completed items from a shopping list.

    Returns the count of items removed.
    """
    list_id = get_shopping_list_id(service, list_key)
    if not list_id:
        return 0

    completed = list_tasks(service, list_id, include_completed=True)
    removed = 0
    for task in completed:
        if task.get("status") == "completed":
            if delete_task(service, list_id, task["id"]):
                removed += 1
    return removed


def list_all_shopping(service) -> dict[str, list[dict]]:
    """
    Return all shopping lists as a dict: {list_key: [task, ...]}
    Useful for the morning briefing and /shopping command.
    """
    result = {}
    for key in GTASKS_SHOPPING_LISTS:
        result[key] = list_shopping(service, key, include_done=False)
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# HIGH-LEVEL: GIFTS
# ═══════════════════════════════════════════════════════════════════════════════

def add_gift(
    service,
    person:   str,
    idea:     str,
    occasion: str = "",
    date:     str = "",   # ISO "YYYY-MM-DD" or freeform "Christmas", "April 3"
) -> dict | None:
    """
    Add a gift idea for a person.

    Title format: "{person}: {idea}"
    Notes: JSON with occasion and date so the briefing can surface upcoming gifts.
    Due: set to `date` if it's a valid ISO date, otherwise left blank.
    """
    list_id = get_gifts_list_id(service)
    if not list_id:
        return None

    title = f"{person}: {idea}"
    meta  = {}
    if occasion:
        meta["occasion"] = occasion
    if date:
        meta["date"] = date

    notes   = json.dumps(meta) if meta else ""
    due_iso = date if _is_iso_date(date) else ""

    return add_task(service, list_id, title=title, notes=notes, due=due_iso)


def list_gifts(service, person: str | None = None) -> list[dict]:
    """
    Return gift ideas.

    Args:
        person: if provided, filter to ideas for that person (case-insensitive).
                If None, return all gifts.

    Each task is enriched with a `_meta` dict containing occasion and date,
    and a `_person` key extracted from the title.
    """
    list_id = get_gifts_list_id(service)
    if not list_id:
        return []

    tasks = list_tasks(service, list_id, include_completed=False)
    enriched = [_enrich_gift(t) for t in tasks]

    if person:
        person_lower = person.lower()
        enriched = [
            t for t in enriched
            if t.get("_person", "").lower() == person_lower
        ]
    return enriched


def complete_gift(service, task_id: str) -> bool:
    """Mark a gift idea as purchased/given."""
    list_id = get_gifts_list_id(service)
    if not list_id:
        return False
    return complete_task(service, list_id, task_id)


def delete_gift(service, task_id: str) -> bool:
    list_id = get_gifts_list_id(service)
    if not list_id:
        return False
    return delete_task(service, list_id, task_id)


def _enrich_gift(task: dict) -> dict:
    """Parse notes JSON into _meta and extract person from title."""
    notes = task.get("notes", "")
    try:
        task["_meta"] = json.loads(notes) if notes else {}
    except (json.JSONDecodeError, TypeError):
        task["_meta"] = {}

    # Title format: "Person: Idea" — split on first colon
    title = task.get("title", "")
    if ":" in title:
        parts         = title.split(":", 1)
        task["_person"] = parts[0].strip()
        task["_idea"]   = parts[1].strip()
    else:
        task["_person"] = ""
        task["_idea"]   = title

    return task


# ═══════════════════════════════════════════════════════════════════════════════
# HIGH-LEVEL: EDIT (update text/fields on existing items)
# ═══════════════════════════════════════════════════════════════════════════════

def update_todo(service, task_id: str, new_text: str | None = None,
                priority: str | None = None, due_date: str | None = None,
                recur: str | None = None, recur_next: str | None = None) -> dict | None:
    """
    Edit an existing todo.

    Pass only the fields you want to change — others are left untouched.
    Fetches the current task first to preserve existing metadata.
    Returns the updated task dict, or None on error.
    """
    list_id = get_todos_list_id(service)
    if not list_id:
        return None

    fields: dict = {}
    if new_text is not None:
        fields["title"] = new_text

    # Rebuild notes JSON if any meta field is being changed
    if any(x is not None for x in [priority, recur, recur_next]):
        # Fetch current meta first
        current = get_task_by_id_in_list(service, list_id, task_id)  # fetch current task
        current_meta = {}
        if current:
            try:
                current_meta = json.loads(current.get("notes", "") or "{}")
            except (json.JSONDecodeError, TypeError):
                current_meta = {}
        if priority   is not None: current_meta["priority"]   = priority
        if recur      is not None: current_meta["recur"]      = recur
        if recur_next is not None: current_meta["recur_next"] = recur_next
        # Remove keys set to None/default
        current_meta = {k: v for k, v in current_meta.items() if v and v != "none"}
        fields["notes"] = json.dumps(current_meta) if current_meta else ""

    if due_date is not None:
        fields["due"] = _local_midnight_to_utc(due_date) if due_date else None

    if not fields:
        return None
    return update_task(service, list_id, task_id, **fields)


def update_note(service, task_id: str, new_text: str) -> dict | None:
    """Edit the text of an existing note. Returns updated task or None."""
    list_id = get_notes_list_id(service)
    if not list_id:
        return None
    return update_task(service, list_id, task_id, title=new_text)


def update_shopping_item(service, list_key: str, task_id: str, new_text: str) -> dict | None:
    """Edit the text of an existing shopping list item. Returns updated task or None."""
    list_id = get_shopping_list_id(service, list_key)
    if not list_id:
        return None
    return update_task(service, list_id, task_id, title=new_text)


def update_gift(service, task_id: str, idea: str | None = None,
                occasion: str | None = None, date: str | None = None) -> dict | None:
    """
    Edit a gift idea. Pass only the fields you want to change.
    Person name cannot be changed (delete and re-add instead).
    Returns updated task or None.
    """
    list_id = get_gifts_list_id(service)
    if not list_id:
        return None

    fields: dict = {}

    if idea is not None:
        # Need to preserve the person prefix
        current = get_task_by_id_in_list(service, list_id, task_id)
        if current:
            enriched = _enrich_gift(current.copy())
            fields["title"] = f"{enriched['_person']}: {idea}"

    if occasion is not None or date is not None:
        current = current if idea is not None else get_task_by_id_in_list(service, list_id, task_id)
        if current:
            try:
                meta = json.loads(current.get("notes", "") or "{}")
            except (json.JSONDecodeError, TypeError):
                meta = {}
            if occasion is not None: meta["occasion"] = occasion
            if date     is not None: meta["date"]     = date
            fields["notes"] = json.dumps(meta)
            if date and _is_iso_date(date):
                fields["due"] = _local_midnight_to_utc(date)

    if not fields:
        return None
    return update_task(service, list_id, task_id, **fields)


def get_task_by_id_in_list(service, list_id: str, task_id: str) -> dict | None:
    """Fetch a single task by ID within a known list. Returns None on error."""
    try:
        return service.tasks().get(tasklist=list_id, task=task_id).execute()
    except Exception as e:
        logger.error(f"get_task_by_id_in_list(task_id={task_id}): {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# HIGH-LEVEL: FIND BY TITLE
# ═══════════════════════════════════════════════════════════════════════════════

def find_todo_by_title(service, title: str, include_done: bool = False) -> dict | None:
    """
    Find the first todo whose title contains `title` (case-insensitive).
    Returns the enriched task dict, or None if not found.
    """
    list_id = get_todos_list_id(service)
    if not list_id:
        return None
    task = find_task_by_title(service, list_id, title, include_completed=include_done)
    return _enrich_todo(task) if task else None


def find_note_by_title(service, title: str) -> dict | None:
    """Find the first note whose title contains `title` (case-insensitive)."""
    list_id = get_notes_list_id(service)
    if not list_id:
        return None
    return find_task_by_title(service, list_id, title)


def find_shopping_item(service, list_key: str, title: str,
                       include_done: bool = False) -> dict | None:
    """Find a shopping item by partial title match in a specific list."""
    list_id = get_shopping_list_id(service, list_key)
    if not list_id:
        return None
    return find_task_by_title(service, list_id, title, include_completed=include_done)


def find_gift_by_idea(service, person: str, idea: str) -> dict | None:
    """
    Find a gift idea by person name and partial idea text.
    Returns the enriched task dict, or None.
    """
    gifts = list_gifts(service, person=person)
    idea_lower = idea.lower()
    for g in gifts:
        if idea_lower in g.get("_idea", "").lower():
            return g
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# UTILITIES
# ═══════════════════════════════════════════════════════════════════════════════

def _is_iso_date(value: str) -> bool:
    """Return True if value looks like YYYY-MM-DD."""
    import re
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}$", value or ""))


def _local_midnight_to_utc(iso_date: str) -> str:
    """
    Convert a local date string "YYYY-MM-DD" to a UTC RFC 3339 string
    representing midnight in the user's configured timezone.

    This ensures due dates display on the correct day in the Google Tasks UI
    regardless of the user's timezone offset from UTC.

    Example (America/Denver, UTC-7):
        "2026-04-07" → "2026-04-07T07:00:00.000Z"
    """
    import pytz, datetime as _dt
    from core.config import TIMEZONE as _TZ
    try:
        tz       = pytz.timezone(_TZ)
        date     = _dt.date.fromisoformat(iso_date)
        local_midnight = tz.localize(_dt.datetime(date.year, date.month, date.day, 0, 0, 0))
        utc_midnight   = local_midnight.astimezone(pytz.utc)
        return utc_midnight.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    except Exception:
        # Fallback to naive UTC midnight rather than crash
        return f"{iso_date}T00:00:00.000Z"


def format_task_list_for_display(
    tasks:      list[dict],
    empty_msg:  str = "Nothing here.",
    done_label: str = "✅",
    open_label: str = "•",
) -> str:
    """
    Convert a list of Google Tasks into a numbered display string.

    Example output:
        1. Buy milk
        2. ✅ Eggs (completed)
        3. Bread

    Returns the formatted string, or empty_msg if tasks is empty.
    Used by feature handlers to format replies without duplicating logic.
    """
    if not tasks:
        return empty_msg

    lines = []
    for i, task in enumerate(tasks, start=1):
        title  = task.get("title", "").strip()
        done   = task.get("status") == "completed"
        prefix = done_label if done else open_label
        lines.append(f"{i}. {prefix} {title}")
    return "\n".join(lines)

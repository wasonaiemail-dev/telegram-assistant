import os
import json
import logging
import datetime
import asyncio
import requests
import pytz
from openai import OpenAI
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, CallbackQueryHandler, filters, ContextTypes

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
ALLOWED_USER_ID = int(os.environ["ALLOWED_USER_ID"])
GOOGLE_CREDENTIALS = os.environ["GOOGLE_CREDENTIALS"]

client = OpenAI()

conversation_history = {}
SCOPES = ["https://www.googleapis.com/auth/calendar", "https://www.googleapis.com/auth/tasks"]
# Use persistent volume if mounted, otherwise fall back to /tmp
PERSIST_DIR = "/data" if os.path.isdir("/data") else "/tmp"
TOKEN_FILE = os.path.join(PERSIST_DIR, "google_token.json")
AUTH_STATE_FILE = os.path.join(PERSIST_DIR, "auth_state.json")
DATA_FILE = os.path.join(PERSIST_DIR, "userdata.json")
LOG_FILE = os.path.join(PERSIST_DIR, "audit.log")
CONTACTS_FILE = os.path.join(PERSIST_DIR, "contacts.json")
CONVO_FILE = os.path.join(PERSIST_DIR, "conversation.json")

# Data helpers

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            data = json.load(f)
        # Migrate old flat shopping list -> shopping_lists structure
        if "shopping_lists" not in data:
            old_shopping = data.get("shopping", [])
            data["shopping_lists"] = {
                "grocery": old_shopping if old_shopping else [],
                "household": [],
                "baby": [],
                "wishlist": []
            }
            data.pop("shopping", None)
            with open(DATA_FILE, "w") as f:
                json.dump(data, f, indent=2)
        # Ensure all list keys exist
        for k in ("grocery", "household", "baby", "wishlist"):
            data["shopping_lists"].setdefault(k, [])
        return data
    return {
        "todos": [],
        "shopping_lists": {"grocery": [], "household": [], "baby": [], "wishlist": []},
        "notes": [],
        "reminders": [],
        "expenses": [],
        "meals": [],
        "workouts": [],
        "gifts": {},
        "habits": {},
        "habit_log": []
    }

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


def load_contacts():
    if os.path.exists(CONTACTS_FILE):
        with open(CONTACTS_FILE, "r") as f:
            return json.load(f)
    return {}


def save_contacts(contacts):
    with open(CONTACTS_FILE, "w") as f:
        json.dump(contacts, f, indent=2)


def load_conversation():
    if os.path.exists(CONVO_FILE):
        with open(CONVO_FILE, "r") as f:
            return json.load(f)
    return {}


def save_conversation(history):
    with open(CONVO_FILE, "w") as f:
        json.dump(history, f, indent=2)


def audit_log(event):
    try:
        tz = pytz.timezone("America/Denver")
        ts = datetime.datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_FILE, "a") as f:
            f.write(f"{ts} | {event}\n")
    except Exception:
        pass


def send_error_alert(bot, msg):
    import asyncio
    try:
        asyncio.create_task(
            bot.send_message(chat_id=ALLOWED_USER_ID, text=f"Bot error: {msg[:300]}")
        )
    except Exception:
        pass

# System prompt - NO apostrophes anywhere inside this string

SYSTEM_PROMPT = """You are a personal assistant accessible via Telegram. You are helpful, concise, and friendly.

You help with scheduling, lists, notes, tracking, and general questions.

== CALENDAR ==
When the user asks to add/create/schedule a calendar event, respond with this on its own line:
CALENDAR_ACTION: {"action": "create", "title": "...", "start": "YYYY-MM-DDTHH:MM:00", "end": "YYYY-MM-DDTHH:MM:00", "description": "...", "recurrence": ""}

For recurring events, set recurrence to one of: "RRULE:FREQ=DAILY", "RRULE:FREQ=WEEKLY", "RRULE:FREQ=MONTHLY", "RRULE:FREQ=YEARLY". Leave empty for single events.
Examples: "every Monday" -> "RRULE:FREQ=WEEKLY;BYDAY=MO", "daily" -> "RRULE:FREQ=DAILY", "every week" -> "RRULE:FREQ=WEEKLY"

When the user asks what is on their calendar or schedule, respond with:
CALENDAR_ACTION: {"action": "list", "days": 7}

When the user asks to delete or remove a calendar event, tell them: to delete events, open Google Calendar directly since the bot cannot delete events for safety reasons.
When the user asks to edit or update a calendar event time/title, tell them the same.

== TO-DO LIST ==
When the user asks to add a task or to-do, respond with:
DATA_ACTION: {"action": "todo_add", "item": "...", "priority": "normal"}

If the user says "high priority", "urgent", "important", or "asap" use priority "high".
If the user says "low priority", "whenever", "someday" use priority "low".
Otherwise use "normal".

When the user asks to see their to-do list, respond with:
DATA_ACTION: {"action": "todo_list"}

When the user marks a task done or checks off a to-do (by number or name), respond with:
DATA_ACTION: {"action": "todo_done", "index": <number starting at 1>}

When the user asks to clear all completed todos or clear the list:
DATA_ACTION: {"action": "todo_clear"}

When the user wants to delete or remove a specific todo by number or name:
DATA_ACTION: {"action": "todo_delete", "index": <number starting at 1>}

When the user wants to change the priority of a todo (e.g. "make todo 2 high priority"):
DATA_ACTION: {"action": "todo_priority", "index": <number starting at 1>, "priority": "high|normal|low"}

== SHOPPING LISTS ==
There are 4 shopping lists: grocery, household, baby (for Luna), wishlist.
Auto-assign items to the correct list:
- grocery: food, drinks, produce, dairy, meat, snacks, beverages, kitchen staples
- household: cleaning supplies, paper towels, soap, laundry, home supplies, batteries, light bulbs
- baby: diapers, wipes, formula, baby food, baby clothes, Luna items, anything for the baby
- wishlist: electronics, gadgets, clothing for self, personal wants, things to buy someday

When the user adds a shopping item (naturally or explicitly):
DATA_ACTION: {"action": "shop_add", "item": "...", "list": "grocery|household|baby|wishlist"}

If the user says "add to grocery/household/baby/wishlist" use that list explicitly.
If unclear, use grocery as default for food items, wishlist for non-essential personal items.

When the user asks to see their shopping list or /shopping:
DATA_ACTION: {"action": "shop_list"}

When the user marks a shopping item as gotten or bought (by number or name):
DATA_ACTION: {"action": "shop_done", "index": <number starting at 1>, "list": "grocery|household|baby|wishlist"}

When the user asks to delete or remove a shopping item:
DATA_ACTION: {"action": "shop_delete", "index": <number starting at 1>, "list": "grocery|household|baby|wishlist"}

When the user asks to clear bought/done items from a list:
DATA_ACTION: {"action": "shop_clear", "list": "grocery|household|baby|wishlist|all"}

When the user wants to remove/delete a specific shopping item (not mark it bought, but remove it entirely):
DATA_ACTION: {"action": "shop_delete", "index": <number>}

== NOTES ==
When the user says note, remember this, save this, jot this down, or anything like note: ...:
DATA_ACTION: {"action": "note_add", "text": "..."}

When the user asks to see their notes:
DATA_ACTION: {"action": "note_list"}

When the user wants to search notes or find a note about something:
DATA_ACTION: {"action": "note_search", "query": "...search term..."}

When the user asks to delete a note by number:
DATA_ACTION: {"action": "note_delete", "index": <number starting at 1>}

== REMINDERS ==
When the user asks to be reminded of something at a specific time, respond with:
DATA_ACTION: {"action": "reminder_add", "text": "...", "time": "YYYY-MM-DDTHH:MM:00"}

When the user asks to see their reminders:
DATA_ACTION: {"action": "reminder_list"}

When the user wants to cancel or delete a specific reminder by number:
DATA_ACTION: {"action": "reminder_cancel", "index": <number starting at 1>}

== EXPENSES ==
When the user logs an expense (e.g. spent $45 on groceries, bought gas for $60):
DATA_ACTION: {"action": "expense_add", "amount": <number>, "category": "...", "note": "..."}

When the user asks for spending summary or to see expenses:
DATA_ACTION: {"action": "expense_list"}

== MEAL PLANNING ==
When the user saves a meal idea or recipe name:
DATA_ACTION: {"action": "meal_add", "meal": "..."}

When the user asks for meal ideas or their meal list:
DATA_ACTION: {"action": "meal_list"}

When the user asks to plan the weekly meals:
DATA_ACTION: {"action": "meal_plan"}

== WORKOUT LOG ==
When the user logs a workout (e.g. just did 30 min run, did chest day, walked 2 miles):
DATA_ACTION: {"action": "workout_add", "description": "..."}

When the user asks to see their workout history:
DATA_ACTION: {"action": "workout_list"}

== SLEEP TRACKING ==
When the user mentions sleep (e.g. slept 7 hours, got 6 hours of sleep, only slept 5 hours, slept great):
DATA_ACTION: {"action": "sleep_add", "hours": <number or null if unknown>, "quality": "good|okay|poor or null"}

When the user asks to see their sleep log:
DATA_ACTION: {"action": "sleep_list"}

== MOOD TRACKING ==
When the user mentions how they are feeling (e.g. feeling tired, stressed, anxious, great, happy, good, exhausted):
DATA_ACTION: {"action": "mood_add", "mood": "great|good|okay|tired|stressed|anxious|low", "note": "...optional context..."}

When the user asks to see their mood log:
DATA_ACTION: {"action": "mood_list"}

== GIFT IDEAS ==
When the user saves a gift idea for someone, extract person, idea, occasion, and target date if mentioned:
DATA_ACTION: {"action": "gift_add", "person": "...", "idea": "...", "occasion": "birthday|christmas|anniversary|just because|other", "date": "YYYY-MM-DD or empty"}

When the user asks to see gift ideas (optionally for a person):
DATA_ACTION: {"action": "gift_list", "person": "..."}

== SMART REPLY DRAFTING ==
When the user asks for help replying to a message, email, or DM - or pastes a message and says things like help me reply, how should I respond, draft a response, what should I say, reply to this - generate exactly 3 reply options.

Automatically detect the type and tone:
- Is it a text/iMessage, work email, or social media DM?
- Is the sender a friend, family member, colleague, or stranger?
- What is the context - casual, professional, sensitive, urgent?

Format your response EXACTLY like this (always use these exact labels):

**Option 1 - [tone label, e.g. Warm and friendly]:**
[reply text]

**Option 2 - [tone label, e.g. Professional]:**
[reply text]

**Option 3 - [tone label, e.g. Short and direct]:**
[reply text]

After the options, add one line: Want me to tweak any of these?

If the user asks to refine an option (e.g. make option 2 more casual, make option 1 shorter), rewrite just that option.
If the user says send option 2 or use option 1, just confirm which they picked - you cannot actually send it for them.

== HABIT LOGGING ==
The user tracks these daily habits: Daily workout, Water intake, Meditation, Morning routine, Journaling, Vitamins, Stretching, Outdoor time, Gratitude practice.
When the user mentions completing any of these (e.g. "did my workout", "meditated today", "took vitamins"), the habit checker handles it automatically - just respond naturally and encouragingly.

== CONTACT MEMORY ==
When the user says things like "remember that John prefers texts over calls" or "note about Sarah: birthday is April 3rd", respond with:
CONTACT_ACTION: {"name": "...", "fact": "..."}
When the user asks about a person you have notes on, include the relevant facts naturally in your response.

== GENERAL ==
For everything else, respond normally in plain conversational text.
Keep responses concise. The current date and time will be provided in each message.
When performing a DATA_ACTION or CALENDAR_ACTION, also include a brief friendly confirmation message on a separate line before or after the action line."""


# Calendar helpers

def get_calendar_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    if not creds or not creds.valid:
        return None
    return build("calendar", "v3", credentials=creds)


def create_event(title, start, end, description="", recurrence=None):
    service = get_calendar_service()
    if not service:
        return None
    event = {
        "summary": title,
        "description": description,
        "start": {"dateTime": start, "timeZone": "America/Denver"},
        "end": {"dateTime": end, "timeZone": "America/Denver"},
    }
    if recurrence:
        event["recurrence"] = recurrence
    return service.events().insert(calendarId="primary", body=event).execute()


def list_events(days=7):
    service = get_calendar_service()
    if not service:
        return None
    now = datetime.datetime.utcnow().isoformat() + "Z"
    future = (datetime.datetime.utcnow() + datetime.timedelta(days=days)).isoformat() + "Z"
    all_events = []
    try:
        calendars = service.calendarList().list().execute().get("items", [])
        for cal in calendars:
            try:
                result = service.events().list(
                    calendarId=cal["id"],
                    timeMin=now,
                    timeMax=future,
                    singleEvents=True,
                    orderBy="startTime"
                ).execute()
                for event in result.get("items", []):
                    event["_calendar_name"] = cal.get("summary", "")
                    all_events.append(event)
            except Exception:
                pass
    except Exception:
        result = service.events().list(
            calendarId="primary",
            timeMin=now,
            timeMax=future,
            singleEvents=True,
            orderBy="startTime"
        ).execute()
        return result.get("items", [])
    all_events.sort(key=lambda e: e["start"].get("dateTime", e["start"].get("date", "")))
    return all_events


# Data action handler

async def handle_data_action(action_data):
    data = load_data()
    action = action_data.get("action", "")
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    # TO-DO
    if action == "todo_add":
        item = action_data.get("item", "").strip()
        priority = action_data.get("priority", "normal").lower()
        if priority not in ("high", "normal", "low"):
            priority = "normal"
        # Dedup check - warn if very similar item exists
        existing = [t["text"].lower() for t in data.get("todos", []) if not t.get("done")]
        item_lower = item.lower()
        for ex in existing:
            if item_lower in ex or ex in item_lower or (len(item_lower) > 5 and item_lower[:8] in ex):
                # Store in a separate pending key for "add anyway" override
                # Note: can't access context here so we just return the warning
                return f"Similar todo already exists: \"{ex}\"\nSay \"add anyway\" if you still want to add \"{item}\""
        data["todos"].append({"text": item, "done": False, "added": now_str, "priority": priority})
        save_data(data)
        flag = " [HIGH PRIORITY]" if priority == "high" else (" [low priority]" if priority == "low" else "")
        return f"Added to your to-do list: {item}{flag}"

    elif action == "todo_list":
        todos = data.get("todos", [])
        if not todos:
            return "Your to-do list is empty!"
        priority_order = {"high": 0, "normal": 1, "low": 2}
        active = sorted([t for t in todos if not t.get("done")],
                        key=lambda t: priority_order.get(t.get("priority", "normal"), 1))
        done_items = [t for t in todos if t.get("done")]
        def _esc(s):
            return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        lines = ["<b>To-Do List</b>\n"]
        if active:
            for i, t in enumerate(active, 1):
                p = t.get("priority", "normal")
                if p == "high":
                    icon = "🔴"
                elif p == "low":
                    icon = "🔵"
                else:
                    icon = "⚪"
                lines.append(f"{icon} {i}. {_esc(t['text'])}")
        if done_items:
            lines.append("\n<i>Completed:</i>")
            for t in done_items:
                lines.append(f"✅ {_esc(t['text'])}")
        return "\n".join(lines)

    elif action == "todo_done":
        idx = action_data.get("index", 0) - 1
        todos = data.get("todos", [])
        if 0 <= idx < len(todos):
            todos[idx]["done"] = True
            save_data(data)
            return f"Marked done: {todos[idx]['text']}"
        return "Couldn't find that item."

    elif action == "todo_clear":
        data["todos"] = [t for t in data["todos"] if not t["done"]]
        save_data(data)
        return "Cleared completed to-dos."

    elif action == "todo_delete":
        active = [t for t in data.get("todos", []) if not t.get("done")]
        idx = action_data.get("index", 0) - 1
        if 0 <= idx < len(active):
            item_text = active[idx]["text"]
            data["todos"] = [t for t in data["todos"] if t is not active[idx]]
            save_data(data)
            return f"Deleted: {item_text}"
        return "Could not find that todo item."

    elif action == "todo_priority":
        active = [t for t in data.get("todos", []) if not t.get("done")]
        idx = action_data.get("index", 0) - 1
        new_p = action_data.get("priority", "normal").lower()
        if new_p not in ("high", "normal", "low"):
            new_p = "normal"
        if 0 <= idx < len(active):
            active[idx]["priority"] = new_p
            save_data(data)
            flag = "🔴 HIGH" if new_p == "high" else ("🔵 low" if new_p == "low" else "⚪ normal")
            return f"Updated priority to {flag}: {active[idx]['text']}"
        return "Could not find that todo item."

    # SHOPPING
    elif action == "shop_add":
        # Migrate old shopping list if needed
        if "shopping_lists" not in data:
            data["shopping_lists"] = {"grocery": [], "household": [], "baby": [], "wishlist": []}
            for old_item in data.get("shopping", []):
                data["shopping_lists"]["grocery"].append(old_item)
        item = action_data.get("item", "").strip()
        lst = action_data.get("list", "grocery").lower()
        if lst not in ("grocery", "household", "baby", "wishlist"):
            lst = "grocery"
        if "shopping_lists" not in data:
            data["shopping_lists"] = {"grocery": [], "household": [], "baby": [], "wishlist": []}
        data["shopping_lists"][lst].append({"text": item, "done": False, "added": now_str})
        save_data(data)
        list_label = {"grocery": "Grocery", "household": "Household", "baby": "Luna (Baby)", "wishlist": "Wishlist"}[lst]
        return f"Added to {list_label}: {item}"

    elif action == "shop_list":
        # Migrate old shopping list if needed
        if "shopping_lists" not in data:
            data["shopping_lists"] = {"grocery": [], "household": [], "baby": [], "wishlist": []}
            for old_item in data.get("shopping", []):
                data["shopping_lists"]["grocery"].append(old_item)
            save_data(data)
        lists = data.get("shopping_lists", {"grocery": [], "household": [], "baby": [], "wishlist": []})
        list_icons = {"grocery": "\U0001f6d2 <b>Grocery</b>", "household": "\U0001f3e0 <b>Household</b>",
                      "baby": "\U0001f476 <b>Luna (Baby)</b>", "wishlist": "\u2b50 <b>Wishlist</b>"}
        sections = []
        for lst_key in ("grocery", "household", "baby", "wishlist"):
            items = [i for i in lists.get(lst_key, []) if not i.get("done")]
            if items:
                lines = [list_icons[lst_key]]
                for i, t in enumerate(items, 1):
                    lines.append(f"  {i}. {t['text']}")
                sections.append("\n".join(lines))
        if not sections:
            return "All shopping lists are empty!"
        return "\n\n".join(sections)

    elif action == "shop_done":
        lst = action_data.get("list", "grocery").lower()
        if lst not in ("grocery", "household", "baby", "wishlist"):
            lst = "grocery"
        idx = action_data.get("index", 0) - 1
        lists = data.get("shopping_lists", {})
        items = [i for i in lists.get(lst, []) if not i.get("done")]
        if 0 <= idx < len(items):
            items[idx]["done"] = True
            save_data(data)
            return f"Got it: {items[idx]['text']}"
        return "Couldn't find that item."

    elif action == "shop_delete":
        lst = action_data.get("list", "grocery").lower()
        if lst not in ("grocery", "household", "baby", "wishlist"):
            lst = "grocery"
        idx = action_data.get("index", 0) - 1
        lists = data.get("shopping_lists", {})
        items = [i for i in lists.get(lst, []) if not i.get("done")]
        if 0 <= idx < len(items):
            removed = items[idx]["text"]
            lists[lst] = [i for i in lists.get(lst, []) if i is not items[idx]]
            save_data(data)
            return f"Removed from list: {removed}"
        return "Couldn't find that item."

    elif action == "shop_clear":
        lst = action_data.get("list", "all").lower()
        if "shopping_lists" not in data:
            data["shopping_lists"] = {"grocery": [], "household": [], "baby": [], "wishlist": []}
        if lst == "all":
            for k in data["shopping_lists"]:
                data["shopping_lists"][k] = [i for i in data["shopping_lists"][k] if not i.get("done")]
        elif lst in data["shopping_lists"]:
            data["shopping_lists"][lst] = [i for i in data["shopping_lists"][lst] if not i.get("done")]
        save_data(data)
        return "Cleared purchased items."

    elif action == "shop_delete":
        active = [t for t in data.get("shopping", []) if not t.get("done")]
        idx = action_data.get("index", 0) - 1
        if 0 <= idx < len(active):
            item_text = active[idx]["text"]
            data["shopping"] = [t for t in data["shopping"] if t is not active[idx]]
            save_data(data)
            return f"Removed from shopping list: {item_text}"
        return "Could not find that item."

    # NOTES
    elif action == "note_add":
        text = action_data.get("text", "").strip()
        data["notes"].append({"text": text, "added": now_str})
        save_data(data)
        return "Note saved!"

    elif action == "note_list":
        notes = data.get("notes", [])
        if not notes:
            return "No notes saved yet."
        lines = ["<b>Your Notes</b>\n"]
        for i, n in enumerate(notes, 1):
            text = n["text"]
            # Use first line as title if multiline, else first 50 chars
            title = text.split("\n")[0][:60]
            if len(title) < len(text):
                title += "..."
            lines.append(f"{i}. {title}\n   <i>{n['added']}</i>")
        return "\n".join(lines)

    elif action == "note_delete":
        idx = action_data.get("index", 0) - 1
        notes = data.get("notes", [])
        if 0 <= idx < len(notes):
            removed = notes.pop(idx)
            save_data(data)
            return f"Deleted note: {removed['text']}"
        return "Couldn't find that note."

    elif action == "note_search":
        query = action_data.get("query", "").lower().strip()
        notes = data.get("notes", [])
        matches = [n for n in notes if query in n.get("text", "").lower()]
        if not matches:
            return f"No notes found matching: {query}"
        lines = [f"<b>Notes matching '{query}'</b>\n"]
        for i, n in enumerate(matches, 1):
            lines.append(f"{i}. {n['text']}\n   ({n['added']})")
        return "\n".join(lines)

    # REMINDERS
    elif action == "reminder_add":
        text = action_data.get("text", "").strip()
        time_str = action_data.get("time", "")
        import uuid as _uuid
        data["reminders"].append({"text": text, "time": time_str, "sent": False, "added": now_str, "id": str(_uuid.uuid4())[:8]})
        save_data(data)
        try:
            dt = datetime.datetime.fromisoformat(time_str)
            friendly = dt.strftime("%A, %B %-d at %-I:%M %p")
        except Exception:
            friendly = time_str
        return f"Reminder set: {text}\n{friendly}"

    elif action == "reminder_list":
        reminders = [r for r in data.get("reminders", []) if not r.get("sent")]
        if not reminders:
            return "No upcoming reminders."
        lines = ["Upcoming Reminders:\n"]
        for i, r in enumerate(reminders, 1):
            try:
                dt = datetime.datetime.fromisoformat(r["time"])
                friendly = dt.strftime("%a %b %-d at %-I:%M %p")
            except Exception:
                friendly = r["time"]
            lines.append(f"{i}. {r['text']} - {friendly}")
        return "\n".join(lines)

    elif action == "reminder_cancel":
        reminders = [r for r in data.get("reminders", []) if not r.get("sent")]
        idx = action_data.get("index", 0) - 1
        if 0 <= idx < len(reminders):
            item = reminders[idx]
            item["sent"] = True
            save_data(data)
            return f"Cancelled reminder: {item['text']}"
        return "Could not find that reminder."

    # EXPENSES
    elif action == "expense_add":
        amount = action_data.get("amount", 0)
        category = action_data.get("category", "Other")
        note = action_data.get("note", "")
        data["expenses"].append({
            "amount": amount,
            "category": category,
            "note": note,
            "date": now_str
        })
        save_data(data)
        return f"Logged: ${amount:.2f} on {category}{' - ' + note if note else ''}"

    elif action == "expense_list":
        expenses = data.get("expenses", [])
        if not expenses:
            return "No expenses logged yet."
        totals = {}
        total = 0
        for e in expenses:
            cat = e.get("category", "Other")
            amt = e.get("amount", 0)
            totals[cat] = totals.get(cat, 0) + amt
            total += amt
        lines = ["Expense Summary:\n"]
        for cat, amt in sorted(totals.items(), key=lambda x: -x[1]):
            lines.append(f"* {cat}: ${amt:.2f}")
        lines.append(f"\nTotal: ${total:.2f}")
        return "\n".join(lines)

    # MEALS
    elif action == "meal_add":
        meal = action_data.get("meal", "").strip()
        data["meals"].append({"meal": meal, "added": now_str})
        save_data(data)
        return f"Saved meal idea: {meal}"

    elif action == "meal_list":
        meals = data.get("meals", [])
        if not meals:
            return "No meal ideas saved yet. Tell me some meals you like!"
        lines = ["Your Meal Ideas:\n"]
        for i, m in enumerate(meals, 1):
            lines.append(f"{i}. {m['meal']}")
        return "\n".join(lines)

    elif action == "meal_plan":
        meals = data.get("meals", [])
        if len(meals) < 7:
            return f"You only have {len(meals)} meal ideas saved. Add more first, then I can plan a week!"
        import random
        picks = random.sample(meals, 7)
        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        lines = ["Meal Plan for the Week:\n"]
        for day, meal in zip(days, picks):
            lines.append(f"* {day}: {meal['meal']}")
        return "\n".join(lines)

    # WORKOUTS
    elif action == "workout_add":
        desc = action_data.get("description", "").strip()
        data["workouts"].append({"description": desc, "date": now_str})
        save_data(data)
        return f"Workout logged: {desc}"

    elif action == "workout_list":
        workouts = data.get("workouts", [])
        if not workouts:
            return "No workouts logged yet. Get after it!"
        lines = ["Recent Workouts:\n"]
        for w in reversed(workouts[-10:]):
            lines.append(f"* {w['date'][:10]}: {w['description']}")
        return "\n".join(lines)

    # GIFTS
    elif action == "gift_add":
        person = action_data.get("person", "").strip().lower()
        idea = action_data.get("idea", "").strip()
        occasion = action_data.get("occasion", "").strip()
        date = action_data.get("date", "").strip()
        if person not in data["gifts"]:
            data["gifts"][person] = []
        entry = {"idea": idea, "added": now_str}
        if occasion:
            entry["occasion"] = occasion
        if date:
            entry["date"] = date
        data["gifts"][person].append(entry)
        save_data(data)
        extra = f" for {occasion}" if occasion else ""
        date_str = f" (by {date})" if date else ""
        return f"Gift idea saved for {person.title()}{extra}{date_str}: {idea}"

    elif action == "gift_list":
        person = action_data.get("person", "").strip().lower()
        gifts = data.get("gifts", {})
        occasion_icons = {"birthday": "\U0001f382", "christmas": "\U0001f384",
                          "anniversary": "\U0001f496", "just because": "\U0001f381", "other": "\U0001f4dd"}
        if person and person in gifts:
            ideas = gifts[person]
            if not ideas:
                return f"No gift ideas for {person.title()} yet."
            lines = [f"\U0001f381 <b>Gift Ideas for {person.title()}</b>\n"]
            for i, g in enumerate(ideas, 1):
                icon = occasion_icons.get(g.get("occasion", ""), "\U0001f381")
                date_label = f" - by {g['date']}" if g.get("date") else ""
                occ_label = f" ({g['occasion']})" if g.get("occasion") else ""
                lines.append(f"{icon} {i}. {g['idea']}{occ_label}{date_label}")
            return "\n".join(lines)
        elif not person:
            if not gifts:
                return "No gift ideas saved yet."
            # Sort people by earliest upcoming gift date
            import datetime as _dt
            def _earliest(items):
                dates = [i.get("date","") for i in items if i.get("date")]
                return min(dates) if dates else "9999"
            sorted_people = sorted(gifts.items(), key=lambda x: _earliest(x[1]))
            lines = ["\U0001f381 <b>All Gift Ideas</b>\n"]
            for p, ideas in sorted_people:
                lines.append(f"\n<b>{p.title()}</b>")
                for g in ideas:
                    icon = occasion_icons.get(g.get("occasion", ""), "\U0001f381")
                    date_label = f" - by {g['date']}" if g.get("date") else ""
                    occ_label = f" ({g['occasion']})" if g.get("occasion") else ""
                    lines.append(f"  {icon} {g['idea']}{occ_label}{date_label}")
            return "\n".join(lines)
        return f"No gift ideas saved for {person.title()} yet."

    # SLEEP
    elif action == "sleep_add":
        hours = action_data.get("hours")
        quality = action_data.get("quality")
        entry = {"date": now_str[:10], "added": now_str}
        if hours is not None:
            try:
                entry["hours"] = float(hours)
            except (ValueError, TypeError):
                pass
        if quality:
            entry["quality"] = quality
        if "sleep_log" not in data:
            data["sleep_log"] = []
        data["sleep_log"].append(entry)
        save_data(data)
        parts = []
        if "hours" in entry:
            parts.append(f"{entry['hours']:.0f} hours")
        if "quality" in entry:
            q_emoji = {"great": "😴✨", "good": "😴", "okay": "😐", "poor": "😔"}.get(entry["quality"], "")
            parts.append(f"{entry['quality']} {q_emoji}")
        return "Sleep logged: " + (", ".join(parts) if parts else "noted")

    elif action == "sleep_list":
        log = data.get("sleep_log", [])
        if not log:
            return "No sleep logged yet."
        recent = log[-7:]
        lines = ["<b>Sleep Log (last 7 days)</b>\n"]
        for e in reversed(recent):
            parts = [e.get("date", "")]
            if "hours" in e:
                h = e["hours"]
                bar = "🟢" if h >= 7 else ("🟡" if h >= 5 else "🔴")
                parts.append(f"{bar} {h:.0f}h")
            if "quality" in e:
                parts.append(e["quality"])
            lines.append("  ".join(parts))
        total_h = [e["hours"] for e in recent if "hours" in e]
        if total_h:
            avg = sum(total_h) / len(total_h)
            lines.append(f"\nAvg: {avg:.1f}h / night")
        return "\n".join(lines)

    # MOOD
    elif action == "mood_add":
        mood = action_data.get("mood", "okay")
        note = action_data.get("note", "")
        if "mood_log" not in data:
            data["mood_log"] = []
        data["mood_log"].append({"date": now_str[:10], "added": now_str, "mood": mood, "note": note})
        save_data(data)
        mood_emoji = {"great": "🌟", "good": "😊", "okay": "😐", "tired": "😴", "stressed": "😤", "anxious": "😰", "low": "😔"}.get(mood, "")
        return f"Mood logged: {mood} {mood_emoji}"

    elif action == "mood_list":
        log = data.get("mood_log", [])
        if not log:
            return "No mood logged yet."
        recent = log[-7:]
        lines = ["<b>Mood Log (last 7 days)</b>\n"]
        emoji_map = {"great": "🌟", "good": "😊", "okay": "😐", "tired": "😴", "stressed": "😤", "anxious": "😰", "low": "😔"}
        for e in reversed(recent):
            em = emoji_map.get(e.get("mood", ""), "")
            note = f" - {e['note']}" if e.get("note") else ""
            lines.append(f"{e.get('date', '')}  {em} {e.get('mood', '')}{note}")
        return "\n".join(lines)

    return None


# Calendar action handler

async def handle_calendar_action(action_data, update):
    action = action_data.get("action")

    if action == "create":
        service = get_calendar_service()
        if not service:
            return "I would love to add that, but calendar is not connected yet. Use /auth to connect."
        recurrence_rule = action_data.get("recurrence", "")
        recurrence = [recurrence_rule] if recurrence_rule else None
        event = create_event(
            title=action_data.get("title", "Event"),
            start=action_data.get("start"),
            end=action_data.get("end"),
            description=action_data.get("description", ""),
            recurrence=recurrence
        )
        if event:
            title = action_data.get("title", "Event")
            rec_label = ""
            if recurrence_rule:
                if "WEEKLY" in recurrence_rule:
                    rec_label = " (repeating weekly)"
                elif "DAILY" in recurrence_rule:
                    rec_label = " (repeating daily)"
                elif "MONTHLY" in recurrence_rule:
                    rec_label = " (repeating monthly)"
            return f"Added to your calendar: {title}{rec_label}"
        else:
            return "Could not add the event - something went wrong."

    elif action == "list":
        service = get_calendar_service()
        if not service:
            return "Calendar not connected. Use /auth to connect."
        days = action_data.get("days", 7)
        events = list_events(days=days)
        if not events:
            return "No upcoming events found."
        lines = ["Coming up:\n"]
        for e in events:
            start = e["start"].get("dateTime", e["start"].get("date", ""))
            if "T" in start:
                dt = datetime.datetime.fromisoformat(start.replace("Z", "+00:00"))
                time_str = dt.strftime("%a %b %-d at %-I:%M %p")
            else:
                dt = datetime.datetime.fromisoformat(start)
                time_str = dt.strftime("%a %b %-d (all day)")
            lines.append(f"* {e.get('summary', 'No title')} - {time_str}")
        return "\n".join(lines)

    return None


# Reminder checker

async def check_reminders(context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    now = datetime.datetime.now()
    changed = False
    for r in data.get("reminders", []):
        if r.get("sent"):
            continue
        try:
            remind_time = datetime.datetime.fromisoformat(r["time"])
            if now >= remind_time:
                reminder_id = r.get("id", "")
                reminder_text = f"Reminder: {r['text']}"
                await context.bot.send_message(chat_id=ALLOWED_USER_ID, text=reminder_text)
                r["sent"] = True
                changed = True
        except Exception as e:
            logger.error(f"Reminder error: {e}")
    if changed:
        save_data(data)


# Message utilities

async def send_long_message(message_obj, text, parse_mode=None):
    """Split and send messages that exceed Telegram 4096 char limit."""
    MAX_LEN = 4000
    if len(text) <= MAX_LEN:
        await message_obj.reply_text(text, parse_mode=parse_mode)
        return
    chunks = []
    while text:
        if len(text) <= MAX_LEN:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, MAX_LEN)
        if split_at == -1:
            split_at = MAX_LEN
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    for chunk in chunks:
        await message_obj.reply_text(chunk, parse_mode=parse_mode)


# Rate limiting

_rate_counters = {}

def check_rate_limit(user_id):
    """Returns True if user is within rate limit (30 msgs/60s)."""
    import time
    now = time.time()
    window = 60
    limit = 30
    if user_id not in _rate_counters:
        _rate_counters[user_id] = []
    _rate_counters[user_id] = [t for t in _rate_counters[user_id] if now - t < window]
    if len(_rate_counters[user_id]) >= limit:
        return False
    _rate_counters[user_id].append(now)
    return True


# Phase 5 - Daily Briefing helpers

def get_weather_slc():
    cached = cache_get("weather_slc", max_age_seconds=300)
    if cached:
        return cached
    try:
        url = (
            "https://api.open-meteo.com/v1/forecast"
            "?latitude=40.7608&longitude=-111.8910"
            "&current=temperature_2m,apparent_temperature,precipitation,weathercode,windspeed_10m"
            "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode"
            "&temperature_unit=fahrenheit"
            "&windspeed_unit=mph"
            "&precipitation_unit=inch"
            "&timezone=America%2FDenver"
            "&forecast_days=2"
        )
        resp = requests.get(url, timeout=10)
        data = resp.json()
        cur = data["current"]
        daily = data["daily"]
        wmo_codes = {
            0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
            45: "Foggy", 48: "Icy fog",
            51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
            61: "Light rain", 63: "Rain", 65: "Heavy rain",
            71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains",
            80: "Rain showers", 81: "Showers", 82: "Heavy showers",
            85: "Snow showers", 86: "Heavy snow showers",
            95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Severe thunderstorm",
        }
        code = cur.get("weathercode", 0)
        description = wmo_codes.get(code, "Unknown")
        temp_now = round(cur["temperature_2m"])
        feels_like = round(cur["apparent_temperature"])
        wind = round(cur["windspeed_10m"])
        high = round(daily["temperature_2m_max"][0])
        low = round(daily["temperature_2m_min"][0])
        precip = round(daily["precipitation_sum"][0], 2)
        # Pick emoji based on weather code
        if code == 0:
            w_emoji = "☀️"
        elif code in (1, 2):
            w_emoji = "🌤"
        elif code == 3:
            w_emoji = "☁️"
        elif code in (45, 48):
            w_emoji = "🌫"
        elif code in (51, 53, 55, 61, 63, 65, 80, 81, 82):
            w_emoji = "🌧"
        elif code in (71, 73, 75, 77, 85, 86):
            w_emoji = "❄️"
        elif code in (95, 96, 99):
            w_emoji = "⛈"
        else:
            w_emoji = "🌤"
        lines = [
            f"{w_emoji} <b>Weather - Salt Lake City</b>",
            f"Now: {temp_now}F (feels {feels_like}F) - {description}",
            f"High: {high}F  |  Low: {low}F  |  Wind: {wind} mph",
        ]
        if precip > 0:
            lines.append(f"Precip: {precip} in")
        result = "\n".join(lines)
        cache_set("weather_slc", result)
        return result
    except Exception as e:
        return f"Weather unavailable ({str(e)[:50]})"


def get_todays_calendar_events_briefing(service):
    try:
        tz = pytz.timezone("America/Denver")
        now = datetime.datetime.now(tz)
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=0)
        all_events = []
        try:
            calendars = service.calendarList().list().execute().get("items", [])
            for cal in calendars:
                try:
                    result = service.events().list(
                        calendarId=cal["id"],
                        timeMin=start_of_day.isoformat(),
                        timeMax=end_of_day.isoformat(),
                        singleEvents=True,
                        orderBy="startTime",
                    ).execute()
                    for event in result.get("items", []):
                        event["_calendar_name"] = cal.get("summary", "")
                        all_events.append(event)
                except Exception:
                    pass
        except Exception:
            result = service.events().list(
                calendarId="primary",
                timeMin=start_of_day.isoformat(),
                timeMax=end_of_day.isoformat(),
                singleEvents=True,
                orderBy="startTime",
            ).execute()
            all_events = result.get("items", [])
        all_events.sort(key=lambda e: e["start"].get("dateTime", e["start"].get("date", "")))
        if not all_events:
            return "Calendar - No events today"
        lines = ["📅 <b>Todays Calendar</b>"]
        for event in all_events:
            start = event["start"].get("dateTime", event["start"].get("date", ""))
            if "T" in start:
                dt = datetime.datetime.fromisoformat(start)
                if dt.tzinfo is None:
                    dt = tz.localize(dt)
                else:
                    dt = dt.astimezone(tz)
                time_str = dt.strftime("%-I:%M %p")
            else:
                time_str = "All day"
            title = event.get("summary", "Untitled")
            cal_name = event.get("_calendar_name", "")
            label = f"  * {time_str} - {title}"
            if cal_name and cal_name.lower() not in ("ty wass", "primary"):
                label += f" ({cal_name})"
            lines.append(label)
        return "\n".join(lines)
    except Exception as e:
        return f"Calendar unavailable ({str(e)[:60]})"


def get_briefing_todos(user_data):
    todos = [t for t in user_data.get("todos", []) if not t.get("done")]
    if not todos:
        return "✅ <b>To-Dos</b> - All clear!"
    priority_order = {"high": 0, "normal": 1, "low": 2}
    todos = sorted(todos, key=lambda t: priority_order.get(t.get("priority", "normal"), 1))
    high = [t for t in todos if t.get("priority") == "high"]
    rest = [t for t in todos if t.get("priority") != "high"]
    lines = ["✅ <b>To-Dos</b>"]
    for item in high:
        lines.append(f"  🔴 {item['text']}")
    shown = len(high)
    for item in rest[:max(0, 8 - shown)]:
        lines.append(f"  * {item['text']}")
    remaining = len(todos) - min(len(todos), 8)
    if remaining > 0:
        lines.append(f"  ...and {remaining} more")
    return "\n".join(lines)


def get_briefing_shopping(user_data):
    lists = user_data.get("shopping_lists", {})
    # Fallback: check old shopping key too
    old = [s for s in user_data.get("shopping", []) if not s.get("done")]
    all_items = old[:]
    for lst_key in ("grocery", "household", "baby", "wishlist"):
        all_items += [i for i in lists.get(lst_key, []) if not i.get("done")]
    if not all_items:
        return None
    lines = ["🛒 <b>Shopping</b>"]
    for item in all_items[:8]:
        lines.append(f"  * {item['text']}")
    if len(all_items) > 8:
        lines.append(f"  ...and {len(all_items) - 8} more")
    return "\n".join(lines)


def get_briefing_reminders(user_data):
    try:
        tz = pytz.timezone("America/Denver")
        now = datetime.datetime.now(tz)
        today_str = now.strftime("%Y-%m-%d")
        reminders = user_data.get("reminders", [])
        due_today = []
        for r in reminders:
            if r.get("sent"):
                continue
            remind_time = r.get("time", "")
            if remind_time.startswith(today_str):
                due_today.append(r.get("text", "Reminder"))
        if not due_today:
            return None
        lines = ["⏰ <b>Reminders Due Today</b>"]
        for r in due_today:
            lines.append(f"  * {r}")
        return "\n".join(lines)
    except Exception:
        return None


def get_briefing_workouts(user_data):
    try:
        workouts = user_data.get("workouts", [])
        if not workouts:
            return None
        recent = workouts[-5:]
        lines = ["💪 <b>Recent Workouts</b>"]
        for w in reversed(recent):
            lines.append(f"  * {w['date'][:10]}: {w['description']}")
        return "\n".join(lines)
    except Exception:
        return None


def get_briefing_expenses(user_data):
    try:
        tz = pytz.timezone("America/Denver")
        now = datetime.datetime.now(tz)
        current_month = now.strftime("%Y-%m")
        expenses = user_data.get("expenses", [])
        month_expenses = [e for e in expenses if e.get("date", "").startswith(current_month)]
        if not month_expenses:
            return None
        total = 0
        for e in month_expenses:
            try:
                total += float(e.get("amount", 0))
            except (ValueError, TypeError):
                pass
        month_label = now.strftime("%B")
        return f"Expenses ({month_label}) - {len(month_expenses)} entries, ${total:.2f} total"
    except Exception:
        return None


# Scheduled morning briefing job

async def send_scheduled_briefing(context: ContextTypes.DEFAULT_TYPE):
    user_data = load_data()
    cal_service = None
    try:
        cal_service = get_calendar_service()
    except Exception:
        pass
    sections = await build_briefing_sections(user_data, cal_service)
    for section in sections:
        await context.bot.send_message(
            chat_id=ALLOWED_USER_ID,
            text=section,
            parse_mode="HTML"
        )


# Commands

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    await update.message.reply_text(
        "Hey! I am your personal assistant.\n\n"
        "Calendar: /today /week /auth\n"
        "Lists: just tell me naturally!\n\n"
        "Examples:\n"
        "  Add milk to shopping list\n"
        "  Remind me at 3pm to call mom\n"
        "  Spent $45 on groceries\n"
        "  Log a 30 min run\n"
        "  Gift idea for Sarah: silk scarf\n"
        "  Note: password is abc123\n\n"
        "Commands:\n"
        "/briefing - Morning briefing\n"
        "/todos - See to-do list\n"
        "/shopping - See shopping list\n"
        "/notes - See saved notes\n"
        "/expenses - See spending summary\n"
        "/workouts - See workout log\n"
        "/gifts - See gift ideas\n"
        "/reminders - See upcoming reminders\n"
        "/clear - Clear conversation memory"
    )


async def auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    creds_data = json.loads(GOOGLE_CREDENTIALS)
    flow = Flow.from_client_config(creds_data, scopes=SCOPES)
    flow.redirect_uri = "http://localhost"
    auth_url, state = flow.authorization_url(access_type="offline", prompt="consent")
    auth_state = {"state": state, "code_verifier": flow.code_verifier}
    with open(AUTH_STATE_FILE, "w") as f:
        json.dump(auth_state, f)
    await update.message.reply_text(
        "Click this link and sign in with Google:\n\n"
        f"{auth_url}\n\n"
        "After approving, your browser will show an error page - that is normal.\n\n"
        "Find the part in the address bar that says code= and copy everything after it until &scope\n\n"
        "Send it like this:\n/code 4/0Afr...(your full code here)"
    )


async def code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    if not context.args:
        await update.message.reply_text("Paste the code after /code\n\nExample: /code 4/0Afr...")
        return
    auth_code = " ".join(context.args).strip()
    if not os.path.exists(AUTH_STATE_FILE):
        await update.message.reply_text("No auth session found. Please type /auth first.")
        return
    with open(AUTH_STATE_FILE, "r") as f:
        auth_state = json.load(f)
    try:
        creds_data = json.loads(GOOGLE_CREDENTIALS)
        flow = Flow.from_client_config(creds_data, scopes=SCOPES, state=auth_state.get("state"))
        flow.redirect_uri = "http://localhost"
        flow.code_verifier = auth_state.get("code_verifier")
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
        flow.fetch_token(code=auth_code)
        with open(TOKEN_FILE, "w") as f:
            f.write(flow.credentials.to_json())
        os.remove(AUTH_STATE_FILE)
        await update.message.reply_text("Google Calendar connected!\n\nTry /week to see upcoming events.")
    except Exception as e:
        logger.error(f"Auth error: {e}")
        await update.message.reply_text(f"That did not work - {str(e)[:120]}\n\nType /auth to try again.")


async def today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    try:
        weather = get_weather_slc()
        await update.message.reply_text(weather, parse_mode="HTML")
    except Exception:
        pass
    await show_events(update, days=1, label="today")


async def week(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    await show_events(update, days=7, label="this week")


async def show_events(update, days, label):
    service = get_calendar_service()
    if not service:
        await update.message.reply_text("Calendar not connected yet. Use /auth to connect.")
        return
    events = list_events(days=days)
    if not events:
        await update.message.reply_text(f"No events {label}.")
        return
    # Count events per day PER CALENDAR to flag busy days
    from collections import defaultdict as _dd
    # key: (day, calendar_name) -> count
    day_cal_counts = _dd(int)
    for e in events:
        start = e["start"].get("dateTime", e["start"].get("date", ""))
        cal_name = e.get("_calendar_name", "Personal")
        day_cal_counts[(start[:10], cal_name)] += 1
    lines = [f"<b>Your events {label}</b>\n"]
    for e in events:
        start = e["start"].get("dateTime", e["start"].get("date", ""))
        if "T" in start:
            dt = datetime.datetime.fromisoformat(start.replace("Z", "+00:00"))
            time_str = dt.strftime("%a %b %-d at %-I:%M %p")
        else:
            dt = datetime.datetime.fromisoformat(start)
            time_str = dt.strftime("%a %b %-d (all day)")
        cal_name = e.get("_calendar_name", "Personal")
        busy_tag = ""
        if day_cal_counts[(start[:10], cal_name)] >= 3:
            busy_tag = f" <b>[Busy day - {cal_name}]</b>"
        lines.append(f"* {e.get('summary', 'No title')} - {time_str}{busy_tag}")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def briefing_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    await update.message.reply_text("Building your briefing, one moment...")
    user_data = load_data()
    cal_service = None
    try:
        cal_service = get_calendar_service()
    except Exception:
        pass
    sections = await build_briefing_sections(user_data, cal_service)
    for section in sections:
        await update.message.reply_text(section, parse_mode="HTML")


async def cmd_todos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    reply = await handle_data_action({"action": "todo_list"})
    await update.message.reply_text(reply, parse_mode="HTML")

async def cmd_shopping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    reply = await handle_data_action({"action": "shop_list"})
    await update.message.reply_text(reply, parse_mode="HTML")

async def cmd_notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    reply = await handle_data_action({"action": "note_list"})
    await update.message.reply_text(reply, parse_mode="HTML")

async def cmd_expenses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    reply = await handle_data_action({"action": "expense_list"})
    await update.message.reply_text(reply)

async def cmd_workouts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    reply = await handle_data_action({"action": "workout_list"})
    await update.message.reply_text(reply)

async def cmd_gifts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    reply = await handle_data_action({"action": "gift_list", "person": ""})
    await update.message.reply_text(reply, parse_mode="HTML")

async def cmd_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    reply = await handle_data_action({"action": "reminder_list"})
    await update.message.reply_text(reply)

async def cmd_sleep(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    reply = await handle_data_action({"action": "sleep_list"})
    await update.message.reply_text(reply, parse_mode="HTML")

async def cmd_mood(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    reply = await handle_data_action({"action": "mood_list"})
    await update.message.reply_text(reply, parse_mode="HTML")

async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    global ask_history
    conversation_history.clear()
    ask_history = []
    await update.message.reply_text("Memory cleared - starting fresh!")


# Main message handler

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ALLOWED_USER_ID:
        return

    user_message = update.message.text or ""
    if not user_message.strip():
        return
    _orig_msg = user_message  # preserve original case for $ detection

    if not check_rate_limit(user_id):
        await update.message.reply_text("Slow down a bit - try again in a minute.")
        return

    logger.info(f"Received: {user_message}")

    # Brain dump mode check
    if context.user_data.get("brain_dump_mode"):
        await process_brain_dump(update, context)
        return

    # Briefing keyword trigger
    text_lower = user_message.lower()
    if any(phrase in text_lower for phrase in ["morning briefing", "daily briefing", "give me my briefing", "my briefing"]):
        await briefing_command(update, context)
        return

    # Brain dump keyword trigger
    if any(phrase in text_lower for phrase in ["brain dump", "braindump", "quick capture", "dump everything"]):
        await brain_dump_command(update, context)
        return

    # Pending photo note confirmation
    if context.user_data.get("pending_photo_note") and text_lower in ("yes", "yeah", "yep", "sure", "save it", "yes please", "do it", "save"):
        note_text = context.user_data.pop("pending_photo_note", "")
        # Extract text after NOTE_DETECTED:
        import re as _re2
        _note_match = _re2.search(r"NOTE_DETECTED:(.*?)(?:Would you|$)", note_text, _re2.DOTALL)
        _extracted = _note_match.group(1).strip() if _note_match else note_text[:500]
        reply = await handle_data_action({"action": "note_add", "text": f"[Photo note] {_extracted}"})
        await update.message.reply_text(reply)
        return

    # Pending photo meal confirmation
    if context.user_data.get("pending_photo_meal") and text_lower in ("yes", "yeah", "yep", "sure", "save it", "yes please", "do it", "save"):
        meal_text = context.user_data.pop("pending_photo_meal", "")
        import re as _re3
        _meals = _re3.findall(r"MEAL_DETECTED:(.*?)(?:Would you|$)", meal_text, _re3.DOTALL)
        _meal_raw = _meals[0] if _meals else ""
        _meal_lines = [l.strip() for l in _meal_raw.split("\n") if l.strip() and not l.startswith("-")]
        for _m in _meal_lines[:5]:
            await handle_data_action({"action": "meal_add", "meal": _m})
            saved.append(_m)
        await update.message.reply_text(f"Saved {len(saved)} meals to your list!")
        return

    # Pending calendar event confirmation (from photo)
    if context.user_data.get("pending_calendar_event") and text_lower in ("yes", "yeah", "yep", "sure", "add it", "yes please", "do it"):
        event_text = context.user_data.pop("pending_calendar_event", "")
        service = get_calendar_service()
        if not service:
            await update.message.reply_text("Calendar not connected. Use /auth first.")
            return
        parse_prompt = (
            "Extract calendar event details from this text and return ONLY a JSON object with keys: "
            "title, start (YYYY-MM-DDTHH:MM:00), end (YYYY-MM-DDTHH:MM:00), location, description. "
            "Use reasonable defaults if some fields are missing. "
            f"Text: {event_text}"
        )
        try:
            parse_resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": parse_prompt}],
                max_tokens=200, temperature=0
            )
            import json as _json
            raw = parse_resp.choices[0].message.content.strip()
            raw = raw.replace("```json", "").replace("```", "").strip()
            event_data = _json.loads(raw)
            event = create_event(
                title=event_data.get("title", "Event"),
                start=event_data.get("start", ""),
                end=event_data.get("end", ""),
                description=event_data.get("description", "") + " " + event_data.get("location", "")
            )
            if event:
                title = event_data.get("title", "Event")
                title = event_data.get("title", "Event")
                msg = "Added to your calendar: " + title + ". Note: added as a single event. For recurring events, open Google Calendar to set the repeat."
                await update.message.reply_text(msg)
            else:
                await update.message.reply_text("Could not add the event. Please try using /auth to reconnect.")
        except Exception as e:
            logger.error(f"Calendar event from photo error: {e}")
            await update.message.reply_text("Had trouble adding that event. Try describing it manually.")
        return

    # Expense quick-add: "$45 groceries" or "$45.50 gas"
    _orig_msg = update.message.text or ''
    _dollar_match = _re.match(r'^[$]([0-9]+(?:[.][0-9]{1,2})?) (.+)$', _orig_msg.strip())
    if _dollar_match:
        _amount = float(_dollar_match.group(1))
        _category = _dollar_match.group(2).strip().title()
        reply = await handle_data_action({"action": "expense_add", "amount": _amount, "category": _category, "note": ""})
        await update.message.reply_text(reply)
        return

    # Direct gift idea bypass: "gift idea for [person]: [idea]"
    import re as _re_g
    _gift_match = _re_g.match(r'^gift idea for ([^:]+): (.+)$', user_message.strip(), _re_g.IGNORECASE)
    if _gift_match:
        _gp = _gift_match.group(1).strip()
        _gi = _gift_match.group(2).strip()
        # Check for occasion keywords
        _occ = ""
        for _kw, _ov in [("birthday","birthday"),("christmas","christmas"),("anniversary","anniversary"),("just because","just because")]:
            if _kw in user_message.lower():
                _occ = _ov
                break
        reply = await handle_data_action({"action": "gift_add", "person": _gp, "idea": _gi, "occasion": _occ, "date": ""})
        await update.message.reply_text(reply)
        return

    # Direct shopping list bypass: "add X to grocery/baby/household/wishlist"
    _shop_patterns = [
        (_re_g.match(r'^add (.+) to (?:my )?grocery(?: list)?$', text_lower.strip()), "grocery"),
        (_re_g.match(r'^add (.+) to (?:my )?(?:baby|luna)(?: list)?$', text_lower.strip()), "baby"),
        (_re_g.match(r'^add (.+) to (?:my )?household(?: list)?$', text_lower.strip()), "household"),
        (_re_g.match(r'^add (.+) to (?:my )?wishlist$', text_lower.strip()), "wishlist"),
        (_re_g.match(r'^add (.+) to (?:my )?shopping list$', text_lower.strip()), "grocery"),
    ]
    for _sm, _sl in _shop_patterns:
        if _sm:
            _si = _sm.group(1).strip()
            reply = await handle_data_action({"action": "shop_add", "item": _si, "list": _sl})
            await update.message.reply_text(reply)
            return

    # Direct todo delete detection - bypass GPT to avoid calendar misrouting
    import re as _re
    _stripped = text_lower.strip()
    # Undo last delete
    if _stripped in ("undo", "undo delete", "undo last delete", "restore todos", "restore last deleted"):
        _undo_items = context.user_data.get("last_deleted_todos", [])
        if not _undo_items:
            await update.message.reply_text("Nothing to undo.")
            return
        _data = load_data()
        for _item in _undo_items:
            _data["todos"].append(_item)
        save_data(_data)
        context.user_data["last_deleted_todos"] = []
        _names = ", ".join(i["text"] for i in _undo_items)
        await update.message.reply_text(f"Restored: {_names}\n\nType /todos to see your updated list.")
        return
    # Extract all numbers from "delete todo(s) 1, 2, 3 and 4" patterns
    if _re.match(r'^(?:delete|remove) todos?', _stripped):
        _nums = [int(n) for n in _re.findall(r'\d+', _stripped)]
        if _nums:
            _data = load_data()
            _active = [t for t in _data.get("todos", []) if not t.get("done")]
            _to_delete = []
            for _n in sorted(set(_nums)):
                _i = _n - 1
                if 0 <= _i < len(_active):
                    _to_delete.append(_active[_i])
            if not _to_delete:
                await update.message.reply_text("Could not find those items. Type /todos to see current numbers.")
                return
            # Save for undo before deleting
            context.user_data["last_deleted_todos"] = list(_to_delete)
            _ids = {id(t) for t in _to_delete}
            _data["todos"] = [t for t in _data["todos"] if id(t) not in _ids]
            save_data(_data)
            _names = ", ".join(t["text"] for t in _to_delete)
            await update.message.reply_text(f"Deleted: {_names}\n\nSay \"undo\" within this session to restore.")
            return

    # Shopping multi-mark-done bypass
    _shop_got = _re.match(r'^(got|bought|picked up|checked off) (.+)$', _stripped)
    if _shop_got:
        _items_text = _shop_got.group(2)
        _nums = [int(n) for n in _re.findall(r'\d+', _items_text)]
        if _nums:
            _data = load_data()
            _shop = _data.get("shopping", [])
            _active_shop = [t for t in _shop if not t.get("done")]
            _got_names = []
            for _n in _nums:
                _i = _n - 1
                if 0 <= _i < len(_active_shop):
                    _active_shop[_i]["done"] = True
                    _got_names.append(_active_shop[_i]["text"])
            if _got_names:
                save_data(_data)
                context.user_data["last_shop_done"] = _nums
                await update.message.reply_text("Got it: " + ", ".join(_got_names) + "\n\nSay \"undo shopping\" to unmark.")
                return

    # Shopping undo
    if _stripped in ("undo shopping", "unmark shopping", "undo shop"):
        _data = load_data()
        _last = context.user_data.get("last_shop_done", [])
        if not _last:
            await update.message.reply_text("Nothing to undo for shopping.")
            return
        _shop = _data.get("shopping", [])
        _active_shop = [t for t in _shop if not t.get("done")]
        _done_shop = [t for t in _shop if t.get("done")]
        _restored = []
        for _n in _last:
            _i = _n - 1
            if 0 <= _i < len(_done_shop):
                _done_shop[_i]["done"] = False
                _restored.append(_done_shop[_i]["text"])
        if _restored:
            save_data(_data)
            context.user_data["last_shop_done"] = []
            await update.message.reply_text("Unmarked: " + ", ".join(_restored))
        else:
            await update.message.reply_text("Nothing to undo.")
        return

    # /done shortcut: "done 3" marks todo 3 as complete
    import re as _re
    _done_match = _re.match(r'^done [0-9]+$', text_lower.strip())
    if _done_match:
        _done_idx = int(text_lower.strip().split()[-1])
        _data = load_data()
        _active = [t for t in _data.get("todos", []) if not t.get("done")]
        if 0 <= _done_idx - 1 < len(_active):
            _active[_done_idx - 1]["done"] = True
            save_data(_data)
            await update.message.reply_text(f"Done: {_active[_done_idx - 1]['text']}")
        else:
            await update.message.reply_text("Could not find that todo.")
        return

    # "add anyway" override for dedup warning
    if text_lower.strip() in ("add anyway", "add it anyway", "yes add it", "add it"):
        if context.user_data.get("pending_todo_add"):
            _pend = context.user_data.pop("pending_todo_add")
            _data = load_data()
            _data["todos"].append({"text": _pend["text"], "done": False,
                                   "added": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                                   "priority": _pend.get("priority", "normal")})
            save_data(_data)
            await update.message.reply_text(f"Added: {_pend['text']}")
            return

    # Direct priority todo detection - ensure priority is passed correctly
    _high_patterns = ["high priority:", "urgent:", "high priority -", "urgent -"]
    _low_patterns = ["low priority:", "low priority -"]
    _detected_priority = None
    _todo_text = text_lower.strip()
    for pat in _high_patterns:
        if _todo_text.startswith(pat):
            _detected_priority = "high"
            _todo_text = user_message[len(pat):].strip()
            break
    if not _detected_priority:
        for pat in _low_patterns:
            if _todo_text.startswith(pat):
                _detected_priority = "low"
                _todo_text = user_message[len(pat):].strip()
                break
    if _detected_priority and _todo_text:
        reply = await handle_data_action({"action": "todo_add", "item": _todo_text, "priority": _detected_priority})
        await update.message.reply_text(reply, parse_mode="HTML")
        return

    # Habit logging check - skip if message is about scheduling/planning (not completing)
    scheduling_words = ["schedule", "remind me", "every monday", "every tuesday",
                        "every wednesday", "every thursday", "every friday",
                        "every saturday", "every sunday", "every day", "every week",
                        "set a reminder", "add to calendar", "create a reminder",
                        "plan to", "going to", "will do", "want to", "need to"]
    is_scheduling = any(w in text_lower for w in scheduling_words)
    data = load_data()
    if not is_scheduling:
        habit_response = check_habit_from_message(text_lower, data)
        if habit_response:
            await update.message.reply_text(habit_response)
            audit_log(f"HABIT user={user_id}")
            return

    # Load conversation from persistent storage, merge with in-memory
    if user_id not in conversation_history:
        saved = load_conversation()
        conversation_history[user_id] = saved.get(str(user_id), [])

    conversation_history[user_id].append({"role": "user", "content": user_message[:2000]})
    if len(conversation_history[user_id]) > 20:
        conversation_history[user_id] = conversation_history[user_id][-20:]

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        now = datetime.datetime.now().strftime("%A, %B %-d, %Y, %-I:%M %p")
        # Add contact context if any known contacts
        contacts = load_contacts()
        contact_ctx = ""
        if contacts:
            contact_ctx = "\n\nKnown contacts:\n"
            for name, facts in list(contacts.items())[:10]:
                facts_list = facts if isinstance(facts, list) else [facts]
                contact_ctx += f"- {name}: {'; '.join(facts_list[:3])}\n"
        system = SYSTEM_PROMPT + CONTACT_SYSTEM_ADDON + f"\n\nCurrent date/time: {now} (Mountain Time)" + contact_ctx
        messages = [{"role": "system", "content": system}] + conversation_history[user_id]

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=900,
            temperature=0.7
        )

        assistant_message = response.choices[0].message.content
        reply_lines = []

        for line in assistant_message.split("\n"):
            if line.startswith("CALENDAR_ACTION:"):
                json_str = line.replace("CALENDAR_ACTION:", "").strip()
                try:
                    action_data = json.loads(json_str)
                    cal_reply = await handle_calendar_action(action_data, update)
                    if cal_reply:
                        reply_lines.append(cal_reply)
                except Exception as e:
                    logger.error(f"Calendar action error: {e}")
            elif line.startswith("DATA_ACTION:"):
                json_str = line.replace("DATA_ACTION:", "").strip()
                try:
                    action_data = json.loads(json_str)
                    data_reply = await handle_data_action(action_data)
                    if data_reply:
                        reply_lines.append(data_reply)
                        if action_data.get("action") in ("todo_list", "sleep_list", "mood_list", "habit_list"):
                            context.user_data["_last_html_reply"] = True
                except Exception as e:
                    logger.error(f"Data action error: {e}")
            elif line.startswith("CONTACT_ACTION:"):
                json_str = line.replace("CONTACT_ACTION:", "").strip()
                try:
                    contact_data = json.loads(json_str)
                    contacts = load_contacts()
                    name = contact_data.get("name", "").title()
                    fact = contact_data.get("fact", "").strip()
                    if name and fact:
                        if name not in contacts:
                            contacts[name] = []
                        if isinstance(contacts[name], str):
                            contacts[name] = [contacts[name]]
                        contacts[name].append(fact)
                        save_contacts(contacts)
                        reply_lines.append(f"Got it! Saved note about {name}: {fact}")
                        audit_log(f"CONTACT_SAVED {name}")
                except Exception as e:
                    logger.error(f"Contact action error: {e}")
            else:
                if line.strip():
                    reply_lines.append(line)

        final_reply = "\n".join(reply_lines).strip()
        if not final_reply:
            final_reply = "Done!"

        conversation_history[user_id].append({"role": "assistant", "content": final_reply})
        # Persist conversation to disk
        all_history = load_conversation()
        all_history[str(user_id)] = conversation_history[user_id]
        save_conversation(all_history)
        audit_log(f"MSG user={user_id} len={len(user_message)}")
        await send_long_message(update.message, final_reply)

    except Exception as e:
        logger.error(f"Error: {e}")
        audit_log(f"ERROR {str(e)[:100]}")
        try:
            await context.bot.send_message(
                chat_id=ALLOWED_USER_ID,
                text=f"Bot error alert: {str(e)[:200]}"
            )
        except Exception:
            pass
        await update.message.reply_text("Sorry, ran into an issue. Please try again.")


# Phase 6 - Sports recap helpers

MY_TEAMS = {
    "nba": ["celtics", "jazz"],
    "nfl": ["patriots"],
    "mlb": ["red sox"],
}

ESPN_URLS = {
    "nba": "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
    "nfl": "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
    "mlb": "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard",
}

LEAGUE_LABELS = {"nba": "NBA", "nfl": "NFL", "mlb": "MLB"}


def fetch_espn_scores(league, date_str):
    cache_key = f"espn_{league}_{date_str}"
    cached = cache_get(cache_key, max_age_seconds=300)
    if cached is not None:
        return cached
    try:
        url = ESPN_URLS[league]
        resp = requests.get(url, params={"dates": date_str}, timeout=10)
        data = resp.json()
        games = []
        for event in data.get("events", []):
            comp = event.get("competitions", [{}])[0]
            competitors = comp.get("competitors", [])
            if len(competitors) < 2:
                continue
            home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
            away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])
            home_name = home.get("team", {}).get("displayName", "")
            away_name = away.get("team", {}).get("displayName", "")
            home_score = home.get("score", "")
            away_score = away.get("score", "")
            status = event.get("status", {}).get("type", {}).get("description", "")
            winner = ""
            if home.get("winner"):
                winner = home_name
            elif away.get("winner"):
                winner = away_name
            leaders = []
            for leader_cat in comp.get("leaders", []):
                for leader in leader_cat.get("leaders", [])[:1]:
                    name = leader.get("athlete", {}).get("displayName", "")
                    stat = leader.get("displayValue", "")
                    cat = leader_cat.get("shortDisplayName", "")
                    if name and stat:
                        leaders.append(f"{name} {stat} {cat}")
            games.append({
                "home": home_name, "away": away_name,
                "home_score": home_score, "away_score": away_score,
                "status": status, "winner": winner,
                "leaders": leaders[:2],
            })
        cache_set(cache_key, games)
        return games
    except Exception as e:
        logger.error(f"ESPN fetch error {league}: {e}")
        return []


def format_sports_recap(date_label="yesterday", my_teams_only=False):
    tz = pytz.timezone("America/Denver")
    now = datetime.datetime.now(tz)
    if date_label == "yesterday":
        target = now - datetime.timedelta(days=1)
    else:
        target = now
    date_str = target.strftime("%Y%m%d")
    sections = []
    for league in ["nba", "nfl", "mlb"]:
        games = fetch_espn_scores(league, date_str)
        if not games:
            continue
        my_team_names = MY_TEAMS[league]
        my_games = []
        other_games = []
        for g in games:
            is_my_team = any(
                t in g["home"].lower() or t in g["away"].lower()
                for t in my_team_names
            )
            if is_my_team:
                my_games.append(g)
            else:
                other_games.append(g)
        if my_teams_only and not my_games:
            continue
        games_to_show = my_games if my_teams_only else (my_games + other_games)
        league_lines = [f"{LEAGUE_LABELS[league]}"]
        for g in games_to_show:
            score_line = f"  {g['away']} {g['away_score']} @ {g['home']} {g['home_score']}"
            if g["winner"]:
                score_line += f" - {g['winner']} win"
            league_lines.append(score_line)
            for leader in g["leaders"]:
                league_lines.append(f"    {leader}")
        if len(league_lines) > 1:
            sections.append("\n".join(league_lines))
    if not sections:
        return None
    # Sleep summary
    sleep_log = user_data.get("sleep_log", [])
    week_sleep = [e for e in sleep_log if e.get("date", "") >= week_start_str]
    if week_sleep:
        hours_list = [e["hours"] for e in week_sleep if "hours" in e]
        if hours_list:
            avg_sleep = sum(hours_list) / len(hours_list)
            low_nights = sum(1 for h in hours_list if h < 6)
            sleep_line = f"Avg: {avg_sleep:.1f}h/night over {len(hours_list)} night(s)"
            if low_nights:
                sleep_line += f" ({low_nights} night(s) under 6h)"
            sections.append(f"😴 <b>Sleep</b>\n{sleep_line}")

    # Mood summary
    mood_log = user_data.get("mood_log", [])
    week_moods = [e for e in mood_log if e.get("date", "") >= week_start_str]
    if week_moods:
        mood_counts = {}
        for e in week_moods:
            m = e.get("mood", "okay")
            mood_counts[m] = mood_counts.get(m, 0) + 1
        top_mood = max(mood_counts, key=mood_counts.get)
        emoji_map = {"great": "🌟", "good": "😊", "okay": "😐", "tired": "😴", "stressed": "😤", "anxious": "😰", "low": "😔"}
        em = emoji_map.get(top_mood, "")
        sections.append(f"🧠 <b>Mood</b>\nMost common: {top_mood} {em} ({mood_counts[top_mood]}x)")

    return "\n\n".join(sections)


# Phase 6 - Quote and word of the day via GPT

def get_stoic_quote():
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": (
                "Give me one authentic stoic quote from Marcus Aurelius, Seneca, or Epictetus. "
                "Return ONLY this format, nothing else:\n"
                "Quote text here\n- Author Name"
            )}],
            max_tokens=120,
            temperature=0.9
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        return None


def get_word_of_the_day():
    try:
        import random as _random
        _seed_date = datetime.datetime.now().strftime("%Y-%m-%d")
        _rand_n = _random.randint(1000, 9999)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": (
                f"Today is {_seed_date} (seed:{_rand_n}). Give me a DIFFERENT interesting English word of the day - "
                "NOT serendipity, NOT ubiquitous, NOT ephemeral. Pick something fresh and unexpected. "
                "Pick a real word that is genuinely useful in everyday conversation - "
                "not too obscure, not too common. Something someone could actually use this week. "
                "Return ONLY this exact format with no extra text:\n"
                "WORD: the word\n"
                "PART: noun/verb/adjective/etc\n"
                "MEANING: one clear sentence definition\n"
                "EXAMPLE: one natural example sentence using the word"
            )}],
            max_tokens=120,
            temperature=0.9
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        return None


# Phase 6 - Voice message handler

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    voice_file = await update.message.voice.get_file()
    ogg_path = f"/tmp/voice_{update.message.message_id}.ogg"
    try:
        await voice_file.download_to_drive(ogg_path)
        with open(ogg_path, "rb") as audio:
            transcription = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio,
                response_format="text"
            )
        text = transcription.strip()
        if not text:
            await update.message.reply_text("Could not make out what you said. Try again?")
            return
        await update.message.reply_text(f"You said: {text}\n\nProcessing...")
        # Process transcribed text directly through GPT
        user_id = update.effective_user.id
        if user_id not in conversation_history:
            saved = load_conversation()
            conversation_history[user_id] = saved.get(str(user_id), [])
        # Check habit keywords first
        text_lower = text.lower()
        habit_response = check_habit_from_message(text_lower, load_data())
        if habit_response:
            await update.message.reply_text(habit_response)
            return
        conversation_history[user_id].append({"role": "user", "content": text[:2000]})
        if len(conversation_history[user_id]) > 20:
            conversation_history[user_id] = conversation_history[user_id][-20:]
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        now = datetime.datetime.now().strftime("%A, %B %-d, %Y, %-I:%M %p")
        contacts = load_contacts()
        contact_ctx = ""
        if contacts:
            contact_ctx = "\n\nKnown contacts:\n"
            for name, facts in list(contacts.items())[:10]:
                facts_list = facts if isinstance(facts, list) else [facts]
                contact_ctx += f"- {name}: {'; '.join(facts_list[:3])}\n"
        system = SYSTEM_PROMPT + CONTACT_SYSTEM_ADDON + f"\n\nCurrent date/time: {now} (Mountain Time)" + contact_ctx
        messages = [{"role": "system", "content": system}] + conversation_history[user_id]
        response = client.chat.completions.create(
            model="gpt-4o-mini", messages=messages, max_tokens=900, temperature=0.7
        )
        assistant_message = response.choices[0].message.content
        reply_lines = []
        for line in assistant_message.split("\n"):
            if line.startswith("CALENDAR_ACTION:"):
                try:
                    action_data = json.loads(line.replace("CALENDAR_ACTION:", "").strip())
                    cal_reply = await handle_calendar_action(action_data, update)
                    if cal_reply:
                        reply_lines.append(cal_reply)
                except Exception as e:
                    logger.error(f"Voice cal action error: {e}")
            elif line.startswith("DATA_ACTION:"):
                try:
                    action_data = json.loads(line.replace("DATA_ACTION:", "").strip())
                    data_reply = await handle_data_action(action_data)
                    if data_reply:
                        reply_lines.append(data_reply)
                        if action_data.get("action") in ("todo_list", "sleep_list", "mood_list", "habit_list"):
                            context.user_data["_last_html_reply"] = True
                except Exception as e:
                    logger.error(f"Voice data action error: {e}")
            elif line.startswith("CONTACT_ACTION:"):
                try:
                    contact_data = json.loads(line.replace("CONTACT_ACTION:", "").strip())
                    contacts = load_contacts()
                    name = contact_data.get("name", "").title()
                    fact = contact_data.get("fact", "").strip()
                    if name and fact:
                        if name not in contacts:
                            contacts[name] = []
                        if isinstance(contacts[name], str):
                            contacts[name] = [contacts[name]]
                        contacts[name].append(fact)
                        save_contacts(contacts)
                        reply_lines.append(f"Got it! Saved note about {name}: {fact}")
                except Exception as e:
                    logger.error(f"Voice contact action error: {e}")
            else:
                if line.strip():
                    reply_lines.append(line)
        final_reply = "\n".join(reply_lines).strip() or "Done!"
        conversation_history[user_id].append({"role": "assistant", "content": final_reply})
        all_history = load_conversation()
        all_history[str(user_id)] = conversation_history[user_id]
        save_conversation(all_history)
        await send_long_message(update.message, final_reply)
    except Exception as e:
        logger.error(f"Voice error: {e}")
        await update.message.reply_text("Had trouble processing that voice message. Please try again.")
    finally:
        try:
            os.remove(ogg_path)
        except Exception:
            pass


# Phase 6 - Photo/screenshot handler

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    photo = update.message.photo[-1]
    photo_file = await photo.get_file()
    img_path = f"/tmp/photo_{update.message.message_id}.jpg"
    try:
        await photo_file.download_to_drive(img_path)
        with open(img_path, "rb") as f:
            import base64
            img_data = base64.b64encode(f.read()).decode("utf-8")
        caption = update.message.caption or ""
        prompt = (
            "Look at this image carefully. Determine what it is and respond helpfully. "
            "If it is a receipt or expense: extract the total amount, store name, date, and spending category if visible. "
            "If the caption mentions a category (e.g. groceries, gas, coffee) use that as the category. "
            "Then say RECEIPT_DETECTED: {amount} at {store} on {date} category:{category} and ask if they want to log it. "
            "If it is a whiteboard, handwritten notes, sticky notes, or any written/typed text content: "
            "transcribe all the text clearly, then say NOTE_DETECTED: and offer to save it as a note. "
            "If it is a menu, recipe, or food item list: list what you see, then say MEAL_DETECTED: and offer to save meals to their list. "
            "If it is a calendar event or appointment screenshot: extract ALL details (title, date, start time, "
            "end time, location, description) and say CALENDAR_EVENT_DETECTED: then list the details clearly, "
            "then ask if they want to add it to their calendar. "
            "If it is a message, text, email, or DM someone sent them: offer 3 reply options "
            "(Option 1, Option 2, Option 3 with tone labels). "
            "If it is anything else: describe what you see and answer any question in the caption. "
            f"Caption from user: {caption if caption else 'None'}"
        )
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/jpeg;base64,{img_data}"
                    }}
                ]
            }],
            max_tokens=600
        )
        reply = response.choices[0].message.content.strip()
        import re as _re
        reply = _re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', reply)
        if "RECEIPT_DETECTED:" in reply:
            context.user_data["pending_receipt"] = reply
        if "CALENDAR_EVENT_DETECTED:" in reply:
            context.user_data["pending_calendar_event"] = reply
        if "NOTE_DETECTED:" in reply:
            context.user_data["pending_photo_note"] = reply
        if "MEAL_DETECTED:" in reply:
            context.user_data["pending_photo_meal"] = reply
        await update.message.reply_text(reply, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Photo error: {e}")
        await update.message.reply_text("Had trouble reading that image. Please try again.")
    finally:
        try:
            os.remove(img_path)
        except Exception:
            pass


# Phase 6 - Calendar range commands

async def weekend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    tz = pytz.timezone("America/Denver")
    now = datetime.datetime.now(tz)
    days_until_sat = (5 - now.weekday()) % 7
    if days_until_sat == 0 and now.weekday() == 5:
        days_until_sat = 0
    sat = now + datetime.timedelta(days=days_until_sat)
    sun = sat + datetime.timedelta(days=1)
    service = get_calendar_service()
    if not service:
        await update.message.reply_text("Calendar not connected yet. Use /auth to connect.")
        return
    sat_start = sat.replace(hour=0, minute=0, second=0, microsecond=0)
    sun_end = sun.replace(hour=23, minute=59, second=59, microsecond=0)
    all_events = []
    try:
        calendars = service.calendarList().list().execute().get("items", [])
        for cal in calendars:
            try:
                result = service.events().list(
                    calendarId=cal["id"],
                    timeMin=sat_start.isoformat(),
                    timeMax=sun_end.isoformat(),
                    singleEvents=True,
                    orderBy="startTime"
                ).execute()
                for event in result.get("items", []):
                    event["_calendar_name"] = cal.get("summary", "")
                    all_events.append(event)
            except Exception:
                pass
    except Exception:
        await update.message.reply_text("Could not fetch calendar events.")
        return
    all_events.sort(key=lambda e: e["start"].get("dateTime", e["start"].get("date", "")))
    if not all_events:
        await update.message.reply_text("Nothing on the calendar this weekend.")
        return
    lines = ["Your weekend:\n"]
    for e in all_events:
        start = e["start"].get("dateTime", e["start"].get("date", ""))
        if "T" in start:
            dt = datetime.datetime.fromisoformat(start)
            if dt.tzinfo is None:
                dt = tz.localize(dt)
            else:
                dt = dt.astimezone(tz)
            time_str = dt.strftime("%a %-I:%M %p")
        else:
            dt = datetime.datetime.fromisoformat(start)
            time_str = dt.strftime("%a (all day)")
        title = e.get("summary", "Untitled")
        cal_name = e.get("_calendar_name", "")
        line = f"* {time_str} - {title}"
        if cal_name and cal_name.lower() not in ("ty wass", "primary"):
            line += f" ({cal_name})"
        lines.append(line)
    await update.message.reply_text("\n".join(lines))


async def rest_of_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    tz = pytz.timezone("America/Denver")
    now = datetime.datetime.now(tz)
    end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=0)
    service = get_calendar_service()
    if not service:
        await update.message.reply_text("Calendar not connected yet. Use /auth to connect.")
        return
    all_events = []
    try:
        calendars = service.calendarList().list().execute().get("items", [])
        for cal in calendars:
            try:
                result = service.events().list(
                    calendarId=cal["id"],
                    timeMin=now.isoformat(),
                    timeMax=end_of_day.isoformat(),
                    singleEvents=True,
                    orderBy="startTime"
                ).execute()
                for event in result.get("items", []):
                    event["_calendar_name"] = cal.get("summary", "")
                    all_events.append(event)
            except Exception:
                pass
    except Exception:
        await update.message.reply_text("Could not fetch calendar events.")
        return
    all_events.sort(key=lambda e: e["start"].get("dateTime", e["start"].get("date", "")))
    if not all_events:
        await update.message.reply_text("Nothing left on the calendar today.")
        return
    lines = ["Rest of today:\n"]
    for e in all_events:
        start = e["start"].get("dateTime", e["start"].get("date", ""))
        if "T" in start:
            dt = datetime.datetime.fromisoformat(start)
            if dt.tzinfo is None:
                dt = tz.localize(dt)
            else:
                dt = dt.astimezone(tz)
            time_str = dt.strftime("%-I:%M %p")
        else:
            time_str = "All day"
        title = e.get("summary", "Untitled")
        cal_name = e.get("_calendar_name", "")
        line = f"* {time_str} - {title}"
        if cal_name and cal_name.lower() not in ("ty wass", "primary"):
            line += f" ({cal_name})"
        lines.append(line)
    await update.message.reply_text("\n".join(lines))


async def scores_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    args = context.args or []
    my_teams = "myteams" in " ".join(args).lower() or "myteam" in " ".join(args).lower()
    await update.message.reply_text("Fetching scores for your teams..." if my_teams else "Fetching yesterday's scores...")
    recap = format_sports_recap("yesterday", my_teams_only=my_teams)
    if recap:
        await update.message.reply_text(recap)
    else:
        await update.message.reply_text("No games played yesterday.")


# Update build_briefing_message to include Phase 6 content

async def build_briefing_sections(user_data, cal_service=None):
    """Returns a list of message strings, each sent as a separate Telegram message."""
    tz = pytz.timezone("America/Denver")
    now = datetime.datetime.now(tz)
    date_str = now.strftime("%A, %B %-d")

    sections = []

    # Message 1: Header + Weather
    try:
        header = f"🌅 <b>Good morning, Ty!</b>\n{date_str}"
        weather = get_weather_slc()
        sections.append(header + "\n\n" + weather)
    except Exception as e:
        sections.append(f"🌅 <b>Good morning, Ty!</b>\n{date_str}\n\nWeather unavailable")

    # Message 2: Calendar
    try:
        if cal_service:
            cal = get_todays_calendar_events_briefing(cal_service)
        else:
            cal = "📅 Calendar - Not connected (use /auth to connect)"
        sections.append(cal)
    except Exception:
        sections.append("📅 Calendar unavailable")

    # Message 3: To-dos + Shopping + Reminders (grouped)
    try:
        daily_tasks = []
        daily_tasks.append(get_briefing_todos(user_data))
        shopping = get_briefing_shopping(user_data)
        if shopping:
            daily_tasks.append(shopping)
        reminders = get_briefing_reminders(user_data)
        if reminders:
            daily_tasks.append(reminders)
        sections.append("\n\n".join(daily_tasks))
    except Exception as e:
        sections.append(f"Tasks unavailable: {str(e)[:60]}")

    # Message 4: Habits streak (if any tracked)
    try:
        habits_msg = get_briefing_habits(user_data)
        if habits_msg:
            sections.append(habits_msg)
    except Exception:
        pass

    # Message 5: Workouts + Expenses
    try:
        stats = []
        workouts = get_briefing_workouts(user_data)
        if workouts:
            stats.append(workouts)
        expenses = get_briefing_expenses(user_data)
        if expenses:
            stats.append(expenses)
        if stats:
            sections.append("\n\n".join(stats))
    except Exception:
        pass

    # Message 6: Sports recap (my teams only)
    try:
        recap = format_sports_recap("yesterday", my_teams_only=True)
        if recap:
            sections.append("🏆 <b>Yesterday in Sports</b>\n" + recap)
    except Exception:
        pass

    # Message 7: Quote + Word of the day
    try:
        inspiration = []
        quote = get_stoic_quote()
        if quote:
            inspiration.append("💭 <b>Stoic Quote</b>\n" + quote)
        word = get_word_of_the_day()
        if word:
            inspiration.append("📖 <b>Word of the Day</b>\n" + word)
        if inspiration:
            sections.append("\n\n".join(inspiration))
    except Exception:
        pass

    return sections


async def build_briefing_message(user_data, cal_service=None):
    """Legacy single-message version kept for compatibility."""
    sections = await build_briefing_sections(user_data, cal_service)
    return "\n\n".join(sections)



# Phase 7 - Habit Tracker

HABITS = [
    "workout",
    "water",
    "meditation",
    "morning_routine",
    "journaling",
    "vitamins",
    "stretching",
    "outdoor_time",
    "gratitude",
]

HABIT_LABELS = {
    "workout": "Daily workout",
    "water": "Water intake",
    "meditation": "Meditation",
    "morning_routine": "Morning routine",
    "journaling": "Journaling",
    "vitamins": "Vitamins",
    "stretching": "Stretching",
    "outdoor_time": "Outdoor time",
    "gratitude": "Gratitude practice",
}

HABIT_KEYWORDS = {
    "workout": ["workout", "worked out", "exercise", "exercised", "hit the gym", "gym done"],
    "water": ["drank water", "water intake", "hydrated", "finished my water"],
    "meditation": ["meditated", "meditation done", "mindfulness", "did meditation"],
    "morning_routine": ["morning routine", "morning done", "got my morning in"],
    "journaling": ["journaled", "journaling done", "wrote in journal", "did my journal"],
    "vitamins": ["took vitamins", "took my vitamins", "vitamins done", "took my supplements", "supplements done", "vitamins taken", "had my vitamins"],
    "stretching": ["stretched", "stretching done", "did my stretches", "mobility done"],
    "outdoor_time": ["went outside", "outdoor time", "fresh air", "took a walk outside"],
    "gratitude": ["gratitude done", "did gratitude", "grateful today", "wrote gratitude"],
}


def get_habit_streak(habit_log, habit_key):
    """Calculate current streak for a habit."""
    tz = pytz.timezone("America/Denver")
    today = datetime.datetime.now(tz).date()
    streak = 0
    check_date = today
    while True:
        date_str = check_date.strftime("%Y-%m-%d")
        if any(e.get("habit") == habit_key and e.get("date", "").startswith(date_str)
               for e in habit_log):
            streak += 1
            check_date -= datetime.timedelta(days=1)
        else:
            break
    return streak


def get_briefing_habits(user_data):
    habit_log = user_data.get("habit_log", [])
    if not habit_log:
        return None
    tz = pytz.timezone("America/Denver")
    today_str = datetime.datetime.now(tz).strftime("%Y-%m-%d")
    lines = ["🔥 <b>Habit Streaks</b>"]
    any_streak = False
    for habit in HABITS:
        streak = get_habit_streak(habit_log, habit)
        done_today = any(
            e.get("habit") == habit and e.get("date", "").startswith(today_str)
            for e in habit_log
        )
        if streak > 0:
            any_streak = True
            check = "✅" if done_today else "⬜"
            label = HABIT_LABELS[habit]
            lines.append(f"  {check} {label} - {streak} day streak")
    if not any_streak:
        return None
    return "\n".join(lines)


async def cmd_habits(update, context):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    data = load_data()
    habit_log = data.get("habit_log", [])
    tz = pytz.timezone("America/Denver")
    today_str = datetime.datetime.now(tz).strftime("%Y-%m-%d")
    lines = ["🔥 <b>Your Habit Tracker</b>\n"]
    for habit in HABITS:
        streak = get_habit_streak(habit_log, habit)
        done_today = any(
            e.get("habit") == habit and e.get("date", "").startswith(today_str)
            for e in habit_log
        )
        check = "✅" if done_today else "⬜"
        label = HABIT_LABELS[habit]
        streak_txt = f"{streak} day streak" if streak > 0 else "No streak yet"
        lines.append(f"{check} {label} - {streak_txt}")
    lines.append("\nSay things like 'did my workout' or 'meditation done' to log habits.")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


def check_habit_from_message(text_lower, user_data):
    """Check if a message logs a habit. Returns response string or None."""
    data_changed = False
    responses = []
    tz = pytz.timezone("America/Denver")
    now_str = datetime.datetime.now(tz).strftime("%Y-%m-%d %H:%M")

    for habit, keywords in HABIT_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            habit_log = user_data.get("habit_log", [])
            today_str = datetime.datetime.now(tz).strftime("%Y-%m-%d")
            already = any(
                e.get("habit") == habit and e.get("date", "").startswith(today_str)
                for e in habit_log
            )
            if not already:
                habit_log.append({"habit": habit, "date": now_str})
                user_data["habit_log"] = habit_log
                save_data(user_data)
                data_changed = True
                streak = get_habit_streak(habit_log, habit)
                label = HABIT_LABELS[habit]
                responses.append(f"✅ {label} logged! {streak} day streak 🔥")
            else:
                label = HABIT_LABELS[habit]
                responses.append(f"✅ {label} already logged today!")

    return "\n".join(responses) if responses else None


# Phase 7 - Contact Memory

def get_contact_note(name, contacts):
    name_lower = name.lower()
    for key in contacts:
        if key.lower() == name_lower or name_lower in key.lower():
            return contacts[key]
    return None


def extract_contact_update(text, contacts):
    """Check if message is saving a contact fact. Returns (name, fact) or None."""
    import re
    patterns = [
        r"remember that ([a-zA-Z]+) (.+)",
        r"note about ([a-zA-Z]+)[:\-] (.+)",
        r"([a-zA-Z]+)[ ]?['s]+ (birthday|phone|email|address|prefers|likes|hates|works at|lives in).+",
    ]
    for pattern in patterns:
        match = re.search(pattern, text.lower())
        if match:
            name = match.group(1).title()
            fact = text[match.start(2):].strip() if len(match.groups()) > 1 else text
            return name, fact
    return None


async def cmd_contacts(update, context):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    contacts = load_contacts()
    if not contacts:
        await update.message.reply_text("No contact notes saved yet.\nSay things like: remember that John prefers texts over calls")
        return
    lines = ["👥 <b>Contact Notes</b>\n"]
    for name, facts in contacts.items():
        lines.append(f"<b>{name}</b>")
        if isinstance(facts, list):
            for f in facts:
                lines.append(f"  • {f}")
        else:
            lines.append(f"  • {facts}")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# Phase 7 - Weekly Summary

async def build_weekly_summary(user_data, cal_service=None):
    tz = pytz.timezone("America/Denver")
    now = datetime.datetime.now(tz)
    week_start = now - datetime.timedelta(days=7)
    week_start_str = week_start.strftime("%Y-%m-%d")

    sections = ["📊 <b>Your Week in Review</b>\n"]

    # Habits this week
    habit_log = user_data.get("habit_log", [])
    week_habits = [e for e in habit_log if e.get("date", "") >= week_start_str]
    if week_habits:
        habit_counts = {}
        for e in week_habits:
            h = e.get("habit", "")
            habit_counts[h] = habit_counts.get(h, 0) + 1
        habit_lines = ["💪 <b>Habits this week</b>"]
        for habit in HABITS:
            count = habit_counts.get(habit, 0)
            if count > 0:
                label = HABIT_LABELS[habit]
                bar = "🟩" * count + "⬜" * (7 - count)
                habit_lines.append(f"  {label}: {bar} {count}/7")
        sections.append("\n".join(habit_lines))

    # Workouts this week
    workouts = [w for w in user_data.get("workouts", [])
                if w.get("date", "") >= week_start_str]
    if workouts:
        sections.append(f"🏋️ <b>Workouts</b>: {len(workouts)} this week")

    # Expenses this week
    expenses = [e for e in user_data.get("expenses", [])
                if e.get("date", "") >= week_start_str]
    if expenses:
        total = sum(float(e.get("amount", 0)) for e in expenses)
        sections.append(f"💰 <b>Spending</b>: ${total:.2f} across {len(expenses)} transactions")

    # Calendar events this week
    if cal_service:
        try:
            week_events = list_events(days=7)
            if week_events:
                sections.append(f"📅 <b>Upcoming this week</b>: {len(week_events)} events")
        except Exception:
            pass

    # GPT narrative summary
    try:
        summary_prompt = (
            f"Write a brief, warm, encouraging weekly recap for Ty. "
            f"This week: {len(workouts)} workouts, "
            f"{len(week_habits)} habit completions, "
            f"${sum(float(e.get('amount',0)) for e in expenses):.2f} spent. "
            f"Keep it to 2-3 sentences, positive and motivating."
        )
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": summary_prompt}],
            max_tokens=150,
            temperature=0.8
        )
        narrative = resp.choices[0].message.content.strip()
        sections.append(f"\n{narrative}")
    except Exception:
        pass

    # Sleep this week
    sleep_log = data.get("sleep_log", [])
    week_sleep = [e for e in sleep_log if e.get("date", "") >= week_start_str]
    if week_sleep:
        hours_list = [e["hours"] for e in week_sleep if "hours" in e]
        if hours_list:
            avg_sleep = sum(hours_list) / len(hours_list)
            low_nights = sum(1 for h in hours_list if h < 6)
            sleep_line = f"Avg {avg_sleep:.1f}h/night over {len(hours_list)} nights logged"
            if low_nights:
                sleep_line += f" ({low_nights} night(s) under 6h)"
            sections.append(f"\U0001f4a4 <b>Sleep</b>\n{sleep_line}")

    # Mood this week
    mood_log = data.get("mood_log", [])
    week_moods = [e for e in mood_log if e.get("date", "") >= week_start_str]
    if week_moods:
        mood_counts = {}
        for e in week_moods:
            m = e.get("mood", "okay")
            mood_counts[m] = mood_counts.get(m, 0) + 1
        mood_emoji = {"great": "\U0001f31f", "good": "\U0001f60a", "okay": "\U0001f610",
                      "tired": "\U0001f634", "stressed": "\U0001f624", "anxious": "\U0001f630", "low": "\U0001f614"}
        top_mood = max(mood_counts, key=mood_counts.get)
        em = mood_emoji.get(top_mood, "")
        mood_summary = ", ".join(f"{m} x{c}" for m, c in sorted(mood_counts.items(), key=lambda x: -x[1]))
        sections.append(f"{em} <b>Mood</b>\n{mood_summary}")

    # Todos status
    todos = data.get("todos", [])
    active_todos = [t for t in todos if not t.get("done")]
    high_todos = [t for t in active_todos if t.get("priority") == "high"]
    if active_todos:
        todo_line = f"{len(active_todos)} active"
        if high_todos:
            todo_line += f", {len(high_todos)} high priority"
        sections.append(f"\u2705 <b>To-Dos</b>\n{todo_line} items outstanding")

    # Upcoming reminders
    reminders = [r for r in data.get("reminders", []) if not r.get("sent")]
    if reminders:
        sections.append(f"\u23f0 <b>Reminders</b>\n{len(reminders)} upcoming")

    return "\n\n".join(sections)


async def summary_command(update, context):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    await update.message.reply_text("Building your weekly summary...")
    data = load_data()
    cal_service = None
    try:
        cal_service = get_calendar_service()
    except Exception:
        pass
    msg = await build_weekly_summary(data, cal_service)
    await update.message.reply_text(msg, parse_mode="HTML")


async def send_weekly_summary(context):
    """Scheduled Sunday evening weekly summary."""
    data = load_data()
    cal_service = None
    try:
        cal_service = get_calendar_service()
    except Exception:
        pass
    msg = await build_weekly_summary(data, cal_service)
    await context.bot.send_message(
        chat_id=ALLOWED_USER_ID,
        text=msg,
        parse_mode="HTML"
    )


# Phase 7 - Travel Weather Detection

async def check_travel_weather(context):
    """Evening job: scan tomorrows calendar for travel, send weather forecast."""
    try:
        service = get_calendar_service()
        if not service:
            return
        tz = pytz.timezone("America/Denver")
        tomorrow = datetime.datetime.now(tz) + datetime.timedelta(days=1)
        start = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
        end = tomorrow.replace(hour=23, minute=59, second=59, microsecond=0)
        all_events = []
        calendars = service.calendarList().list().execute().get("items", [])
        for cal in calendars:
            try:
                result = service.events().list(
                    calendarId=cal["id"],
                    timeMin=start.isoformat(),
                    timeMax=end.isoformat(),
                    singleEvents=True,
                    orderBy="startTime"
                ).execute()
                all_events.extend(result.get("items", []))
            except Exception:
                pass

        travel_keywords = ["flight", "fly", "airport", "hotel", "travel", "trip",
                           "conference", "convention", "visit", "drive to"]
        slc_keywords = ["salt lake", "slc", "home", "ut ", "utah"]

        for event in all_events:
            title = event.get("summary", "").lower()
            location = event.get("location", "").lower()
            combined = title + " " + location
            is_travel = any(kw in combined for kw in travel_keywords)
            is_local = any(kw in combined for kw in slc_keywords)

            if is_travel and not is_local:
                dest = event.get("location") or event.get("summary", "your destination")
                msg = (
                    f"✈️ <b>Travel heads up!</b>\n"
                    f"You have <b>{event.get('summary', 'an event')}</b> tomorrow.\n"
                    f"Location: {dest}\n\n"
                    f"Remember to check the weather at your destination and pack accordingly!"
                )
                await context.bot.send_message(
                    chat_id=ALLOWED_USER_ID,
                    text=msg,
                    parse_mode="HTML"
                )
                break
    except Exception as e:
        logger.error(f"Travel weather check error: {e}")


# Phase 7 - Contact memory detection in handle_message (injected via system prompt addition)

CONTACT_SYSTEM_ADDON = """
== CONTACT MEMORY ==
When the user mentions remembering something about a person (e.g. "remember that John prefers texts", "note about Sarah: birthday is April 3"), respond with:
CONTACT_ACTION: {"name": "...", "fact": "..."}

When the user asks about a person they have mentioned before, include any known facts about them in your response if relevant.
"""



# Phase 8 - Callback query handler (inline keyboard button presses)

async def handle_callback(update, context):
    query = update.callback_query
    await query.answer()  # Must answer within 10s or Telegram drops the callback
    data_str = query.data

    if data_str.startswith("reminder_done:"):
        reminder_id = data_str.split(":", 1)[1]
        data = load_data()
        for r in data.get("reminders", []):
            if r.get("id") == reminder_id:
                r["sent"] = True
                break
        save_data(data)
        await query.edit_message_text("Reminder marked done!")

    elif data_str.startswith("reminder_snooze_1h:"):
        reminder_id = data_str.split(":", 1)[1]
        data = load_data()
        tz = pytz.timezone("America/Denver")
        for r in data.get("reminders", []):
            if r.get("id") == reminder_id:
                r["sent"] = False
                try:
                    new_time = datetime.datetime.fromisoformat(r["time"]) + datetime.timedelta(hours=1)
                    r["time"] = new_time.strftime("%Y-%m-%dT%H:%M:00")
                except Exception:
                    new_time = datetime.datetime.now(tz) + datetime.timedelta(hours=1)
                    r["time"] = new_time.strftime("%Y-%m-%dT%H:%M:00")
                break
        save_data(data)
        await query.edit_message_text("Reminder snoozed for 1 hour!")

    elif data_str.startswith("reminder_snooze_1d:"):
        reminder_id = data_str.split(":", 1)[1]
        data = load_data()
        for r in data.get("reminders", []):
            if r.get("id") == reminder_id:
                r["sent"] = False
                try:
                    new_time = datetime.datetime.fromisoformat(r["time"]) + datetime.timedelta(days=1)
                    r["time"] = new_time.strftime("%Y-%m-%dT%H:%M:00")
                except Exception:
                    tz = pytz.timezone("America/Denver")
                    new_time = datetime.datetime.now(tz) + datetime.timedelta(days=1)
                    r["time"] = new_time.strftime("%Y-%m-%dT%H:%M:00")
                break
        save_data(data)
        await query.edit_message_text("Reminder snoozed until tomorrow!")

    elif data_str == "cmd_todos":
        try:
            reply = await handle_data_action({"action": "todo_list"})
            await context.bot.send_message(chat_id=query.message.chat_id, text=reply)
        except Exception as e:
            logger.error(f"cmd_todos callback error: {e}")

    elif data_str == "cmd_notes":
        try:
            reply = await handle_data_action({"action": "note_list"})
            await context.bot.send_message(chat_id=query.message.chat_id, text=reply)
        except Exception as e:
            logger.error(f"cmd_notes callback error: {e}")

    elif data_str == "cmd_habits":
        try:
            data = load_data()
            habit_log = data.get("habit_log", [])
            tz = pytz.timezone("America/Denver")
            today_str = datetime.datetime.now(tz).strftime("%Y-%m-%d")
            lines = ["<b>Your Habit Tracker</b>\n"]
            for habit in HABITS:
                streak = get_habit_streak(habit_log, habit)
                done_today = any(
                    e.get("habit") == habit and e.get("date", "").startswith(today_str)
                    for e in habit_log
                )
                check = "done" if done_today else "o"
                label = HABIT_LABELS[habit]
                streak_txt = f"{streak} day streak" if streak > 0 else "No streak yet"
                lines.append(f"{check} {label} - {streak_txt}")
            await context.bot.send_message(chat_id=query.message.chat_id, text="\n".join(lines), parse_mode="HTML")
        except Exception as e:
            logger.error(f"cmd_habits callback error: {e}")

    elif data_str == "cmd_summary":
        try:
            data = load_data()
            cal_service = None
            try:
                cal_service = get_calendar_service()
            except Exception:
                pass
            msg = await build_weekly_summary(data, cal_service)
            await context.bot.send_message(chat_id=query.message.chat_id, text=msg, parse_mode="HTML")
        except Exception as e:
            logger.error(f"cmd_summary callback error: {e}")

    elif data_str == "cmd_expenses":
        try:
            reply = await handle_data_action({"action": "expense_list"})
            await context.bot.send_message(chat_id=query.message.chat_id, text=reply)
        except Exception as e:
            logger.error(f"cmd_expenses callback error: {e}")

    elif data_str == "cmd_briefing":
        try:
            data = load_data()
            cal_service = None
            try:
                cal_service = get_calendar_service()
            except Exception:
                pass
            sections = await build_briefing_sections(data, cal_service)
            for section in sections:
                await context.bot.send_message(chat_id=query.message.chat_id, text=section, parse_mode="HTML")
        except Exception as e:
            logger.error(f"cmd_briefing callback error: {e}")


# Phase 8 - Brain dump

async def brain_dump_command(update, context):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    await update.message.reply_text(
        "Brain dump mode. Just type or speak everything on your mind - "
        "I will sort it into todos, reminders, and notes automatically. Go!"
    )
    context.user_data["brain_dump_mode"] = True


async def process_brain_dump(update, context):
    """Process a brain dump message - sort with GPT and save raw to notes."""
    text = update.message.text
    user_data = load_data()
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    # Save raw version to notes
    user_data["notes"].append({"text": f"[Brain dump] {text}", "added": now_str})

    # Ask GPT to sort it
    sort_prompt = (
        "The user did a brain dump. Extract and categorize everything into: "
        "TODOS (format: TODO: task text), "
        "REMINDERS (format: REMINDER: text | YYYY-MM-DDTHH:MM:00), "
        "NOTES (format: NOTE: text). "
        "If no clear time is given for reminders, make them todos instead. "
        f"Current date/time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}. "
        f"Brain dump text: {text} "
        "List each item on its own line with the prefix. Nothing else."
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": sort_prompt}],
            max_tokens=500,
            temperature=0.3
        )
        sorted_text = response.choices[0].message.content.strip()

        todos_added = []
        reminders_added = []
        notes_added = []

        for line in sorted_text.splitlines():
            line = line.strip()
            if line.startswith("TODO:"):
                item = line[5:].strip()
                import uuid as _uuid
                user_data["todos"].append({"text": item, "done": False, "added": now_str})
                todos_added.append(item)
            elif line.startswith("REMINDER:"):
                parts = line[9:].strip().split("|")
                if len(parts) == 2:
                    reminder_text = parts[0].strip()
                    reminder_time = parts[1].strip()
                    user_data["reminders"].append({
                        "text": reminder_text,
                        "time": reminder_time,
                        "sent": False,
                        "added": now_str,
                        "id": str(_uuid.uuid4())[:8]
                    })
                    reminders_added.append(reminder_text)
                else:
                    item = parts[0].strip()
                    user_data["todos"].append({"text": item, "done": False, "added": now_str})
                    todos_added.append(item)
            elif line.startswith("NOTE:"):
                note_text = line[5:].strip()
                notes_added.append(note_text)

        save_data(user_data)

        summary_parts = []
        if todos_added:
            summary_parts.append(f"<b>{len(todos_added)} todo(s)</b>: " + ", ".join(todos_added[:3]) + ("..." if len(todos_added) > 3 else ""))
        if reminders_added:
            summary_parts.append(f"<b>{len(reminders_added)} reminder(s)</b>: " + ", ".join(reminders_added[:2]))
        if notes_added:
            summary_parts.append(f"<b>{len(notes_added)} note idea(s)</b> captured")

        summary = ("Brain dump sorted! " + " | ".join(summary_parts) if summary_parts else "Brain dump saved to notes!")
        summary += " (Raw dump also saved to your notes)"

        await update.message.reply_text(summary)

    except Exception as e:
        logger.error(f"Brain dump error: {e}")
        save_data(user_data)
        await update.message.reply_text("Saved your brain dump to notes! Could not auto-sort this time.")

    context.user_data["brain_dump_mode"] = False


# Phase 8 - /ask web search via GPT-4o with browsing

async def ask_command(update, context):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    if not context.args:
        await update.message.reply_text("Usage: /ask [question]. Example: /ask who won last nights Celtics game")
        return
    question = " ".join(context.args).strip()
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    await update.message.reply_text("Searching...")
    serper_key = os.environ.get("SERPER_API_KEY", "")
    search_results = ""
    if serper_key:
        try:
            resp = requests.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": serper_key, "Content-Type": "application/json"},
                json={"q": question, "num": 5},
                timeout=10
            )
            data = resp.json()
            snippets = []
            if "answerBox" in data:
                ab = data["answerBox"]
                snippets.append(ab.get("answer") or ab.get("snippet") or "")
            for r in data.get("organic", [])[:4]:
                snippets.append(r.get("title", "") + ": " + r.get("snippet", ""))
            search_results = " | ".join(s for s in snippets if s)
        except Exception as e:
            logger.error(f"Serper search error: {e}")
    today = datetime.datetime.now().strftime("%B %d, %Y")
    if search_results:
        prompt = (
            f"Using these search results, answer the question concisely. "
            f"Today is {today}. "
            f"Search results: {search_results[:1500]} "
            f"Question: {question}"
        )
    else:
        prompt = (
            f"Answer this question as accurately as possible. "
            f"If the answer depends on recent events after your training, say so. "
            f"Today is {today}. "
            f"Question: {question}"
        )
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
            temperature=0.3,
        )
        answer = response.choices[0].message.content or "Could not find an answer for that."
        src = " (via live search)" if search_results else " (from training data)"
        reply = "<b>" + question + "</b>" + src + "\n\n" + answer
        await send_long_message(update.message, reply, parse_mode="HTML")
        audit_log(f"ASK q={question[:50]}")
    except Exception as e:
        logger.error(f"Ask command error: {e}")
        audit_log(f"ASK_ERROR {str(e)[:100]}")
        await update.message.reply_text(f"Search error: {str(e)[:120]}")


# Phase 8 - Google Tasks two-way sync

def get_tasks_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        from google.oauth2.credentials import Credentials as GCreds
        creds = GCreds.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        from google.auth.transport.requests import Request as GRequest
        creds.refresh(GRequest())
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    if not creds or not creds.valid:
        return None
    return build("tasks", "v1", credentials=creds)


def sync_todos_to_tasks(user_data):
    """Push bot todos to Google Tasks."""
    try:
        service = get_tasks_service()
        if not service:
            return False
        tasklists = service.tasklists().list().execute()
        bot_list_id = None
        for tl in tasklists.get("items", []):
            if tl.get("title") == "Wasonassistant":
                bot_list_id = tl["id"]
                break
        if not bot_list_id:
            new_list = service.tasklists().insert(body={"title": "Wasonassistant"}).execute()
            bot_list_id = new_list["id"]
        existing = service.tasks().list(tasklist=bot_list_id, showCompleted=False).execute()
        existing_titles = {t.get("title", "") for t in existing.get("items", [])}
        pushed = 0
        for todo in user_data.get("todos", []):
            if not todo.get("done") and todo.get("text") not in existing_titles:
                service.tasks().insert(
                    tasklist=bot_list_id,
                    body={"title": todo["text"], "status": "needsAction"}
                ).execute()
                pushed += 1
        return pushed
    except Exception as e:
        logger.error(f"Tasks sync push error: {e}")
        return False


def sync_tasks_to_todos(user_data):
    """Pull Google Tasks into bot todos (avoid duplicates)."""
    try:
        service = get_tasks_service()
        if not service:
            return 0
        tasklists = service.tasklists().list().execute()
        pulled = 0
        existing_texts = {t.get("text", "").lower() for t in user_data.get("todos", [])}
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        for tl in tasklists.get("items", []):
            if tl.get("title") == "Wasonassistant":
                continue
            tasks = service.tasks().list(
                tasklist=tl["id"], showCompleted=False
            ).execute()
            for task in tasks.get("items", []):
                title = task.get("title", "").strip()
                if title and title.lower() not in existing_texts:
                    import uuid as _uuid
                    user_data["todos"].append({
                        "text": title,
                        "done": False,
                        "added": now_str,
                        "source": "google_tasks"
                    })
                    existing_texts.add(title.lower())
                    pulled += 1
        if pulled:
            save_data(user_data)
        return pulled
    except Exception as e:
        logger.error(f"Tasks sync pull error: {e}")
        return 0


async def cmd_synctasks(update, context):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    service = get_calendar_service()
    if not service:
        await update.message.reply_text("Google Tasks is not connected. Use /auth to connect Google first.")
        return
    await update.message.reply_text("Syncing with Google Tasks...")
    try:
        user_data = load_data()
        pulled = sync_tasks_to_todos(user_data)
        pushed = sync_todos_to_tasks(user_data)
    except Exception as e:
        await update.message.reply_text(f"Sync failed: {str(e)[:120]}\nTry /auth to reconnect Google.")
        return
    parts = []
    if pulled:
        parts.append(f"{pulled} task(s) pulled from Google Tasks")
    if pushed:
        parts.append(f"{pushed} todo(s) pushed to Google Tasks")
    if not parts:
        parts.append("Everything already in sync")
    await update.message.reply_text("Sync complete! " + " | ".join(parts))


# Phase 8 - Auto tasks sync job

async def auto_sync_tasks(context):
    """Silently sync Google Tasks every morning."""
    try:
        user_data = load_data()
        pulled = sync_tasks_to_todos(user_data)
        if pulled:
            await context.bot.send_message(
                chat_id=ALLOWED_USER_ID,
                text=f"Synced {pulled} new task(s) from Google Tasks into your todos."
            )
    except Exception as e:
        logger.error(f"Auto tasks sync error: {e}")


# Phase 8 - Response caching for weather and sports

_cache = {}

def cache_get(key, max_age_seconds=300):
    if key in _cache:
        value, timestamp = _cache[key]
        if datetime.datetime.now().timestamp() - timestamp < max_age_seconds:
            return value
    return None

def cache_set(key, value):
    _cache[key] = (value, datetime.datetime.now().timestamp())


# Main

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("auth", auth))
    app.add_handler(CommandHandler("code", code))
    app.add_handler(CommandHandler("today", today))
    app.add_handler(CommandHandler("week", week))
    app.add_handler(CommandHandler("weekend", weekend))
    app.add_handler(CommandHandler("restofday", rest_of_day))
    app.add_handler(CommandHandler("scores", scores_command))
    app.add_handler(CommandHandler("briefing", briefing_command))
    app.add_handler(CommandHandler("todos", cmd_todos))
    app.add_handler(CommandHandler("shopping", cmd_shopping))
    app.add_handler(CommandHandler("notes", cmd_notes))
    app.add_handler(CommandHandler("expenses", cmd_expenses))
    app.add_handler(CommandHandler("workouts", cmd_workouts))
    app.add_handler(CommandHandler("gifts", cmd_gifts))
    app.add_handler(CommandHandler("reminders", cmd_reminders))
    app.add_handler(CommandHandler("sleep", cmd_sleep))
    app.add_handler(CommandHandler("mood", cmd_mood))
    app.add_handler(CommandHandler("habits", cmd_habits))
    app.add_handler(CommandHandler("contacts", cmd_contacts))
    app.add_handler(CommandHandler("summary", summary_command))
    app.add_handler(CommandHandler("ask", ask_command))
    app.add_handler(CommandHandler("braindump", brain_dump_command))
    app.add_handler(CommandHandler("synctasks", cmd_synctasks))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    mtn = pytz.timezone("America/Denver")

    # Check reminders every 60 seconds
    app.job_queue.run_repeating(check_reminders, interval=60, first=10)

    # Scheduled morning briefing at 7:00 AM Mountain Time
    briefing_time = datetime.time(hour=7, minute=0, tzinfo=mtn)
    app.job_queue.run_daily(send_scheduled_briefing, time=briefing_time, name="morning_briefing")

    # Weekly summary + digest: Sunday at 7:00 PM Mountain Time
    weekly_time = datetime.time(hour=19, minute=0, tzinfo=mtn)
    app.job_queue.run_daily(send_weekly_summary, time=weekly_time, days=(6,), name="weekly_summary")

    # Travel weather check: every evening at 7:00 PM Mountain Time
    travel_time = datetime.time(hour=19, minute=0, tzinfo=mtn)
    app.job_queue.run_daily(check_travel_weather, time=travel_time, name="travel_weather")

    # Google Tasks sync: every morning at 7:05 AM (just after briefing)
    tasks_sync_time = datetime.time(hour=7, minute=5, tzinfo=mtn)
    app.job_queue.run_daily(auto_sync_tasks, time=tasks_sync_time, name="tasks_sync")

    logger.info("Bot is running (Phase 8)...")
    app.run_polling(drop_pending_updates=True, allowed_updates=["message", "callback_query", "voice", "photo"])


if __name__ == "__main__":
    main()

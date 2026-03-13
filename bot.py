import os
import json
import logging
import datetime
import asyncio
import requests
import pytz
from openai import OpenAI
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes

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
SCOPES = ["https://www.googleapis.com/auth/calendar"]
TOKEN_FILE = "/tmp/google_token.json"
AUTH_STATE_FILE = "/tmp/auth_state.json"
DATA_FILE = "/tmp/userdata.json"

# Data helpers

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {
        "todos": [],
        "shopping": [],
        "notes": [],
        "reminders": [],
        "expenses": [],
        "meals": [],
        "workouts": [],
        "gifts": {}
    }

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

# System prompt - NO apostrophes anywhere inside this string

SYSTEM_PROMPT = """You are a personal assistant accessible via Telegram. You are helpful, concise, and friendly.

You help with scheduling, lists, notes, tracking, and general questions.

== CALENDAR ==
When the user asks to add/create/schedule a calendar event, respond with this on its own line:
CALENDAR_ACTION: {"action": "create", "title": "...", "start": "YYYY-MM-DDTHH:MM:00", "end": "YYYY-MM-DDTHH:MM:00", "description": "..."}

When the user asks what is on their calendar or schedule, respond with:
CALENDAR_ACTION: {"action": "list", "days": 7}

== TO-DO LIST ==
When the user asks to add a task or to-do, respond with:
DATA_ACTION: {"action": "todo_add", "item": "..."}

When the user asks to see their to-do list, respond with:
DATA_ACTION: {"action": "todo_list"}

When the user marks a task done or checks off a to-do (by number or name), respond with:
DATA_ACTION: {"action": "todo_done", "index": <number starting at 1>}

When the user asks to clear all completed todos or clear the list:
DATA_ACTION: {"action": "todo_clear"}

== SHOPPING LIST ==
When the user asks to add something to the shopping list or says I need to buy X or pick up X:
DATA_ACTION: {"action": "shop_add", "item": "..."}

When the user asks to see the shopping list:
DATA_ACTION: {"action": "shop_list"}

When the user marks a shopping item as gotten or bought (by number or name):
DATA_ACTION: {"action": "shop_done", "index": <number starting at 1>}

When the user asks to clear the shopping list:
DATA_ACTION: {"action": "shop_clear"}

== NOTES ==
When the user says note, remember this, save this, jot this down, or anything like note: ...:
DATA_ACTION: {"action": "note_add", "text": "..."}

When the user asks to see their notes:
DATA_ACTION: {"action": "note_list"}

When the user asks to delete a note by number:
DATA_ACTION: {"action": "note_delete", "index": <number starting at 1>}

== REMINDERS ==
When the user asks to be reminded of something at a specific time, respond with:
DATA_ACTION: {"action": "reminder_add", "text": "...", "time": "YYYY-MM-DDTHH:MM:00"}

When the user asks to see their reminders:
DATA_ACTION: {"action": "reminder_list"}

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

== GIFT IDEAS ==
When the user saves a gift idea for someone (e.g. gift idea for mom: silk scarf):
DATA_ACTION: {"action": "gift_add", "person": "...", "idea": "..."}

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


def create_event(title, start, end, description=""):
    service = get_calendar_service()
    if not service:
        return None
    event = {
        "summary": title,
        "description": description,
        "start": {"dateTime": start, "timeZone": "America/Denver"},
        "end": {"dateTime": end, "timeZone": "America/Denver"},
    }
    return service.events().insert(calendarId="primary", body=event).execute()


def list_events(days=7):
    service = get_calendar_service()
    if not service:
        return None
    now = datetime.datetime.utcnow().isoformat() + "Z"
    future = (datetime.datetime.utcnow() + datetime.timedelta(days=days)).isoformat() + "Z"
    result = service.events().list(
        calendarId="primary",
        timeMin=now,
        timeMax=future,
        singleEvents=True,
        orderBy="startTime"
    ).execute()
    return result.get("items", [])


# Data action handler

async def handle_data_action(action_data):
    data = load_data()
    action = action_data.get("action", "")
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    # TO-DO
    if action == "todo_add":
        item = action_data.get("item", "").strip()
        data["todos"].append({"text": item, "done": False, "added": now_str})
        save_data(data)
        return f"Added to your to-do list: {item}"

    elif action == "todo_list":
        todos = data.get("todos", [])
        if not todos:
            return "Your to-do list is empty!"
        lines = ["To-Do List:\n"]
        for i, t in enumerate(todos, 1):
            check = "done" if t["done"] else "o"
            lines.append(f"{check} {i}. {t['text']}")
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

    # SHOPPING
    elif action == "shop_add":
        item = action_data.get("item", "").strip()
        data["shopping"].append({"text": item, "done": False, "added": now_str})
        save_data(data)
        return f"Added to shopping list: {item}"

    elif action == "shop_list":
        items = data.get("shopping", [])
        if not items:
            return "Your shopping list is empty!"
        lines = ["Shopping List:\n"]
        for i, t in enumerate(items, 1):
            check = "got it" if t["done"] else "o"
            lines.append(f"{check} {i}. {t['text']}")
        return "\n".join(lines)

    elif action == "shop_done":
        idx = action_data.get("index", 0) - 1
        items = data.get("shopping", [])
        if 0 <= idx < len(items):
            items[idx]["done"] = True
            save_data(data)
            return f"Got it: {items[idx]['text']}"
        return "Couldn't find that item."

    elif action == "shop_clear":
        data["shopping"] = [t for t in data["shopping"] if not t["done"]]
        save_data(data)
        return "Cleared purchased items from shopping list."

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
        lines = ["Your Notes:\n"]
        for i, n in enumerate(notes, 1):
            lines.append(f"{i}. {n['text']}\n   ({n['added']})")
        return "\n".join(lines)

    elif action == "note_delete":
        idx = action_data.get("index", 0) - 1
        notes = data.get("notes", [])
        if 0 <= idx < len(notes):
            removed = notes.pop(idx)
            save_data(data)
            return f"Deleted note: {removed['text']}"
        return "Couldn't find that note."

    # REMINDERS
    elif action == "reminder_add":
        text = action_data.get("text", "").strip()
        time_str = action_data.get("time", "")
        data["reminders"].append({"text": text, "time": time_str, "sent": False, "added": now_str})
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
        if person not in data["gifts"]:
            data["gifts"][person] = []
        data["gifts"][person].append({"idea": idea, "added": now_str})
        save_data(data)
        return f"Gift idea saved for {person.title()}: {idea}"

    elif action == "gift_list":
        person = action_data.get("person", "").strip().lower()
        gifts = data.get("gifts", {})
        if person and person in gifts:
            ideas = gifts[person]
            if not ideas:
                return f"No gift ideas for {person.title()} yet."
            lines = [f"Gift ideas for {person.title()}:\n"]
            for i, g in enumerate(ideas, 1):
                lines.append(f"{i}. {g['idea']}")
            return "\n".join(lines)
        elif not person:
            if not gifts:
                return "No gift ideas saved yet."
            lines = ["All Gift Ideas:\n"]
            for p, ideas in gifts.items():
                lines.append(f"\n{p.title()}:")
                for g in ideas:
                    lines.append(f"  * {g['idea']}")
            return "\n".join(lines)
        return f"No gift ideas saved for {person.title()} yet."

    return None


# Calendar action handler

async def handle_calendar_action(action_data, update):
    action = action_data.get("action")

    if action == "create":
        service = get_calendar_service()
        if not service:
            return "I would love to add that, but calendar is not connected yet. Use /auth to connect."
        event = create_event(
            title=action_data.get("title", "Event"),
            start=action_data.get("start"),
            end=action_data.get("end"),
            description=action_data.get("description", "")
        )
        if event:
            return f"Added to your calendar: {action_data.get('title')}"
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
                await context.bot.send_message(
                    chat_id=ALLOWED_USER_ID,
                    text=f"Reminder: {r['text']}"
                )
                r["sent"] = True
                changed = True
        except Exception as e:
            logger.error(f"Reminder error: {e}")
    if changed:
        save_data(data)


# Phase 5 - Daily Briefing helpers

def get_weather_slc():
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
            "&forecast_days=1"
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
        lines = [
            "Weather - Salt Lake City",
            f"Now: {temp_now}F (feels {feels_like}F) - {description}",
            f"High: {high}F  |  Low: {low}F",
            f"Wind: {wind} mph",
        ]
        if precip > 0:
            lines.append(f"Precip: {precip} in")
        return "\n".join(lines)
    except Exception as e:
        return f"Weather unavailable ({str(e)[:50]})"


def get_todays_calendar_events_briefing(service):
    try:
        tz = pytz.timezone("America/Denver")
        now = datetime.datetime.now(tz)
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=0)
        events_result = service.events().list(
            calendarId="primary",
            timeMin=start_of_day.isoformat(),
            timeMax=end_of_day.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        events = events_result.get("items", [])
        if not events:
            return "Calendar - No events today"
        lines = ["Todays Calendar"]
        for event in events:
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
            lines.append(f"  * {time_str} - {title}")
        return "\n".join(lines)
    except Exception as e:
        return f"Calendar unavailable ({str(e)[:60]})"


def get_briefing_todos(user_data):
    todos = [t for t in user_data.get("todos", []) if not t.get("done")]
    if not todos:
        return "To-Dos - All clear!"
    lines = ["To-Dos"]
    for item in todos[:10]:
        lines.append(f"  * {item['text']}")
    if len(todos) > 10:
        lines.append(f"  ...and {len(todos) - 10} more")
    return "\n".join(lines)


def get_briefing_shopping(user_data):
    shopping = [s for s in user_data.get("shopping", []) if not s.get("done")]
    if not shopping:
        return None
    lines = ["Shopping List"]
    for item in shopping[:8]:
        lines.append(f"  * {item['text']}")
    if len(shopping) > 8:
        lines.append(f"  ...and {len(shopping) - 8} more")
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
        lines = ["Reminders Due Today"]
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
        lines = ["Recent Workouts"]
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


async def build_briefing_message(user_data, cal_service=None):
    tz = pytz.timezone("America/Denver")
    now = datetime.datetime.now(tz)
    date_str = now.strftime("%A, %B %-d")
    sections = [f"Good morning, Ty!\n{date_str}\n"]
    sections.append(get_weather_slc())
    if cal_service:
        sections.append(get_todays_calendar_events_briefing(cal_service))
    else:
        sections.append("Calendar - Not connected (use /auth to connect)")
    sections.append(get_briefing_todos(user_data))
    shopping = get_briefing_shopping(user_data)
    if shopping:
        sections.append(shopping)
    reminders = get_briefing_reminders(user_data)
    if reminders:
        sections.append(reminders)
    workouts = get_briefing_workouts(user_data)
    if workouts:
        sections.append(workouts)
    expenses = get_briefing_expenses(user_data)
    if expenses:
        sections.append(expenses)
    return "\n\n".join(sections)


# Scheduled morning briefing job

async def send_scheduled_briefing(context: ContextTypes.DEFAULT_TYPE):
    user_data = load_data()
    cal_service = None
    try:
        cal_service = get_calendar_service()
    except Exception:
        pass
    message = await build_briefing_message(user_data, cal_service)
    await context.bot.send_message(
        chat_id=ALLOWED_USER_ID,
        text=message
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
    lines = [f"Your events {label}:\n"]
    for e in events:
        start = e["start"].get("dateTime", e["start"].get("date", ""))
        if "T" in start:
            dt = datetime.datetime.fromisoformat(start.replace("Z", "+00:00"))
            time_str = dt.strftime("%a %b %-d at %-I:%M %p")
        else:
            dt = datetime.datetime.fromisoformat(start)
            time_str = dt.strftime("%a %b %-d (all day)")
        lines.append(f"* {e.get('summary', 'No title')} - {time_str}")
    await update.message.reply_text("\n".join(lines))


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
    message = await build_briefing_message(user_data, cal_service)
    await update.message.reply_text(message)


async def cmd_todos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    reply = await handle_data_action({"action": "todo_list"})
    await update.message.reply_text(reply)

async def cmd_shopping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    reply = await handle_data_action({"action": "shop_list"})
    await update.message.reply_text(reply)

async def cmd_notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    reply = await handle_data_action({"action": "note_list"})
    await update.message.reply_text(reply)

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
    await update.message.reply_text(reply)

async def cmd_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    reply = await handle_data_action({"action": "reminder_list"})
    await update.message.reply_text(reply)

async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    conversation_history.clear()
    await update.message.reply_text("Memory cleared - starting fresh!")


# Main message handler

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ALLOWED_USER_ID:
        return

    user_message = update.message.text
    if not user_message:
        return

    logger.info(f"Received: {user_message}")

    # Briefing keyword trigger
    text_lower = user_message.lower()
    if any(phrase in text_lower for phrase in ["morning briefing", "daily briefing", "give me my briefing", "my briefing"]):
        await briefing_command(update, context)
        return

    if user_id not in conversation_history:
        conversation_history[user_id] = []

    conversation_history[user_id].append({"role": "user", "content": user_message})
    if len(conversation_history[user_id]) > 20:
        conversation_history[user_id] = conversation_history[user_id][-20:]

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        now = datetime.datetime.now().strftime("%A, %B %-d, %Y, %-I:%M %p")
        system = SYSTEM_PROMPT + f"\n\nCurrent date/time: {now} (Mountain Time)"
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
                except Exception as e:
                    logger.error(f"Data action error: {e}")
            else:
                if line.strip():
                    reply_lines.append(line)

        final_reply = "\n".join(reply_lines).strip()
        if not final_reply:
            final_reply = "Done!"

        conversation_history[user_id].append({"role": "assistant", "content": final_reply})
        await update.message.reply_text(final_reply)

    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text("Sorry, ran into an issue. Please try again.")


# Main

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("auth", auth))
    app.add_handler(CommandHandler("code", code))
    app.add_handler(CommandHandler("today", today))
    app.add_handler(CommandHandler("week", week))
    app.add_handler(CommandHandler("briefing", briefing_command))
    app.add_handler(CommandHandler("todos", cmd_todos))
    app.add_handler(CommandHandler("shopping", cmd_shopping))
    app.add_handler(CommandHandler("notes", cmd_notes))
    app.add_handler(CommandHandler("expenses", cmd_expenses))
    app.add_handler(CommandHandler("workouts", cmd_workouts))
    app.add_handler(CommandHandler("gifts", cmd_gifts))
    app.add_handler(CommandHandler("reminders", cmd_reminders))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Check reminders every 60 seconds
    app.job_queue.run_repeating(check_reminders, interval=60, first=10)

    # Scheduled morning briefing at 7:00 AM Mountain Time
    briefing_time = datetime.time(hour=7, minute=0, tzinfo=pytz.timezone("America/Denver"))
    app.job_queue.run_daily(send_scheduled_briefing, time=briefing_time, name="morning_briefing")

    logger.info("Bot is running (Phase 5)...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

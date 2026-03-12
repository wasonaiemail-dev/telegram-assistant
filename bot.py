import os
import json
import logging
import datetime
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

SYSTEM_PROMPT = """You are a personal assistant accessible via Telegram. You are helpful, concise, and friendly.

You help with:
- Scheduling and calendar management
- To-do lists and task tracking
- Daily briefings and reminders
- Note taking and saving ideas
- Budget and expense tracking
- Habit and goal tracking
- Suggesting replies to messages
- General questions and research

When the user asks to add, create, or schedule something on their calendar, extract:
- Event title
- Date and time (assume current year if not specified)
- Duration (default 1 hour if not specified)

Then respond with a JSON block in this exact format on its own line:
CALENDAR_ACTION: {"action": "create", "title": "...", "start": "YYYY-MM-DDTHH:MM:00", "end": "YYYY-MM-DDTHH:MM:00", "description": "..."}

When the user asks what's on their calendar or their schedule, respond with:
CALENDAR_ACTION: {"action": "list", "days": 7}

For everything else, respond normally in plain conversational text.

Keep responses concise. Today's date context will be provided in each message."""


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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    await update.message.reply_text(
        "Hey! I'm your personal assistant.\n\n"
        "Commands:\n"
        "/auth - Connect your Google Calendar\n"
        "/code YOUR_CODE - Submit Google auth code\n"
        "/today - See today's events\n"
        "/week - See this week's events\n"
        "/clear - Clear conversation memory\n\n"
        "Or just talk to me naturally!"
    )


async def auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return

    creds_data = json.loads(GOOGLE_CREDENTIALS)
    flow = Flow.from_client_config(creds_data, scopes=SCOPES)
    flow.redirect_uri = "http://localhost"
    auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent")

    await update.message.reply_text(
        "Click this link and sign in with Google:\n\n"
        f"{auth_url}\n\n"
        "You'll get an error page — that's normal. Copy the full URL from your browser's address bar and send it back using:\n\n"
        "/code PASTE_FULL_URL_HERE"
    )


async def code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    if not context.args:
        await update.message.reply_text(
            "Please include your code or URL. Example:\n/code 4/0Afr..."
        )
        return

    raw = " ".join(context.args).strip()

    # Extract code from full URL if pasted
    if "code=" in raw:
        raw = raw.split("code=")[1].split("&")[0]

    logger.info(f"Attempting auth with code: {raw[:20]}...")

    try:
        creds_data = json.loads(GOOGLE_CREDENTIALS)
        flow = Flow.from_client_config(creds_data, scopes=SCOPES)
        flow.redirect_uri = "http://localhost"
        flow.fetch_token(code=raw)
        creds = flow.credentials
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
        await update.message.reply_text(
            "✅ Google Calendar connected!\n\nTry /week to see upcoming events, or just tell me something to schedule."
        )
    except Exception as e:
        logger.error(f"Auth error: {e}")
        await update.message.reply_text(
            "That code didn't work — it may have expired. Type /auth to get a fresh link and try again immediately."
        )


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
        await update.message.reply_text(
            "Calendar not connected yet. Use /auth to connect."
        )
        return

    events = list_events(days=days)
    if not events:
        await update.message.reply_text(f"No events {label}.")
        return

    lines = [f"📅 Your events {label}:\n"]
    for e in events:
        start = e["start"].get("dateTime", e["start"].get("date", ""))
        if "T" in start:
            dt = datetime.datetime.fromisoformat(start.replace("Z", "+00:00"))
            time_str = dt.strftime("%a %b %-d at %-I:%M %p")
        else:
            dt = datetime.datetime.fromisoformat(start)
            time_str = dt.strftime("%a %b %-d (all day)")
        lines.append(f"• {e.get('summary', 'No title')} — {time_str}")

    await update.message.reply_text("\n".join(lines))


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ALLOWED_USER_ID:
        return

    user_message = update.message.text
    logger.info(f"Received: {user_message}")

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
            max_tokens=500,
            temperature=0.7
        )

        assistant_message = response.choices[0].message.content

        # Check for calendar actions
        if "CALENDAR_ACTION:" in assistant_message:
            lines = assistant_message.split("\n")
            reply_lines = []
            for line in lines:
                if line.startswith("CALENDAR_ACTION:"):
                    json_str = line.replace("CALENDAR_ACTION:", "").strip()
                    try:
                        action_data = json.loads(json_str)
                        cal_reply = await handle_calendar_action(action_data, update)
                        if cal_reply:
                            reply_lines.append(cal_reply)
                    except Exception as e:
                        logger.error(f"Calendar action error: {e}")
                else:
                    if line.strip():
                        reply_lines.append(line)
            assistant_message = "\n".join(reply_lines)

        conversation_history[user_id].append({"role": "assistant", "content": assistant_message})
        await update.message.reply_text(assistant_message)

    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text("Sorry, ran into an issue. Please try again.")


async def handle_calendar_action(action_data, update):
    action = action_data.get("action")

    if action == "create":
        service = get_calendar_service()
        if not service:
            return "I'd love to add that, but calendar isn't connected yet. Use /auth to connect."

        event = create_event(
            title=action_data.get("title", "Event"),
            start=action_data.get("start"),
            end=action_data.get("end"),
            description=action_data.get("description", "")
        )
        if event:
            return f"✅ Added to your calendar: {action_data.get('title')}"
        else:
            return "Couldn't add the event — something went wrong."

    elif action == "list":
        service = get_calendar_service()
        if not service:
            return "Calendar not connected. Use /auth to connect."

        days = action_data.get("days", 7)
        events = list_events(days=days)
        if not events:
            return "No upcoming events found."

        lines = ["📅 Here's what's coming up:\n"]
        for e in events:
            start = e["start"].get("dateTime", e["start"].get("date", ""))
            if "T" in start:
                dt = datetime.datetime.fromisoformat(start.replace("Z", "+00:00"))
                time_str = dt.strftime("%a %b %-d at %-I:%M %p")
            else:
                dt = datetime.datetime.fromisoformat(start)
                time_str = dt.strftime("%a %b %-d (all day)")
            lines.append(f"• {e.get('summary', 'No title')} — {time_str}")
        return "\n".join(lines)

    return None


async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    conversation_history.clear()
    await update.message.reply_text("Memory cleared — starting fresh!")


def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("auth", auth))
    app.add_handler(CommandHandler("code", code))
    app.add_handler(CommandHandler("today", today))
    app.add_handler(CommandHandler("week", week))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot is running...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

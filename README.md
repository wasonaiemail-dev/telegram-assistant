
# Marvin — Personal Assistant Bot

> A private Telegram bot that manages your life. Todos, calendar, reminders, notes, shopping lists, habits, morning briefings, and a persistent AI assistant — all in one chat thread.

**Setup time: ~20 minutes. No coding required.**

---

## What Marvin Does

Send Marvin a message and it handles the rest. Every feature is available by command or by plain English.

| Area | What you can do |
|---|---|
| 🌅 **Morning Briefing** | Daily digest of weather, calendar, todos, habits, quote, and word of the day |
| 📅 **Calendar** | View, add, update, and delete Google Calendar events by voice or command |
| ✅ **Todos** | Full Google Tasks integration — add, complete, delete, update |
| 🛒 **Shopping** | Multi-list management (grocery / household / wishlist) with auto-routing |
| 📝 **Notes** | Quick capture to Google Tasks, view and delete by number |
| ⏰ **Reminders** | One-time and recurring reminders — "remind me every Monday at 9am" |
| 💪 **Habits** | Log daily habits, get a nudge each evening, see yesterday in your briefing |
| 🧠 **Memory** | Teach Marvin facts about you — injected into every AI conversation |
| 💬 **Ask** | Persistent 8-hour AI conversation thread with optional live web search |
| 🎁 **Gifts** | Gift idea tracker per person, stored in Google Tasks |
| 👥 **Contacts** | Personal contact notes — facts about people in your life |
| 📊 **Weekly Summary** | AI-written narrative of your week every Monday morning |
| 🗓 **Event Prep** | Auto-generated prep notes before significant calendar events |
| ☀️ **Travel Weather** | Automatic weather alert when a trip is detected in your calendar |
| 🍽 **Meal Planning** | Plan meals, log adherence, get nutrition goal tracking |
| 💪 **Workout Tracking** | Log workouts, view history, export to Excel |
| 📔 **Journal** | Private daily journal with voice support and GPT reflections |
| 😊 **Mood Tracker** | 1–10 daily mood rating, trend analysis, GPT insights |
| 🔗 **Read Later** | Save links with AI summaries and tags, snooze, search, weekly digest |
| 💬 **Reply Assist** | Paste a message and Marvin drafts your response |
| 📤 **Data Export** | Export everything (journal, mood, notes, habits, memory, links) to Excel |
| 📧 **Gmail** | Send emails, save drafts, and check unread count — all by voice or natural language |

---

## Commands

```
/briefing       — Morning digest (weather, calendar, todos, habits, quote)
/cal            — View today's calendar events
/todo           — View and manage your todo list
/shopping       — View and manage shopping lists
/notes          — View and manage quick notes
/reminders      — View upcoming reminders
/habits         — View and log daily habits
/memory         — View and teach Marvin about you
/ask <question> — Start or continue an AI conversation
/gifts          — View and manage gift ideas
/contacts       — View and manage personal contact notes
/meals          — View and manage meal plan
/workout        — Log a workout or view history
/journal        — Start or continue today's journal entry
/mood           — Log today's mood (1–10)
/readlater      — Save a link or view your reading list
/export         — Export all data to an Excel file
/setup          — Re-run the initial setup wizard / configure preferences
/help           — List all commands
```

You can also just **type or talk naturally** — Marvin classifies your intent automatically. Voice messages work for everything:
> *"Remind me to call mum on Sunday at 5pm"*
> *"Add oat milk and eggs to the grocery list"*
> *"What's on my calendar next week?"*
> *"I'm feeling about a 7 today, had a rough morning but good workout"*
> 📷 Send a receipt photo to auto-remove items from your shopping lists

---

## How to Set Up

### Option A — Use the AI Setup Guide (recommended)
1. Open `setup/SETUP_COMPANION.md`
2. Copy the entire file
3. Paste it into [Claude](https://claude.ai) or ChatGPT
4. The AI will walk you through every step

### Option B — Follow the Visual Guide
Open `setup/Marvin_Buyer_Guide.pdf` — a 25-page illustrated guide with annotated screenshots for every step, written for people who have never used a terminal.

### What you'll need
- A free [Telegram](https://telegram.org) account
- An [OpenAI](https://platform.openai.com) account (pay-as-you-go, ~$1/month typical usage)
- A free [Railway](https://railway.app) account (hosting)
- A free [GitHub](https://github.com) account (to store and deploy the code)
- A free [Google Cloud](https://console.cloud.google.com) project (Calendar + Tasks access)

---

## Deploy to Railway

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template)

Or manually:
1. Fork this repo to your GitHub account
2. Create a new Railway project → Deploy from GitHub repo → select your fork
3. Add all variables from `.env.example` to Railway → Variables
4. Railway builds and starts Marvin automatically

---

## Tech Stack

- **Python 3.10+**
- **[python-telegram-bot 22.6](https://github.com/python-telegram-bot/python-telegram-bot)** — bot framework with job queue
- **[OpenAI API](https://platform.openai.com)** — intent classification, AI responses, whisper transcription (`gpt-4o-mini` / `gpt-4o` / `whisper-1`)
- **Google Calendar & Tasks API** — calendar and task management
- **[Open-Meteo](https://open-meteo.com)** — free weather API (no key required)
- **[Serper.dev](https://serper.dev)** — optional live web search in /ask
- **Railway** — hosting with persistent `/data` volume for user state

---

## Project Structure

```
marvin/
├── bot.py                  # Telegram bot — dispatcher + JobQueue scheduler (foreground)
├── discord_bot.py          # Discord bot — manual commands, runs in background
├── start.sh                # Launches both bots (Discord background + Telegram foreground)
├── core/
│   ├── config.py           # All constants and environment variables
│   ├── data.py             # JSON state management (memory, reminders, habits)
│   ├── intent.py           # GPT-powered intent classifier
│   └── google_auth.py      # Google OAuth + service setup
├── adapters/
│   ├── google_calendar.py  # Calendar CRUD wrapper
│   └── google_tasks.py     # Tasks CRUD wrapper
├── features/
│   ├── ask.py              # Persistent AI conversation thread
│   ├── briefing.py         # Morning briefing assembler
│   ├── calendar.py         # Calendar commands
│   ├── contacts.py         # Personal contact notes
│   ├── event_prep.py       # Pre-event prep notes
│   ├── gifts.py            # Gift idea tracker
│   ├── habits.py           # Habit logging and nudges
│   ├── memory.py           # Memory capture and injection
│   ├── notes.py            # Quick notes
│   ├── reminders.py        # Timed and recurring reminders
│   ├── reply_assist.py     # Draft replies to incoming messages
│   ├── setup.py            # First-run setup wizard + preferences
│   ├── shopping.py         # Multi-list shopping + receipt photo processing
│   ├── summary.py          # Weekly AI narrative
│   ├── todos.py            # Todo list management
│   ├── journal.py          # Daily journal with voice + GPT reflection
│   ├── mood.py             # Mood logging and trend analysis
│   ├── meals.py            # Meal planning and nutrition tracking
│   ├── workout.py          # Workout logging and history
│   ├── links.py            # Read-later link saver with AI summaries
│   └── export_data.py      # Full data export to Excel
├── setup/
│   ├── SETUP_COMPANION.md  # AI-guided setup wizard (paste into Claude/GPT)
│   └── Marvin_Buyer_Guide.pdf  # Illustrated visual setup guide
├── .env.example            # All environment variables with descriptions
├── railway.json            # Railway deployment config
├── Procfile                # Fallback process definition
└── requirements.txt        # Python dependencies
```

---

## License

For personal use only. Do not redistribute or resell.

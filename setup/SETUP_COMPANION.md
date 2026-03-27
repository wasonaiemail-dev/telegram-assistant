# Alfred Setup Companion
### Your AI-guided installer — paste this entire document into Claude or ChatGPT

---

> **How this works:** You are about to set up your personal assistant bot. I will ask you questions one section at a time. Your answers will be used to configure Alfred specifically for you — your timezone, your habits, your shopping lists, your quote style, and everything else. At the end, I will give you a complete `config.py` file ready to deploy, and a checklist of every Railway variable to set.
>
> Let's begin. Just answer each question as naturally as you'd like — short bullet lists or full sentences are both fine.

---

## SECTION 1 — Identity & Basics

**Q1. What do you want to call your assistant?**
> Examples: Alfred, Aria, Max, J.A.R.V.I.S., Friday
> *(This is the name it will use when it introduces itself and signs messages.)*

**Q2. What is your timezone?**
> Examples: `America/New_York`, `America/Los_Angeles`, `Europe/London`, `Asia/Tokyo`
> Full list: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones

**Q3. What time do you want your morning briefing sent?**
> Examples: 7:00 AM, 6:30 AM, 8:00 AM
> *(This is the daily summary Alfred sends — weather, tasks, habits, calendar, quote, and word of the day.)*

---

## SECTION 2 — Location & Weather

**Q4. What city do you live in?**
> *(Used for daily weather in your briefing and for detecting when you're traveling.)*

**Q5. What is the latitude and longitude of your home city?**
> *(Look yours up at https://www.latlong.net — paste the two numbers.)*
> Example: `40.7608, -111.8910`

**Q6. What are some common ways you'd refer to being home in a calendar event?**
> *(Alfred uses these to tell the difference between local and travel events.)*
> Example: "Salt Lake City, SLC, Utah, downtown"

---

## SECTION 3 — Daily Quote

**Q7. What style of daily quote would you like in your morning briefing?**
> Pick one: **stoic**, **bible verse**, **motivational**, **philosophical**, or **none**
> *(Alfred uses a live API for quotes, with GPT as a fallback if the API is down.)*

---

## SECTION 4 — Habit Tracker

**Q8. What habits do you want to track daily?**
> List each habit on its own line. Be specific — use the name you'd naturally say.
> Example:
> - Morning workout
> - Drinking enough water
> - Meditation
> - Reading 20 pages
> - Taking vitamins

**Q9. For each habit, what phrases would you naturally say or type to log it?**
> *(Alfred will auto-suggest these based on your habit names — you just confirm or edit them.)*
> You can skip this for now and let Alfred generate suggestions after you answer Q8.

---

## SECTION 5 — Shopping Lists

**Q10. What shopping lists do you want?**
> Most people use 2–4. Name them whatever makes sense to you.
> Examples: Grocery, Household, Baby, Wishlist, Costco, Amazon

**Q11. For each list, what kinds of items automatically belong there?**
> *(Alfred uses these to auto-sort items without you having to specify a list every time.)*
> Example for "Household": "toilet paper, paper towels, cleaning supplies, batteries, light bulbs"
> Example for "Baby": "diapers, wipes, formula, baby food, anything with my kid's name"
>
> *(You can also paste a screenshot of an existing shopping list and Alfred will import it.)*

---

## SECTION 6 — Google Calendar

**Q12. Which Google Calendar do you want Alfred to read from?**
> Most people only have one — just answer "my main calendar" or "primary" and
> Alfred will use that automatically.
>
> If you have multiple calendars (e.g. a work calendar and a personal calendar)
> and want Alfred to see both, list them. You can find a calendar's ID in
> Google Calendar → Settings → click the calendar name → "Integrate calendar."
>
> Example: "Just my main calendar" or "Primary + family@group.calendar.google.com"

---

**Q13. Do you want Alfred to send event prep briefings?**
> The night before a significant event, Alfred sends you a briefing with the
> event details, location, guests, and any notes — so you're never caught off
> guard by an important meeting or event.
> Answer: **yes** or **no**

**Q14 (if yes). What makes an event "significant" for you?**
> Alfred uses this to decide which events deserve a prep briefing.
>
> Alfred already flags events with these words in the title by default:
> "interview, presentation, pitch, demo, review, conference, wedding, dinner,
> party, surgery, flight, travel, trip, meeting, date"
>
> Are there words or types of events you'd add or remove from that list?
> Example: "Add 'client call' and 'board'. Remove 'dinner' — I have dinner
> on my calendar constantly and don't need a briefing for every one."

**Q15 (if yes). Are there any recurring events Alfred should never prep you for?**
> Alfred already skips events with these words: "lunch, break, focus time,
> blocked, busy, commute, gym"
>
> Anything else to add?
> Example: "Also skip 'standup' and 'sync'"

---

**Q16. Do you want travel weather alerts?**
> Alfred scans your calendar each evening and sends a weather forecast for any
> event that appears to be in a different city (based on the event's location).
> Answer: **yes** or **no**

**Q17 (if yes). How many days ahead should Alfred scan for travel events?**
> Default is 3 days. Increase this if you like to prepare further in advance.

---

## SECTION 7 — Reminders & Todos

**Q18. Do you want recurring todos or reminders?**
> *(For example: "Take vitamins" every day, "Review budget" every month, "Team meeting" every weekday.)*
> You can add these after setup too — this just confirms you want the feature.
> Answer: **yes** or **no**

---

## SECTION 8 — Alfred Memory

Alfred has a long-term memory system with **10 built-in categories** and support for custom ones.
Memory is stored permanently on Railway and injected into conversations so Alfred always has context.
You configure this **directly in Telegram** using the `/setup` command after Alfred is deployed — no env vars needed.

**How memory injection works:**
Alfred doesn't inject all 10 categories into every GPT call (that would be expensive).
Instead, it always includes *Me* and *Preferences*, then adds other categories only when your message contains relevant keywords.
For example, a question about a medication automatically pulls in your *Health* category. A message about your budget pulls in *Finance*.

**Q19. After Alfred is deployed, run `/setup memory` in Telegram.**

Alfred will walk you through each category with guided questions:

| Category | What goes here |
|---|---|
| **Me** | Name, age, city, personality, communication style |
| **Family** | Spouse/partner, kids, parents, siblings — names, ages, birthdays |
| **Work** | Employer, role, current projects, key colleagues |
| **Health** | Conditions, allergies, medications, dietary restrictions |
| **Finance** | Budget ranges, financial goals, subscriptions |
| **Goals** | Short and long-term targets, personal and professional |
| **Social** | Close friends, recurring social commitments |
| **Travel** | Upcoming trips, preferred airlines/hotels, travel style |
| **Preferences** | Likes/dislikes, how you want Alfred to respond, hobbies |
| **Ongoing** | Things you're actively tracking or working on right now |

You can skip any category and come back later. Type *skip* to skip a question, or *done* to move to the next category.

**Q20. Do you want any custom categories beyond the 10 defaults?**
> Custom categories let you track anything specific to your life.
> Examples: *Pets*, *Hobbies*, *Business*, *Clients*
>
> If yes: during `/setup`, tap **Add custom category** from the setup menu.
> Or after setup: `/memory addcat [name]`
>
> Answer: **yes** (jot down the names) or **no**

**Useful memory commands to know after setup:**
```
/memory               — view everything Alfred knows
/memory [category]    — view one category
/memory add [cat] [fact]   — add a fact directly
/memory remove [cat] [#]   — remove a fact by number
/memory clear [cat]        — wipe a category
/setup memory [cat]        — re-run the wizard for one category
```

**Auto-suggest:** During conversations, if you mention something memorable
(e.g. "by the way, I'm allergic to shellfish"), Alfred will ask:
*"Should I remember that?"* with a Yes/No button. Nothing is saved without your confirmation.

---

## SECTION 9 — /Ask & Web Search

**Q21. Do you want Alfred to search the web when you ask questions?**
> *(This uses the Serper.dev API — free tier is 2,500 searches/month.)*
> If yes: sign up at https://serper.dev and have your API key ready.
> Answer: **yes** or **no**

---

---

## SECTION 9B — Gift Tracker & Personal Contacts

These two features require no configuration — they work out of the box once Alfred is deployed.

**Gift Tracker** stores gift ideas per person in Google Tasks under "Alfred: Gifts".
```
/gifts                          — view all gift ideas grouped by person
add gift for Sarah: silk scarf  — add an idea by plain text
```
Intent examples Alfred understands:
- "I need a gift idea for dad"
- "Add blue headphones to Tom's gift list"
- "Mark the book I got for Emma as done"

**Personal Contacts** stores notes about people in your life (birthday, preferences, notes).
```
/contacts                       — view all contacts
/contacts Sarah                 — view notes for Sarah
add contact note for Sarah: loves hiking
```
Intent examples Alfred understands:
- "What do I know about Mike?"
- "Remember that James is vegetarian"
- "Update Tom's birthday to March 3rd"

*No questions to answer — move on to Section 10.*

## SECTION 10 — Telegram Setup

**Q22. What is your Telegram bot's username?**
> *(This is the @username you set in BotFather, e.g. `myalfred_bot`)*
> *(Used to generate your Quick Capture deep link for the home screen shortcut.)*

---

## SECTION 11 — Google Account Connection

> This is done **after** Alfred is deployed on Railway. It is a one-time setup.
> There are two parts: (A) creating Google API credentials, and (B) connecting
> your account to Alfred via Telegram.

---

### Part A — Create Google API Credentials (one time, ~5 minutes)

Alfred needs a `credentials.json` file from Google Cloud to be allowed to
access your Calendar and Tasks. Here is exactly how to get it:

**Step A1 — Go to Google Cloud Console**
Open https://console.cloud.google.com in your browser.
Sign in with the Google account whose Calendar and Tasks Alfred will use.

**Step A2 — Create a new project**
Click the project dropdown at the top → "New Project" → give it any name
(e.g. "Alfred Bot") → click Create.

**Step A3 — Enable the two APIs**
In the left sidebar, go to **APIs & Services → Library**.
Search for "Google Calendar API" → click it → click **Enable**.
Go back to Library, search "Tasks API" → click it → click **Enable**.

**Step A4 — Create OAuth credentials**
Go to **APIs & Services → Credentials** → click **+ Create Credentials** →
choose **OAuth client ID**.

If prompted to configure a consent screen first:
- Choose **External**
- Fill in App name (e.g. "Alfred"), your email for support and developer fields
- Click Save and Continue through the rest (no scopes or test users needed yet)
- Return to Credentials → + Create Credentials → OAuth client ID

On the OAuth client ID screen:
- Application type: **Desktop app**
- Name: anything (e.g. "Alfred Desktop")
- Click **Create**

**Step A5 — Download credentials.json**
A popup will show your client ID and secret. Click **Download JSON**.
Open the downloaded file in a text editor. You will see something like:
```json
{"installed":{"client_id":"...","client_secret":"...","redirect_uris":[...],...}}
```
Copy the **entire contents** of this file — you will paste it as the
`GOOGLE_CREDENTIALS` environment variable in Railway.

**Step A6 — Add yourself as a test user**
In Google Cloud Console, go to **APIs & Services → OAuth consent screen**.
Scroll to "Test users" → click **Add users** → enter your Google email.
This lets Alfred authenticate before the app is formally verified by Google.

---

### Part B — Connect Alfred to Your Google Account (in Telegram)

> Do this after Alfred is deployed on Railway and you can receive messages
> from your bot.

**Step B1 — Run /auth in Telegram**
Alfred sends you a long Google sign-in URL. Open it in your browser.

**Step B2 — Sign in and approve**
Sign in with the same Google account you used above.
Approve the Calendar and Tasks permissions.

**Step B3 — Copy the auth code**
After approving, your browser redirects to a page that shows an error —
**that is completely normal.** Look at the address bar. Copy everything
after `code=` and before `&scope`. It will start with `4/0A...`.

**Step B4 — Send /code to Alfred**
Send Alfred: `/code 4/0Afr... (your full code)`

**Step B5 — Confirm**
Alfred replies "Google connected successfully." Verify any time with
`/checkauth`.

---

**Token expiry note:** Tokens last 7 days. Alfred auto-refreshes on every
API call as long as the bot is running. If the bot was offline long enough
that the token expired, Alfred warns you at 6:50 AM and asks you to run
`/auth` again. This is rare with Railway's always-on hosting.

---

## WHAT HAPPENS NEXT

Once you have answered all questions, I will:
1. Generate your complete `core/config.py` with your values filled in
2. Walk you through the GitHub drag-and-drop deployment step by step
3. Confirm Alfred is live with a test message
4. Prompt you to run `/setup memory` in Telegram to seed Alfred's memory

**After Alfred is live, first commands to run:**
```
/checkauth          — confirm Google Calendar + Tasks are connected
/setup memory       — walk through each memory category with guided questions
/briefing           — test your first morning briefing
/gifts              — view your gift tracker (empty until you add ideas)
/contacts           — view your contacts (empty until you add notes)
```

**Ready? Start with Section 1 — just answer Q1.**

---

## APPENDIX — Railway Environment Variables Reference

Set all of these in Railway → your project → **Variables** tab before deploying.

| Variable | Required | What it is | Example |
|---|---|---|---|
| `TELEGRAM_TOKEN` | ✅ | Bot token from BotFather | `7123456789:AAF...` |
| `ALLOWED_USER_ID` | ✅ | Your Telegram numeric user ID | `123456789` |
| `OPENAI_API_KEY` | ✅ | OpenAI API key | `sk-proj-...` |
| `GOOGLE_CREDENTIALS` | ✅ | Full contents of credentials.json | `{"installed":{...}}` |
| `BOT_NAME` | ✅ | What to call your assistant | `Alfred` |
| `TIMEZONE` | ✅ | Your timezone (tz database format) | `America/New_York` |
| `WEATHER_LAT` | ✅ | Home city latitude | `40.7608` |
| `WEATHER_LON` | ✅ | Home city longitude | `-111.8910` |
| `HOME_CITY` | ✅ | Home city name (lowercase) | `salt lake city` |
| `BOT_USERNAME` | ✅ | Bot @username from BotFather | `myalfred_bot` |
| `BRIEFING_HOUR` | ✅ | Morning briefing hour (24h) | `7` |
| `BRIEFING_MINUTE` | ✅ | Morning briefing minute | `0` |
| `QUOTE_TYPE` | ✅ | Daily quote style | `stoic` |
| `SERPER_API_KEY` | optional | Serper.dev key for web search | `abc123...` |
| `HABIT_NUDGE_HOUR` | optional | Daily habit nudge hour (24h) | `20` |
| `HABIT_NUDGE_MINUTE` | optional | Daily habit nudge minute | `0` |
| `WEEKLY_SUMMARY_HOUR` | optional | Weekly summary hour (24h) | `9` |
| `WEEKLY_SUMMARY_MINUTE` | optional | Weekly summary minute | `0` |
| `WEEKLY_SUMMARY_WEEKDAY` | optional | Weekly summary day (0=Mon, 6=Sun) | `0` |
| `TRAVEL_WEATHER_HOUR` | optional | Travel weather check hour | `7` |
| `TRAVEL_WEATHER_MINUTE` | optional | Travel weather check minute | `0` |

**How to find your Telegram user ID:**
Send a message to [@userinfobot](https://t.me/userinfobot) on Telegram — it replies with your numeric ID.

**How to find your home city coordinates:**
Go to https://www.latlong.net, search your city, copy the latitude and longitude.

---

*Alfred Setup Companion v1.0 — built alongside Alfred core v1.0*

# Alfred Setup Wizard
### Paste this entire document into Claude or ChatGPT to begin

---

> **FOR THE AI RUNNING THIS WIZARD — READ THIS FIRST:**
>
> You are a friendly setup assistant helping someone deploy Alfred, a personal AI assistant Telegram bot hosted on Railway.app. Your job is to walk the buyer through collecting every required piece of information, then at the very end output a **single, complete KEY=VALUE block** with all their real values filled in — ready to paste directly into Railway's Raw Editor in one shot.
>
> **Two modes are available. The first thing you do is ask which one to use:**
>
> - **Standard Mode** — works with Claude or ChatGPT. You give step-by-step text instructions and the buyer follows them manually. Takes ~45 minutes.
> - **Express Mode** — Claude desktop only, with Chrome control enabled. You control the buyer's browser to handle all navigation and clicking. The buyer only touches credential fields (tokens, API keys). Takes ~20 minutes.
>
> **How to run this:**
> - Ask the mode question first (see opening message below). Then follow the matching instructions for each step.
> - Go through steps **one at a time**. Ask one question, wait for the answer, then move to the next.
> - Keep a running record of every value collected — you'll need them all for the final output block.
> - Do NOT output the final block until every step is complete.
> - When all steps are done, output the block under the heading **"✅ Your Railway Variables — Copy This Entire Block"** in a single code block, with every value filled in.
> - After the block, walk them through the deployment steps.
>
> **If the buyer chooses Express Mode and you are not Claude with Chrome control enabled:** Let them know Express Mode requires Claude's desktop app with computer use turned on (Settings → Desktop app → Computer use). Offer to continue in Standard Mode instead.
>
> **Start the conversation with this exact message:**
>
> "Hi! I'm going to walk you through setting up Alfred. Before we start — are you using **Claude's desktop app** with computer use enabled?
>
> If yes, I can run **Express Mode**: I'll control your browser and handle all the navigation and clicking automatically. You only touch the fields where you paste your actual keys and tokens. Setup takes about 20 minutes.
>
> If no (or you're using ChatGPT), I'll run **Standard Mode**: I'll give you step-by-step instructions and you follow along. Takes about 45 minutes.
>
> Which would you like?"

---

## STEP 1 — Telegram Bot Token + Username

**Variables collected:** `TELEGRAM_TOKEN`, `BOT_USERNAME`

**STANDARD MODE — If they haven't created a bot yet, give these exact instructions:**

1. Open Telegram and search for **@BotFather**
2. Start a chat with BotFather and send the message `/newbot`
3. It will ask for a name — this is the display name (e.g. "My Alfred"). Type anything you like.
4. It will then ask for a username — this must end in `bot` (e.g. `myalfred_bot`). Choose one.
5. BotFather will reply with a message containing your **bot token** — it looks like `7123456789:AAFxxx_yyy`. Copy that token.

**EXPRESS MODE:** BotFather requires interaction inside the Telegram app itself, which cannot be automated. Ask the buyer to complete Step 1 manually using the Standard instructions above, then paste the token back into the chat when done. This is the only step Express Mode cannot handle.

**Collect:** Ask them to paste their bot token and confirm their bot's username (the @username without the @).

---

## STEP 2 — Telegram User ID

**Variable collected:** `ALLOWED_USER_ID`

**STANDARD MODE — Instructions to give:**

1. Open Telegram and search for **@userinfobot**
2. Start a chat and send any message (e.g. "hi")
3. It will instantly reply with your numeric user ID — a number like `123456789`

**EXPRESS MODE:** Open `web.telegram.org` in Chrome. Once the buyer logs in, navigate to the @userinfobot conversation. Ask the buyer to send "hi" to the bot, then read the numeric User ID that appears in the reply and record it. Confirm to the buyer: "Got your User ID — you don't need to copy anything."

**Collect:** The numeric user ID (sourced from screen in Express Mode, pasted by buyer in Standard Mode).

---

## STEP 3 — OpenAI API Key

**Variable collected:** `OPENAI_API_KEY`

**STANDARD MODE — Instructions to give:**

1. Go to **platform.openai.com** → sign in
2. Click your profile icon (top right) → **API keys**
3. Click **Create new secret key** → give it any name → click Create
4. Copy the key immediately — it starts with `sk-proj-` and you can only see it once

**EXPRESS MODE:** Navigate to `platform.openai.com`. Once the buyer is logged in, click through to the API keys page and click "Create new secret key." When the key appears, it will be masked — stop and say: "Your new key is on screen. Copy it now — this is the only time it's visible." Wait for them to confirm they've copied it, then ask them to paste it into the chat.

**Collect:** Ask them to paste their OpenAI API key.

---

## STEP 4 — Google Credentials

**Variable collected:** `GOOGLE_CREDENTIALS`

**STANDARD MODE — Instructions to give — walk through this exactly:**

> "Now we need to connect Alfred to your Google Calendar and Tasks. This takes about 5 minutes. Follow these steps exactly:"

**Step 4A — Create a Google Cloud project:**
1. Go to **console.cloud.google.com** and sign in with the Google account whose Calendar Alfred will use
2. Click the project dropdown at the very top of the page → click **New Project**
3. Give it any name (e.g. `Alfred Bot`) → click **Create**
4. Make sure your new project is selected in the dropdown before continuing

**Step 4B — Enable the two APIs:**
1. In the left sidebar, click **APIs & Services** → **Library**
2. Search `Google Calendar API` → click it → click **Enable**
3. Click the back arrow, then search `Tasks API` → click it → click **Enable**

**Step 4C — Set up the consent screen:**
1. In the left sidebar, click **APIs & Services** → **OAuth consent screen**
2. Choose **External** → click **Create**
3. Fill in **App name** (e.g. `Alfred`) and your email for both support and developer contact
4. Click **Save and Continue** through the remaining screens without changing anything
5. On the **Test users** screen, click **Add users** → type in your Google email → click **Save**
6. Click **Back to Dashboard** → click **Publish App** → confirm when prompted

> ⚠️ **Why step 6 matters:** Apps left in Testing mode have refresh tokens that expire after 7 days, forcing you to run `/auth` every week. Publishing the app makes your refresh token last indefinitely (until you revoke it). For a personal bot with Calendar + Tasks scopes, Google does not require a review — it will show a one-time "unverified app" warning when you first connect, which is safe to click through.

**Step 4D — Create credentials:**
1. In the left sidebar, click **APIs & Services** → **Credentials**
2. Click **+ Create Credentials** at the top → choose **OAuth client ID**
3. Application type: **Desktop app** → Name: anything (e.g. `Alfred`) → click **Create**
4. A popup appears — click **Download JSON** (the download button)

**Step 4E — Copy the file contents:**
1. Find the downloaded file (usually in Downloads, named something like `client_secret_xxx.json`)
2. Open it with any text editor (TextEdit on Mac, Notepad on Windows)
3. Select all the text and copy it — it should start with `{"installed":{` and be one long line or a few lines

**Collect:** Ask them to paste the entire contents of the JSON file. Tell them it's okay if it looks messy — you'll handle it. When they paste it, confirm you received it and move on (you'll put it on a single line in the final output).

---

**EXPRESS MODE — Step 4 is where Express Mode saves the most time. Do all of the following in Chrome:**

> Tell the buyer: "I'm going to handle the Google Cloud setup for you. Sign into console.cloud.google.com with the Google account you want Alfred to use for Calendar, then let me know when you're in."

Once they confirm they're logged in:

1. **Create project:** Click the project dropdown (top of page) → New Project → type `Alfred Bot` → click Create. Wait for creation notification, then click "Select Project."
2. **Enable Calendar API:** Navigate to APIs & Services → Library → search "Google Calendar API" → click it → click Enable.
3. **Enable Tasks API:** Navigate back to Library → search "Tasks API" → click it → click Enable.
4. **Consent screen:** Navigate to APIs & Services → OAuth consent screen → select External → click Create. Fill in App name as `Alfred`. Ask the buyer: "What email address should I use for the support and developer contact fields?" Fill both fields with their answer → click Save and Continue through all remaining screens → on Test Users screen, click Add Users, type in the buyer's Google email, click Save and Continue → click Back to Dashboard.
5. **Create credentials:** Navigate to APIs & Services → Credentials → click + Create Credentials → OAuth client ID → Application type: Desktop app → Name: `Alfred` → click Create.
6. **Download JSON:** In the popup that appears, click the Download JSON button. Say to the buyer: "A file just downloaded to your Downloads folder — please drag it into this chat." Wait for them to share it. Read the file content directly from the upload. Record the full JSON for the final output block.

> Tell the buyer: "Done — I've set up all of Google Cloud for you and captured the credentials. You don't need to open or touch that file."

---

## STEP 5 — Web Search (Optional)

**Variable collected:** `SERPER_API_KEY`

Ask: "Alfred can search the web when you ask it questions. This uses Serper.dev — the free tier gives you 2,500 searches a month which is plenty. Do you want to set this up, or skip it for now?"

**STANDARD MODE — If yes:**
1. Go to **serper.dev** → sign up for a free account
2. After signing in, your API key is shown on the dashboard
3. Copy it

**EXPRESS MODE — If yes:** Navigate to `serper.dev`. Once the buyer is signed in, read the API key directly from the dashboard and record it. Confirm to the buyer: "Got your Serper key — no need to copy anything."

**If no:** Leave SERPER_API_KEY blank in the final block.

**Collect:** Their Serper API key, or "skip."

---

## STEP 6 — Assistant Name

**Variable collected:** `BOT_NAME`

**Ask:** "What do you want to call your assistant? This is the name it uses when it introduces itself."

> Examples: Alfred, Aria, Max, Friday

**Default if they don't care:** `Alfred`

---

## STEP 7 — Timezone

**Variable collected:** `TIMEZONE`

**Ask:** "What's your timezone? I need the exact format — here are the most common ones:
- US Eastern: `America/New_York`
- US Central: `America/Chicago`
- US Mountain: `America/Denver`
- US Pacific: `America/Los_Angeles`
- UK: `Europe/London`
- Central Europe: `Europe/Berlin`
- Australia East: `Australia/Sydney`
- Japan: `Asia/Tokyo`

If yours isn't listed, tell me your city and I'll give you the right one."

---

## STEP 8 — Home City & Coordinates

**Variables collected:** `HOME_CITY`, `WEATHER_LAT`, `WEATHER_LON`

**Ask:** "What city do you live in? This is used for daily weather in your briefing."

**After they answer:** Do NOT ask the buyer for coordinates. Look them up yourself using your web search or built-in knowledge. Find the latitude and longitude for their city and use those values directly in the final output block. Confirm to the buyer: "Got it — I've looked up the coordinates for [city] automatically."

**Collect:** City name only. Coordinates are sourced by you.

---

## STEP 9 — Morning Briefing Time

**Variables collected:** `BRIEFING_HOUR`, `BRIEFING_MINUTE`

**Ask:** "What time do you want your morning briefing? Alfred sends this every day — weather, calendar, habits, todos, and more."

**Convert their answer** to 24-hour format: "7:30am" → BRIEFING_HOUR=7, BRIEFING_MINUTE=30. "8am" → BRIEFING_HOUR=8, BRIEFING_MINUTE=0.

**Default if they don't care:** 7:30am

---

## STEP 10 — Daily Quote Style

**Variable collected:** `QUOTE_TYPE`

**Ask:** "What style of daily quote would you like in your morning briefing?"

Options:
- `stoic` — Marcus Aurelius, Seneca, Epictetus
- `motivational` — high-energy, action-focused
- `philosophical` — broad philosophical wisdom
- `none` — skip the quote entirely

**Default:** `stoic`

---

## STEP 11 — Evening Habit Nudge Time

**Variables collected:** `HABIT_NUDGE_HOUR`, `HABIT_NUDGE_MINUTE`

**Ask:** "What time should Alfred send your evening habit nudge — a quick check-in on which habits you've logged today?"

**Convert to 24h.** Default if they don't care: 8:00pm → HABIT_NUDGE_HOUR=20, HABIT_NUDGE_MINUTE=0

---

## STEP 12 — Weekly Summary Schedule

**Variables collected:** `WEEKLY_SUMMARY_HOUR`, `WEEKLY_SUMMARY_MINUTE`, `WEEKLY_SUMMARY_WEEKDAY`

**Ask:** "When do you want your weekly AI summary delivered? This is a full week-in-review with patterns, wins, and smart suggestions."

**Convert:**
- Day name → number: Monday=0, Tuesday=1, Wednesday=2, Thursday=3, Friday=4, Saturday=5, Sunday=6
- Time → 24h

**Default:** Monday at 9:00am → WEEKLY_SUMMARY_WEEKDAY=0, WEEKLY_SUMMARY_HOUR=9, WEEKLY_SUMMARY_MINUTE=0

---

## STEP 13 — Travel Weather Alert Time

**Variables collected:** `TRAVEL_WEATHER_HOUR`, `TRAVEL_WEATHER_MINUTE`

**Ask:** "Alfred can check your calendar each evening and send a weather forecast for any trips coming up in the next few days. What time should it run this check?"

**Default:** 7:00pm → TRAVEL_WEATHER_HOUR=19, TRAVEL_WEATHER_MINUTE=0

**Note:** This is optional — if they don't want it at all, note it but still include the variable (it won't fire if there are no travel events in the calendar).

---

## STEP 14 — Discord (Optional)

**Variables collected:** `DISCORD_TOKEN`, `DISCORD_ALLOWED_USER_ID`

**Ask:** "Alfred also works on Discord — you can control it from any Discord server or DM. Do you want to set up Discord access now, or skip it?"

**If they say skip:** Leave both variables blank in the final output block. Discord simply won't start.

**STANDARD MODE — If yes:**

1. Go to **discord.com/developers/applications** and sign in
2. Click **New Application** → give it any name (e.g. `Alfred`) → click **Create**
3. In the left sidebar, click **Bot**
4. Click **Reset Token** → confirm → copy the token that appears
5. Scroll down to **Privileged Gateway Intents** → enable **Message Content Intent** → click **Save Changes**
6. In the left sidebar, click **OAuth2 → URL Generator**
7. Under Scopes, check `bot`. Under Bot Permissions, check `Send Messages`, `Read Message History`, `Read Messages/View Channels`
8. Copy the generated URL at the bottom and open it in a browser → choose the server to add Alfred to → click **Authorize**
9. To get your Discord user ID: in Discord, go to Settings → Advanced → turn on Developer Mode → right-click your name anywhere → **Copy User ID**

**EXPRESS MODE:** Navigate to `discord.com/developers/applications`. Once the buyer is in:
1. Click New Application, name it Alfred, click Create.
2. Click Bot in the sidebar → click Reset Token → confirm → read and record the token.
3. Enable Message Content Intent → Save Changes.
4. Click OAuth2 → URL Generator → check `bot` scope → check Send Messages, Read Message History, Read Messages/View Channels → copy the invite URL.
5. Open the invite URL in a new tab → ask the buyer to select their server and click Authorize.
6. Ask the buyer to right-click their username in Discord and choose Copy User ID (requires Developer Mode in Discord Settings → Advanced). Record it.

**Collect:** Their Discord bot token and their Discord user ID.

---

## STEP 15 — Gmail (Optional)

**Variables collected:** `GMAIL_VIP_SENDERS`, `GMAIL_DEFAULT_SIGNATURE`

**Ask:** "Alfred can read, send, and draft emails through Gmail. To enable it, you'll need to re-run `/auth` in Telegram after deployment so Alfred can request Gmail access — it'll be added to the same Google consent screen you already set up. Do you want to configure Gmail options now?"

**If they say skip:** Leave both variables blank in the final output block. Gmail features will still be available once they run `/auth`, just without VIP senders or a signature.

**If yes, ask two sub-questions:**

**15A — VIP Senders (optional):**
"Do you have any email addresses you consider VIP — like a boss, partner, or important client? If so, list them separated by commas. Alfred will highlight unread emails from these senders in your morning briefing."

Example: `boss@company.com,mom@gmail.com`

Leave blank if they don't want this.

**15B — Email Signature (optional):**
"Do you want a signature automatically added to every email Alfred sends or drafts? If yes, what should it say?"

Example: `Tyler` or `Best, Tyler Wason`

Leave blank if they don't want one.

**Important note for Standard and Express Mode:**

> ⚠️ After deployment, you must run `/auth` in Telegram to grant Gmail access. Alfred will open a Google consent screen — you'll see Gmail listed alongside Calendar and Tasks. Click through to authorize it. You only need to do this once.
>
> Also: in Google Cloud Console (from Step 4), go to **APIs & Services → Library** and enable **Gmail API** if you want Gmail features to work.

**Collect:** Their VIP sender emails (or blank) and their signature (or blank).

---

## FINAL OUTPUT

When all steps are complete, output this **exactly**, with every placeholder replaced with their real values. Leave the Discord variables blank if the buyer skipped Step 14.

```
TELEGRAM_TOKEN=[their token]
ALLOWED_USER_ID=[their user ID]
OPENAI_API_KEY=[their OpenAI key]
GOOGLE_CREDENTIALS=[their credentials JSON, minified to a single line]
SERPER_API_KEY=[their Serper key, or leave blank]
BOT_NAME=[their bot name]
BOT_USERNAME=[their bot username, no @]
TIMEZONE=[their timezone string]
HOME_CITY=[their city]
WEATHER_LAT=[their latitude]
WEATHER_LON=[their longitude]
BRIEFING_HOUR=[hour as integer]
BRIEFING_MINUTE=[minute as integer]
QUOTE_TYPE=[their quote style]
HABIT_NUDGE_HOUR=[hour as integer]
HABIT_NUDGE_MINUTE=[minute as integer]
WEEKLY_SUMMARY_HOUR=[hour as integer]
WEEKLY_SUMMARY_MINUTE=[minute as integer]
WEEKLY_SUMMARY_WEEKDAY=[0-6]
TRAVEL_WEATHER_HOUR=[hour as integer]
TRAVEL_WEATHER_MINUTE=[minute as integer]
DISCORD_TOKEN=[their Discord bot token, or leave blank]
DISCORD_ALLOWED_USER_ID=[their Discord user ID, or leave blank]
GMAIL_VIP_SENDERS=[comma-separated VIP emails, or leave blank]
GMAIL_DEFAULT_SIGNATURE=[email signature text, or leave blank]
```

**Important — Google Credentials formatting:**
The JSON they pasted may have line breaks. Before including it in the output block, collapse it to a single line by removing all newlines and extra spaces, so the entire JSON value sits on one line after `GOOGLE_CREDENTIALS=`. Do not add quotes around it.

**Then walk them through these deployment steps exactly as written:**

---

## DEPLOYMENT — Click-by-Click

### PART 1 — Get Alfred's code onto GitHub

**STANDARD MODE:**

**Step 1 — Install GitHub Desktop**
1. Go to **desktop.github.com** and download GitHub Desktop
2. Install it and sign in with your GitHub account

**Step 2 — Clone your repo**
1. Open GitHub Desktop
2. Click **File → Clone Repository**
3. Find your `telegram-assistant` repo in the list and click it
4. Choose where to save it on your computer (Desktop is fine)
5. Click **Clone**

**Step 3 — Replace all the files**
1. In GitHub Desktop, click the **Show in Finder** (Mac) or **Show in Explorer** (Windows) button at the top
2. Delete everything currently inside that folder — you should see 4 old files: `Procfile`, `README.md`, `bot.py`, `requirements.txt`. Delete all of them.
3. Open a second window and navigate to your **AI → alfred** folder
4. Select everything inside it: `bot.py`, `requirements.txt`, `Procfile`, `README.md`, `railway.json`, `.gitignore`, and the folders `core/`, `features/`, `adapters/`, `plugins/`, `setup/`
5. Copy and paste all of it into the cloned `telegram-assistant` folder

The folder should now contain:
```
adapters/   core/   features/   plugins/   setup/
bot.py   Procfile   railway.json   README.md   requirements.txt
```

If there is a `__pycache__` folder visible, delete it — it doesn't belong in the repo.

**Step 4 — Commit and push**
1. Go back to **GitHub Desktop** — you'll see a list of all the new files on the left side
2. In the bottom-left box, type: `Deploy Alfred v2`
3. Click **Commit to main**
4. Click **Push origin** at the top right

Alfred's code is now on GitHub.

---

**EXPRESS MODE — GitHub upload:**

> Tell the buyer: "Now I'll get Alfred's code onto GitHub. Open GitHub Desktop and let me know when it's open."

Once they confirm:
1. Ask the buyer to click **File → Clone Repository**, find the `telegram-assistant` repo, and clone it to their Desktop. Ask them to let you know once cloning is done.
2. Once cloned, ask: "Can you click 'Show in Finder' (Mac) or 'Show in Explorer' (Windows) in GitHub Desktop?" Read the folder contents from the screen.
3. Ask the buyer to select all files in the cloned folder and delete them, then open their Alfred project folder and copy everything into the cloned folder. Let you know when done.
4. Return to GitHub Desktop. Confirm the changed files are listed. Type `Deploy Alfred v2` in the summary box, click **Commit to main**, then click **Push origin**.
5. Confirm to the buyer: "Alfred's code is now on GitHub."

> Note: File copying between folders requires the buyer's hands — you can guide them through it precisely but the drag-and-drop itself is theirs to do.

---

### PART 2 — Configure Railway

**STANDARD MODE:**

**Step 5 — Add your variables**
1. Go to **railway.app** → click your project → click the **worker** service
2. Click the **Variables** tab
3. Click **Raw Editor** (top right of the variables panel)
4. Paste the complete block from above into the editor
5. Click **Update Variables**

**Step 6 — Verify the volume mount**
1. Close the Settings panel and return to the main project view
2. In the service card for **worker**, you will see `worker-volume` listed at the bottom of the card
3. Click directly on **worker-volume** — this opens its configuration
4. Confirm the Mount Path says `/data`
5. If it says anything other than `/data`, edit it and save

**Step 7 — Deploy**
1. Click the **Deployments** tab
2. You'll see an **"Apply X changes"** button or a **Deploy** button at the top — click it
3. A new deployment will appear with a spinning indicator — click it to watch the build log
4. Wait for the line that says Alfred is running (takes 2–3 minutes)
5. If you see any red error lines, copy them and paste them back here — most first-deploy errors are a one-line fix

---

**EXPRESS MODE — Railway configuration:**

> Tell the buyer: "I'll handle Railway from here. I just need you to confirm each step as I go."

1. Navigate to `railway.app` → click the project → click the **worker** service.
2. Click the **Variables** tab → click **Raw Editor**.
3. Click inside the editor, select all existing text, and replace it with the complete KEY=VALUE block assembled during the wizard. Ask the buyer: "Can you confirm the variables look correct on screen?" Wait for confirmation, then click **Update Variables**.
4. Return to the main project view. Click directly on **worker-volume** in the service card. Read the Mount Path shown. If it says `/data`, confirm to the buyer and move on. If it says anything else, click Edit, change it to `/data`, and save.
5. Click the **Deployments** tab. Click the **Deploy** or **Apply X changes** button.
6. Watch the build log in real time. Report progress to the buyer. When `Application started` appears, say: "Alfred is live — let's test it." If any red error lines appear, read them and diagnose immediately.

---

### PART 3 — First run in Telegram

Once the Deployments tab shows **"Deployment successful"**:

1. Open Telegram and find your bot
2. Send `/start` — Alfred should greet you
3. Then run these in order:
```
/setup      → walk through 25 preference steps to personalize Alfred
/auth       → connect Google (Calendar, Tasks, Sheets, Drive, Gmail)
/checkauth  → verify all Google connections show green
/briefing   → test your first morning briefing
/mood       → log your first mood rating
/workout    → set up your workout program
/meals      → set up your first meal plan
/journal    → start your first journal entry
```

If you set up Discord in Step 14, open your Discord server and send `!help` — Alfred should respond with the same command list.

> **Sports Pack buyers:** After deploying, add `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET` to your Railway variables. See the Sports Pack README for setup instructions.

If Alfred doesn't respond to `/start`, go back to Railway → Deployments and check the build log for errors.

---

## APPENDIX — All Commands Reference

### Core
```
/start              — introduction and command list
/help               — all available commands
/setup              — preferences + memory wizard (25 settings)
/checkauth          — verify Google connection
/auth               — (re)connect Google account
/briefing           — trigger morning briefing on demand
/export             — download all your data as Excel
/clear              — wipe conversation and ask thread history
```

### Memory
```
/memory                          — view all stored facts
/memory [category]               — view one category
/memory add [category] [fact]    — add a fact directly
/memory remove [category] [#]    — remove by number
/setup memory                    — re-run the memory wizard
```

### Shopping
```
/shopping                        — view all lists
add [item] to my grocery list    — add to a specific list
[send a receipt photo]           — auto-remove purchased items from lists
```

### Todos & Reminders
```
/todo                            — view active todos
add todo: [task]                 — add a task
remind me to [x] on [date/time] — set a reminder
```

### Calendar
```
/calendar                        — view upcoming events
/today                           — today's events only
/week                            — this week's events
/weekend                         — weekend events
/restofday                       — rest of today's schedule
add [event] on [date]            — create an event
what's on my calendar this week  — natural language query
```

### Notes
```
/notes                           — view all notes
add note: [text]                 — create a note
edit note [#]: [new text]        — replace note content
append to note [#]: [text]       — add to existing note
```

### Habits
```
/habits                          — view habits and streaks
logged [habit name]              — mark a habit done today
show my habit patterns           — smart analysis
```

### Meals
```
/meals                           — view this week's plan
add recipe: [description]        — generate a new recipe
import recipe from [url]         — import from a website
show nutrition for today         — macro breakdown
plan meals for next week         — generate 7-day plan
```

### Workout
```
/workout                         — view program + recent sessions
log [workout description]        — log a session (text or voice)
show my PRs                      — personal records
build me a new workout program   — regenerate from settings
export my workout log            — download Excel log
```

### Journal
```
/journal                         — start tonight's session
/journal view                    — recent entries
/journal search [term]           — search by keyword or date
/journal month                   — this month's GPT reflection
/journal wins                    — wins and highlights this week
```

### Mood
```
/mood                            — tap a 1–10 rating button
mood [number]                    — natural language log
show my mood this week           — recent trend
```

### Sleep
```
/sleep                           — view 7-day sleep history
/sleep [hours]                   — log hours slept (e.g. /sleep 7.5)
/sleep [hours] [quality 1-5]     — log hours + quality rating
slept 7 hours                    — natural language log
```

### Expenses
```
/expenses                        — view this month's spending by category
/expenses today                  — today's spending
/expenses week                   — this week's spending
$45 groceries                    — natural language add (dollar sign triggers it)
spent $12 on coffee              — alternate natural language form
delete expense [category]        — remove most recent expense in a category
```

### Brain Dump
```
/braindump [text]                — dump anything — Alfred sorts it into todos, reminders, notes, shopping
brain dump: [text]               — alternate trigger phrase
```

### Undo
```
undo                             — restore the last thing you deleted (todos, notes, shopping, expenses)
undo that                        — same as above
```

### Links
```
/readlater                       — view unread saves
save this link: [url]            — save with AI summary and tags
find my articles about [topic]   — search saved links
```

### Contacts & Gifts
```
/contacts                        — view all contacts
/contacts [name]                 — view one contact
add contact note for [name]: [fact]
/gifts                           — view all gift ideas
add gift for [name]: [idea]
```

### Email (Gmail)
```
how many unread emails?                    — inbox count (+ VIP highlights if configured)
check my inbox                             — same as above
email [address] that [message]             — send an email with preview + confirmation
email [name] that [message]                — send to a contact (name resolved from contacts)
send an email to [x] saying [message]      — alternate send phrasing
draft an email to [x] about [topic]        — save to Gmail Drafts (no confirmation needed)
save a draft to [x] about [topic]          — alternate draft phrasing
```

> **Note:** Gmail requires running `/auth` after deployment to grant Gmail access. Alfred will walk you through it. VIP senders and email signature are set via `GMAIL_VIP_SENDERS` and `GMAIL_DEFAULT_SIGNATURE` environment variables.

### Ask
```
/ask [question]                  — research with optional web search
```

---

## APPENDIX — Feature Quick Reference

**Voice:** Every feature works by voice. Send any Telegram voice note and Alfred transcribes it and routes it normally.

**Receipt scanning:** Photograph any store receipt and send it — Alfred reads the items and removes them from your shopping lists.

**Reply assist:** Screenshot any text conversation or email and send it — Alfred drafts 3 reply options using GPT-4o vision.

**Smart suggestions:** Alfred analyzes patterns in your habits, workouts, meals, mood, and shopping over time and surfaces observations in your weekly summary. Configure which areas in `/setup` → Configure preferences.

**Morning briefing sections** (toggle any on/off in `/setup`):
`weather` `calendar` `todos` `habits` `quote` `word_of_day` `meals` `journal_highlight` `workout_stats` `expenses` `gmail`

---

### Proactive Alerts

Alfred proactively notices things without being asked — 25 different checks across four categories.

**Commands:**
```
/proactive                        — view all toggle settings
/travel                           — show upcoming detected trips
/vacation                         — show vacation mode status
/vacation on until [date]         — activate vacation mode
/vacation off                     — deactivate (or say "I'm back")
/tomorrowprep                     — manually trigger night-before briefing
```

**Natural language:**
```
"turn off habit streak alerts"         — disable a specific check
"enable expense spike alerts"          — re-enable
"vacation on until June 20"            — activate vacation mode
"I'm back"                             — deactivate vacation mode
"pause running on vacation"            — snooze a habit during vacation
"keep tracking water on vacation"      — keep a habit active during vacation
"add sunscreen to beach packing list"  — customize trip packing lists
```

**Night-before briefing** fires automatically at 9pm (configurable) on nights before busy days (≥3 events or a priority to-do due). Blends: tomorrow's schedule, priority tasks, weather, bedtime suggestion, meeting-prep notes, travel alerts.

**Smart travel system** detects upcoming trips in your calendar and fires packing reminders at 7, 3, 2, and 1 day(s) out. Trip types detected: business, beach, ski, camping, international, weekend. Destination weather included.

**Vacation mode** pauses most proactive alerts. Habits can be individually kept or paused. Auto-resume on a set return date with a welcome-back recovery nudge.

All 25 checks can be toggled individually — say `"turn off [check name]"` or use `/proactive`.

---

### Sleep & Schedule

Configure your personal sleep preferences during `/setup` → Sleep & Schedule.

**What Alfred stores:**
- Weekday bed time / wake time (default: 11pm / 7am)
- Weekend bed time / wake time (default: midnight / 9am)
- Sleep goal in hours (default: 7.5)
- Chronotype: `early` (up before 6am) | `normal` (7am) | `night_owl` (9am+)
- Quiet hours: no proactive nudges during this window (default: 10pm – 7am)

**What these settings control:**
- Night-before briefing bedtime suggestion — uses your actual sleep goal and target wake time, not a generic calculation. Only fires if going to bed later than your target is meaningful.
- Proactive job DND gate — all 25 checks + tomorrow prep are silenced during quiet hours
- Chronotype-aware job scheduling — night owls get proactive checks at 9:30am, early birds at 7am, normal at 8:30am

**Setup format:**
```
Step: Sleep & Schedule
→ 11pm, 7am, midnight, 9am, 7.5
  (weekday bed, weekday wake, weekend bed, weekend wake, sleep goal)

Step: Quiet Hours
→ 10pm – 7am, night_owl
  (DND window, optional chronotype)
```

---

*Alfred Setup Companion v3.5 — Gmail step added (Step 15), GMAIL_VIP_SENDERS + GMAIL_DEFAULT_SIGNATURE in env block, Gmail commands in appendix, gmail added to briefing sections, /auth added to first-run sequence*

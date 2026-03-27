"""
alfred/core/config.py
=====================
All environment variables, constants, and file paths for Alfred.

BUYER CUSTOMIZATION:
  Values marked # <-- CUSTOMIZE are set during setup via the Setup Companion.
  The Setup Companion will walk you through each one — do not edit anything
  else unless instructed.

  Quick reference of what you will configure:
    - TIMEZONE             Your local timezone
    - WEATHER_LAT/LON      Your home city coordinates
    - HOME_CITY            Your home city name (for travel weather detection)
    - HOME_CITY_KEYWORDS   Words in your city/region that identify "home"
    - BOT_NAME             What you want your assistant to be called
    - HABITS / HABIT_LABELS / HABIT_KEYWORDS   Your personal habits to track
    - SHOPPING_LISTS / SHOPPING_KEYWORDS       Your shopping lists + auto-rules
    - QUOTE_TYPE           What kind of daily quote you want (stoic, bible, etc.)
    - BRIEFING_HOUR        What time your morning briefing fires
"""

import os


# ---------------------------------------------------------------------------
# ENVIRONMENT VARIABLES
# Set these in Railway → Variables. Never hardcode secrets here.
# ---------------------------------------------------------------------------

# Telegram bot token from BotFather
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]

# Your Telegram user ID — the bot ONLY responds to this ID
ALLOWED_USER_ID = int(os.environ["ALLOWED_USER_ID"])

# Google OAuth credentials JSON (paste the entire contents of credentials.json)
GOOGLE_CREDENTIALS = os.environ["GOOGLE_CREDENTIALS"]

# OpenAI API key
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

# Serper.dev API key for live web search in /ask
# If not set, /ask falls back to GPT knowledge only
SERPER_API_KEY = os.environ.get("SERPER_API_KEY", "")


# ---------------------------------------------------------------------------
# PERSISTENT STORAGE
# Railway provides a /data volume that survives redeploys.
# ---------------------------------------------------------------------------

PERSIST_DIR = "/data" if os.path.isdir("/data") else "/tmp"

DATA_FILE        = os.path.join(PERSIST_DIR, "userdata.json")
TOKEN_FILE       = os.path.join(PERSIST_DIR, "google_token.json")
AUTH_STATE_FILE  = os.path.join(PERSIST_DIR, "auth_state.json")
LOG_FILE         = os.path.join(PERSIST_DIR, "audit.log")
CONTACTS_FILE    = os.path.join(PERSIST_DIR, "contacts.json")
CONVO_FILE       = os.path.join(PERSIST_DIR, "conversation.json")
MEMORY_FILE      = os.path.join(PERSIST_DIR, "alfred_memory.json")
ASK_HISTORY_FILE  = os.path.join(PERSIST_DIR, "ask_history.json")
JOURNAL_FILE      = os.path.join(PERSIST_DIR, "journal.json")
WORKOUT_FILE      = os.path.join(PERSIST_DIR, "workout_program.json")
STYLE_LIB_FILE    = os.path.join(PERSIST_DIR, "style_library.json")
MEALS_XLSX        = os.path.join(PERSIST_DIR, "meals.xlsx")
WORKOUT_XLSX      = os.path.join(PERSIST_DIR, "workout_log.xlsx")
LINKS_FILE        = os.path.join(PERSIST_DIR, "links.json")
MOOD_LOG_FILE     = os.path.join(PERSIST_DIR, "mood_log.json")
EXPORT_DIR        = "/tmp"


# ---------------------------------------------------------------------------
# GOOGLE API SCOPES
# Calendar + Tasks. Do not change unless you are adding a new Google service.
# ---------------------------------------------------------------------------

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/tasks",
]


# ---------------------------------------------------------------------------
# GOOGLE TASKS LIST NAMES
# Alfred stores todos, notes, shopping, and gifts in Google Tasks.
# These are the exact list names Alfred will create or find in your account.
# The Setup Companion confirms these during setup.
# ---------------------------------------------------------------------------

GTASKS_TODOS_LIST     = "Alfred Todos"
GTASKS_NOTES_LIST     = "Alfred Notes"
GTASKS_SHOPPING_LISTS = {            # internal_key -> Google Tasks list name
    "grocery":   "Shopping: Grocery",
    "household": "Shopping: Household",
    "baby":      "Shopping: Baby",
    "wishlist":  "Shopping: Wishlist",
}
GTASKS_GIFTS_LIST     = "Alfred Gifts"


# ---------------------------------------------------------------------------
# BOT NAME                                                    # <-- CUSTOMIZE
# What you want your assistant called. Set during setup.
# Example: "Alfred", "Aria", "Max", "J.A.R.V.I.S."
# ---------------------------------------------------------------------------

BOT_NAME = os.environ.get("BOT_NAME", "Alfred")


# ---------------------------------------------------------------------------
# TIMEZONE                                                    # <-- CUSTOMIZE
# Your local timezone. Full list:
# https://en.wikipedia.org/wiki/List_of_tz_database_time_zones
# ---------------------------------------------------------------------------

TIMEZONE = os.environ.get("TIMEZONE", "America/New_York")


# ---------------------------------------------------------------------------
# WEATHER LOCATION                                           # <-- CUSTOMIZE
# Your home city latitude and longitude.
# Find yours at: https://www.latlong.net
# ---------------------------------------------------------------------------

WEATHER_LAT = float(os.environ.get("WEATHER_LAT", "40.7128"))   # default: NYC
WEATHER_LON = float(os.environ.get("WEATHER_LON", "-74.0060"))


# ---------------------------------------------------------------------------
# HOME CITY                                                  # <-- CUSTOMIZE
# Used for travel weather detection — Alfred checks if your calendar events
# are in a different city. Set to your home city name (lowercase).
# HOME_CITY_KEYWORDS: words that identify you're still "home" in an event.
# ---------------------------------------------------------------------------

HOME_CITY          = os.environ.get("HOME_CITY", "new york")   # <-- CUSTOMIZE
HOME_CITY_KEYWORDS = [                                          # <-- CUSTOMIZE
    "new york", "nyc", "brooklyn", "queens", "manhattan",
]


# ---------------------------------------------------------------------------
# HABIT TRACKER                                              # <-- CUSTOMIZE
# Define the habits you want to track. Alfred will generate keyword
# suggestions for each habit during setup, and you can confirm or edit them.
#
# HABITS:        ordered list of habit IDs (internal keys, no spaces)
# HABIT_LABELS:  what Alfred displays for each habit
# HABIT_KEYWORDS: phrases that auto-log that habit when spoken/typed
#
# NOTE: These are populated during setup. The defaults below are examples.
# ---------------------------------------------------------------------------

HABITS = [
    "workout",
    "water",
    "meditation",
    "sleep",
    "reading",
]

HABIT_LABELS = {
    "workout":   "Daily workout",
    "water":     "Water intake",
    "meditation": "Meditation",
    "sleep":     "Sleep",
    "reading":   "Reading",
}

HABIT_KEYWORDS = {
    "workout":   ["worked out", "hit the gym", "exercise done", "workout done",
                  "finished my workout", "gym done", "exercised"],
    "water":     ["drank water", "water done", "finished my water", "hydrated",
                  "water intake done"],
    "meditation": ["meditated", "meditation done", "mindfulness done",
                   "did my meditation", "sat today"],
    "sleep":     ["slept", "went to sleep", "sleep logged", "sleep done",
                  "tracked sleep"],
    "reading":   ["read today", "reading done", "finished reading",
                  "read my pages"],
}


# ---------------------------------------------------------------------------
# SHOPPING LISTS                                             # <-- CUSTOMIZE
# Define which shopping lists you want. Keys are internal IDs (no spaces).
# Labels are what Alfred displays.
#
# SHOPPING_KEYWORDS: if Alfred detects one of these words in an item,
# it auto-assigns it to that list. Populated/refined during setup.
# ---------------------------------------------------------------------------

SHOPPING_LISTS = {
    "grocery":   "Grocery",
    "household": "Household",
    "wishlist":  "Wishlist",
}

SHOPPING_KEYWORDS = {
    "household": [
        "toilet paper", "paper towels", "laundry", "detergent", "dish soap",
        "trash bags", "cleaning", "sponge", "batteries", "light bulb",
        "hand soap", "fabric softener",
    ],
    "wishlist": [
        "want", "wish", "someday", "eventually", "would love",
    ],
}


# ---------------------------------------------------------------------------
# DAILY QUOTE                                                # <-- CUSTOMIZE
# QUOTE_TYPE: what style of quote is sent in the morning briefing.
# Options: "stoic", "bible", "motivational", "philosophical", "random"
# If QUOTE_TYPE is "bible" or "motivational", Alfred uses the ZenQuotes API
# with GPT fallback. "stoic" uses the dedicated Stoic Quotes API.
# ---------------------------------------------------------------------------

QUOTE_TYPE = os.environ.get("QUOTE_TYPE", "stoic")   # <-- CUSTOMIZE

# Quote API endpoints (primary sources — GPT is the fallback for all)
STOIC_QUOTES_URL       = "https://stoic-quotes.azurewebsites.net/api/quote"
ZENQUOTES_URL          = "https://zenquotes.io/api/random"
BIBLE_VERSE_URL        = "https://bible-api.com/random"


# ---------------------------------------------------------------------------
# MORNING BRIEFING SCHEDULE                                 # <-- CUSTOMIZE
# All times are in your local TIMEZONE (set above).
# ---------------------------------------------------------------------------

BRIEFING_HOUR           = int(os.environ.get("BRIEFING_HOUR",   "7"))   # 7:00 AM
BRIEFING_MINUTE         = int(os.environ.get("BRIEFING_MINUTE", "0"))
HEALTH_CHECK_HOUR       = BRIEFING_HOUR
HEALTH_CHECK_MINUTE     = max(0, BRIEFING_MINUTE - 10)  # 10 min before briefing
TASKS_SYNC_HOUR         = BRIEFING_HOUR
TASKS_SYNC_MINUTE       = BRIEFING_MINUTE + 5           # 5 min after briefing
HABIT_NUDGE_HOUR        = int(os.environ.get("HABIT_NUDGE_HOUR",     "15"))  # <-- CUSTOMIZE
HABIT_NUDGE_MINUTE      = int(os.environ.get("HABIT_NUDGE_MINUTE",   "0"))
TRAVEL_WEATHER_HOUR     = int(os.environ.get("TRAVEL_WEATHER_HOUR",  "19"))  # <-- CUSTOMIZE
TRAVEL_WEATHER_MINUTE   = int(os.environ.get("TRAVEL_WEATHER_MINUTE","0"))
WEEKLY_SUMMARY_HOUR     = int(os.environ.get("WEEKLY_SUMMARY_HOUR",  "19"))  # <-- CUSTOMIZE
WEEKLY_SUMMARY_MINUTE   = int(os.environ.get("WEEKLY_SUMMARY_MINUTE","0"))
WEEKLY_SUMMARY_WEEKDAY  = int(os.environ.get("WEEKLY_SUMMARY_WEEKDAY","6"))  # <-- CUSTOMIZE (0=Mon, 6=Sun)
REMINDER_CHECK_INTERVAL = 60    # seconds between reminder checks
NOTE_AGING_DAYS         = 30    # days before a note is resurfaced


# ---------------------------------------------------------------------------
# GOOGLE CALENDAR SETTINGS                                   # <-- CUSTOMIZE
#
# CALENDAR_IDS: which calendars Alfred reads.
#   "primary" = your main Google Calendar (almost always correct).
#   To add others, find the calendar ID in Google Calendar settings →
#   (gear icon) → Settings → [click a calendar] → scroll to
#   "Integrate calendar" → copy the Calendar ID.
#   Example: ["primary", "family@group.calendar.google.com"]
#
# MAX_EVENTS_PER_FETCH: hard cap on events returned per calendar fetch.
# ---------------------------------------------------------------------------

CALENDAR_IDS        = ["primary"]   # <-- CUSTOMIZE (add more if needed)
MAX_EVENTS_PER_FETCH = 20


# ---------------------------------------------------------------------------
# EVENT PREP BRIEFING                                        # <-- CUSTOMIZE
# Alfred sends a prep briefing the evening before significant events.
#
# EVENT_PREP_HOUR/MINUTE: when the nightly check fires (default 8:00 PM).
# EVENT_PREP_HOURS_LOOKAHEAD: how far ahead to look for events (default 18h,
#   meaning events from now until 18 hours from now get a prep briefing).
# EVENT_PREP_MIN_DURATION_MINUTES: skip events shorter than this (default 30).
#   Prevents Alfred from prepping you for a 5-minute calendar block.
#
# EVENT_PREP_KEYWORDS: if ANY of these words appear in an event title,
#   it is treated as significant regardless of duration or guest count.
#   Add or remove words to match your life.               # <-- CUSTOMIZE
#
# EVENT_PREP_SKIP_KEYWORDS: events whose title contains these words are
#   never prepped (e.g. recurring blocks you don't need a briefing for).
# ---------------------------------------------------------------------------

EVENT_PREP_HOUR             = 20    # 8:00 PM
EVENT_PREP_MINUTE           = 0
EVENT_PREP_HOURS_LOOKAHEAD  = 18    # prep events happening within next 18h
EVENT_PREP_MIN_DURATION_MINUTES = 30

EVENT_PREP_KEYWORDS = [             # <-- CUSTOMIZE
    "interview", "presentation", "pitch", "demo", "review",
    "conference", "wedding", "dinner", "party", "surgery",
    "flight", "travel", "trip", "meeting", "date",
]

EVENT_PREP_SKIP_KEYWORDS = [        # <-- CUSTOMIZE
    "lunch", "break", "focus time", "blocked", "busy",
    "commute", "gym",
]


# ---------------------------------------------------------------------------
# TRAVEL WEATHER DETECTION                                   # <-- CUSTOMIZE
# Alfred scans upcoming calendar events at 7:00 PM daily and sends a
# weather alert for any event that appears to be in a different city.
#
# TRAVEL_DETECT_DAYS_AHEAD: how many days forward to scan (default 3).
# ---------------------------------------------------------------------------

TRAVEL_DETECT_DAYS_AHEAD = 3


# ---------------------------------------------------------------------------
# ALFRED MEMORY
# Long-term facts Alfred remembers about you.
#
# MEMORY_CATEGORIES: the default categories. The live category list is stored
#   in alfred_memory.json (so custom categories survive redeployment).
#   Buyers configure their categories during /setup in Telegram.
#
# MEMORY_ALWAYS_INJECT: categories injected into *every* GPT call regardless
#   of message content. Keep this small — these cost tokens on every message.
#
# MEMORY_CATEGORY_KEYWORDS: used for relevant-category injection.
#   When a user message contains any of these words, that category is added
#   to the context. Me + Preferences are always included; the rest are
#   keyword-matched. No extra GPT call needed — pure string matching.
#
# MEMORY_MAX_FACTS_PER_CATEGORY: hard cap per category (50 default).
#   At 20 tokens/fact average, 50 facts ≈ 1,000 tokens per category.
#   Relevant-category filtering means only 2–4 categories inject at once.
#
# MEMORY_SETUP_QUESTIONS: guided questions Alfred asks per category
#   during the /setup memory wizard in Telegram.
# ---------------------------------------------------------------------------

MEMORY_CATEGORIES = [
    "Me", "Family", "Work", "Preferences", "Ongoing",
    "Health", "Finance", "Goals", "Social", "Travel",
]

MEMORY_ALWAYS_INJECT = ["Me", "Preferences"]  # always included in GPT context

MEMORY_CATEGORY_KEYWORDS = {
    "Family":     ["family", "mom", "dad", "mother", "father", "parent", "sibling",
                   "brother", "sister", "child", "kid", "son", "daughter", "spouse",
                   "husband", "wife", "partner", "grandma", "grandpa", "grandmother",
                   "grandfather", "aunt", "uncle", "cousin", "nephew", "niece"],
    "Work":       ["work", "job", "career", "office", "meeting", "project", "boss",
                   "manager", "colleague", "coworker", "client", "deadline", "salary",
                   "promotion", "presentation", "email", "hire", "fired", "startup",
                   "company", "team", "employee"],
    "Ongoing":    ["currently", "right now", "these days", "this week", "still",
                   "tracking", "working on", "in progress", "active", "ongoing",
                   "trying to", "been doing", "lately"],
    "Health":     ["health", "doctor", "medical", "sick", "illness", "disease",
                   "medication", "medicine", "allergy", "allergic", "diet", "exercise",
                   "fitness", "symptom", "pain", "injury", "hospital", "therapy",
                   "therapist", "prescription", "mental health", "anxiety", "sleep",
                   "weight", "calories", "nutrition", "vitamin", "condition", "chronic"],
    "Finance":    ["money", "budget", "spend", "spending", "cost", "price", "afford",
                   "salary", "income", "invest", "investment", "savings", "save",
                   "debt", "loan", "credit", "financial", "pay", "bill", "subscription",
                   "expense", "purchase", "bank", "account", "stock", "crypto",
                   "mortgage", "rent", "insurance"],
    "Goals":      ["goal", "target", "want to", "trying to", "planning to", "plan to",
                   "aim", "objective", "achieve", "accomplish", "resolution", "ambition",
                   "dream", "aspire", "working toward", "hope to", "intend to",
                   "milestone", "vision", "focus"],
    "Social":     ["friend", "friends", "social", "party", "event", "hangout",
                   "meet up", "meetup", "invite", "relationship", "dating", "date",
                   "birthday", "anniversary", "gathering", "dinner with", "lunch with",
                   "coffee with", "drinks with"],
    "Travel":     ["travel", "trip", "flight", "hotel", "vacation", "holiday", "visit",
                   "airport", "passport", "abroad", "destination", "booking", "itinerary",
                   "cruise", "road trip", "layover", "check-in", "checkout", "airline",
                   "miles", "points", "airbnb"],
}

MEMORY_MAX_FACTS_PER_CATEGORY = 50

# Guided questions Alfred asks per category during /setup memory
MEMORY_SETUP_QUESTIONS = {
    "Me": [
        "What's your name, and where do you live?",
        "How old are you? (optional — skip if you prefer)",
        "How would you describe your communication style — casual, direct, formal?",
        "Anything else about yourself you'd like me to always keep in mind?",
    ],
    "Family": [
        "Tell me about your immediate family — spouse or partner, kids, parents?",
        "Any important names, ages, or birthdays I should know?",
        "Anyone else close to you I should know about?",
    ],
    "Work": [
        "Where do you work, and what's your role?",
        "Any current key projects or priorities I should know about?",
        "Any important colleagues or clients I might need context on?",
    ],
    "Health": [
        "Any health conditions, injuries, or chronic issues I should know about?",
        "Any allergies or dietary restrictions?",
        "Any medications, supplements, or health goals I should keep in mind?",
    ],
    "Finance": [
        "Any financial goals you're working toward right now?",
        "Any budget constraints I should keep in mind when making suggestions?",
        "Any subscriptions or recurring expenses worth tracking?",
    ],
    "Goals": [
        "What are your biggest goals right now — personal or professional?",
        "Any long-term aspirations or things you're actively working toward?",
    ],
    "Social": [
        "Any close friends or their context I should keep in mind?",
        "Any regular social commitments (weekly dinners, game nights, etc.)?",
    ],
    "Travel": [
        "Any upcoming trips I should know about?",
        "Any travel preferences — preferred airlines, hotel chains, seat type?",
        "Any frequent flyer programs or travel memberships?",
    ],
    "Preferences": [
        "How do you like me to respond — brief and direct, or more conversational?",
        "Any strong likes or dislikes I should know? (food, activities, topics)",
        "Anything about how you want me to behave that I should always remember?",
    ],
    "Ongoing": [
        "What are you actively tracking or working on right now?",
        "Any habits, projects, or goals in progress I should keep in mind?",
    ],
}

# System message prefix injected with memory context into every /ask call
MEMORY_SYSTEM_PREFIX = (
    "You are {bot_name}, a personal assistant. You know the following facts "
    "about the user:\n\n{memory_block}\n\nUse this context when it is "
    "relevant, but do not repeat facts back unless asked."
)

# Setup wizard state file
SETUP_STATE_FILE = os.path.join(PERSIST_DIR, "setup_state.json")


# ---------------------------------------------------------------------------
# /ASK CONTEXT SETTINGS
# Alfred maintains an 8-hour conversation thread for follow-up questions.
# If the topic shifts significantly, the thread auto-resets.
# ---------------------------------------------------------------------------

ASK_CONTEXT_HOURS   = 8    # hours before /ask thread expires
ASK_MAX_HISTORY     = 100  # max messages to keep in active ask thread (8h thread needs room)


# ---------------------------------------------------------------------------
# RECURRING TODOS & REMINDERS
# Options for how often something can recur.
# ---------------------------------------------------------------------------

RECUR_OPTIONS = ["daily", "weekdays", "weekly", "monthly", "none"]

RECUR_LABELS = {
    "daily":    "Every day",
    "weekdays": "Weekdays (Mon–Fri)",
    "weekly":   "Every week",
    "monthly":  "Every month",
    "none":     "One-time only",
}


# ---------------------------------------------------------------------------
# TELEGRAM DEEP LINK (Quick Capture)
# Used to generate the home screen bookmark for instant capture.
# Replace BOT_USERNAME with your bot's @username during setup.
# ---------------------------------------------------------------------------

BOT_USERNAME          = os.environ.get("BOT_USERNAME", "")
QUICK_CAPTURE_DEEPLINK = f"https://t.me/{BOT_USERNAME}?start=capture"


# ---------------------------------------------------------------------------
# CONTACT SYSTEM PROMPT ADD-ON
# Injected into GPT when the user asks about or references a contact.
# ---------------------------------------------------------------------------

CONTACT_SYSTEM_ADDON = (
    "\n\nCONTACT CONTEXT:\n"
    "The user has a personal contacts file with notes about people they know. "
    "When they mention a name, check if context is provided and use it to "
    "personalize your response (e.g., remembering birthdays, preferences, "
    "or relationship details). Never reveal raw contact data unless asked."
)


# ---------------------------------------------------------------------------
# CONVERSATION MEMORY
# How many messages Alfred remembers per conversation session.
# ---------------------------------------------------------------------------

MAX_HISTORY = 20


# ---------------------------------------------------------------------------
# RATE LIMITING
# Max messages per minute before Alfred asks the user to slow down.
# ---------------------------------------------------------------------------

RATE_LIMIT_COUNT  = 30
RATE_LIMIT_WINDOW = 60  # seconds


# ---------------------------------------------------------------------------
# GPT MODELS
# Different models for different tasks to balance cost and quality.
# ---------------------------------------------------------------------------

GPT_CHAT_MODEL   = "gpt-4o-mini"   # Main conversation, intent classification
GPT_VISION_MODEL = "gpt-4o"         # Photo analysis
GPT_VOICE_MODEL  = "whisper-1"      # Voice transcription


# ---------------------------------------------------------------------------
# WORD OF THE DAY
# 248-word list, one word per day (cycling by day-of-year).
# No GPT randomness — deterministic, no repeats until the full year cycles.
# Add or remove words freely; Alfred wraps around if < 365 words.
# ---------------------------------------------------------------------------

WORD_OF_DAY_LIST = [
    # (word, part_of_speech, definition, example_sentence)
    ("Sanguine",        "adjective", "Optimistic, especially in a difficult situation.",
     "She remained sanguine about the project despite the setbacks."),
    ("Ephemeral",       "adjective", "Lasting for a very short time.",
     "The ephemeral nature of social media trends makes planning difficult."),
    ("Laconic",         "adjective", "Using very few words; brief and concise.",
     "His laconic reply told me everything I needed to know."),
    ("Perspicacious",   "adjective", "Having a ready insight; shrewd.",
     "The perspicacious investor spotted the opportunity before others."),
    ("Equanimity",      "noun",      "Mental calmness under pressure.",
     "She accepted the news with remarkable equanimity."),
    ("Fastidious",      "adjective", "Very attentive to detail; hard to please.",
     "He was fastidious about keeping his workspace clean."),
    ("Magnanimous",     "adjective", "Generous and forgiving, especially toward a rival.",
     "The champion was magnanimous in victory."),
    ("Recalcitrant",    "adjective", "Having an uncooperative attitude toward authority.",
     "The recalcitrant employee refused to follow the new policy."),
    ("Tenacious",       "adjective", "Holding firm to a purpose; persistent.",
     "Her tenacious pursuit of the goal paid off in the end."),
    ("Pellucid",        "adjective", "Transparently clear; easy to understand.",
     "His pellucid explanation made the concept accessible to everyone."),
    ("Veracious",       "adjective", "Truthful; accurate.",
     "She was known as a veracious reporter who never embellished."),
    ("Circumspect",     "adjective", "Wary and unwilling to take risks.",
     "Be circumspect when signing contracts you have not fully read."),
    ("Indefatigable",   "adjective", "Persisting tirelessly.",
     "The indefatigable volunteer worked through the night."),
    ("Pernicious",      "adjective", "Having a harmful effect, especially subtly.",
     "The pernicious influence of misinformation spreads slowly."),
    ("Sagacious",       "adjective", "Having good judgment; wise.",
     "The sagacious mentor offered advice that proved prescient."),
    ("Taciturn",        "adjective", "Reserved or uncommunicative in speech.",
     "The taciturn mechanic said little but fixed everything perfectly."),
    ("Ebullient",       "adjective", "Cheerful and full of energy.",
     "Her ebullient personality lit up every room she entered."),
    ("Loquacious",      "adjective", "Tending to talk a great deal.",
     "The loquacious host filled every silence with a new anecdote."),
    ("Stoic",           "adjective", "Enduring pain without complaint or expression.",
     "He was stoic through the long recovery process."),
    ("Acumen",          "noun",      "The ability to make good judgments quickly.",
     "Her business acumen helped the startup survive its first year."),
    ("Candor",          "noun",      "The quality of being open and honest.",
     "I appreciated his candor even though the feedback was hard to hear."),
    ("Fortitude",       "noun",      "Courage in pain or adversity.",
     "It took real fortitude to keep going after the early failures."),
    ("Gravitas",        "noun",      "Dignity and seriousness of manner.",
     "The new CEO brought a quiet gravitas that reassured the board."),
    ("Impetus",         "noun",      "A force or energy that drives something forward.",
     "The funding provided the impetus needed to launch the product."),
    ("Alacrity",        "noun",      "Brisk and cheerful readiness.",
     "She accepted the challenge with alacrity."),
    ("Ameliorate",      "verb",      "To make something bad or unsatisfactory better.",
     "The new policy was designed to ameliorate working conditions."),
    ("Anodyne",         "adjective", "Not likely to cause offense; inoffensive.",
     "His anodyne comments added nothing to the debate."),
    ("Aplomb",          "noun",      "Self-confidence or assurance, especially in difficult situations.",
     "She handled the crisis with remarkable aplomb."),
    ("Arcane",          "adjective", "Understood by few; mysterious.",
     "The arcane rules of the old guild confused newcomers."),
    ("Assiduous",       "adjective", "Showing great care and perseverance.",
     "His assiduous research produced a thorough report."),
    ("Audacious",       "adjective", "Showing willingness to take surprisingly bold risks.",
     "It was an audacious plan, but it worked."),
    ("Auspicious",      "adjective", "Conducive to success; favorable.",
     "The sunny weather felt like an auspicious sign."),
    ("Banal",           "adjective", "So lacking in originality as to be obvious.",
     "The movie's dialogue was disappointingly banal."),
    ("Bellicose",       "adjective", "Demonstrating aggression; eager to fight.",
     "His bellicose tone only escalated the argument."),
    ("Benevolent",      "adjective", "Well meaning and kindly.",
     "The benevolent donor gave anonymously."),
    ("Blithe",          "adjective", "Showing a casual and cheerful indifference.",
     "She was blithe about the risks involved."),
    ("Bombastic",       "adjective", "High-sounding but with little meaning.",
     "His bombastic speech impressed no one."),
    ("Brazen",          "adjective", "Bold and without shame.",
     "It was a brazen lie, told without hesitation."),
    ("Brusque",         "adjective", "Abrupt or offhand in manner.",
     "His brusque reply left her feeling dismissed."),
    ("Bucolic",         "adjective", "Relating to the pleasant aspects of the countryside.",
     "The painting depicted a bucolic scene of rolling hills."),
    ("Cacophony",       "noun",      "A harsh, discordant mixture of sounds.",
     "The cacophony of car horns filled the city street."),
    ("Callous",         "adjective", "Showing or having an insensitive disregard for others.",
     "His callous dismissal of their concerns was shocking."),
    ("Capitulate",      "verb",      "Cease to resist; give in.",
     "After hours of negotiation, they finally capitulated."),
    ("Capricious",      "adjective", "Given to sudden and unaccountable changes of mood.",
     "The capricious weather ruined their outdoor plans."),
    ("Caustic",         "adjective", "Sarcastic in a scathing and bitter way.",
     "Her caustic wit intimidated new employees."),
    ("Celerity",        "noun",      "Swiftness of movement.",
     "She completed the task with surprising celerity."),
    ("Chicanery",       "noun",      "The use of trickery to achieve a goal.",
     "The investigation uncovered years of financial chicanery."),
    ("Cogent",          "adjective", "Clear, logical, and convincing.",
     "She made a cogent argument for the new policy."),
    ("Complacent",      "adjective", "Showing uncritical satisfaction with one's achievements.",
     "Success made them complacent about future risks."),
    ("Compunction",     "noun",      "A feeling of guilt that follows doing something wrong.",
     "He showed no compunction about cutting corners."),
    ("Convoluted",      "adjective", "Extremely complex and difficult to follow.",
     "The instructions were so convoluted nobody could follow them."),
    ("Copious",         "noun",      "Abundant in supply or quantity.",
     "She took copious notes during the lecture."),
    ("Culpable",        "adjective", "Deserving blame.",
     "He was found culpable for the accident."),
    ("Dauntless",       "adjective", "Showing fearlessness and determination.",
     "The dauntless explorer pressed on through the storm."),
    ("Debacle",         "noun",      "A sudden disastrous collapse or defeat.",
     "The product launch was a complete debacle."),
    ("Decorous",        "adjective", "In keeping with good taste and propriety.",
     "The ceremony was decorous and dignified."),
    ("Deferential",     "adjective", "Showing respect and high regard.",
     "He was deferential toward his mentors."),
    ("Deft",            "adjective", "Neatly skillful and quick.",
     "She made a deft move to avoid the awkward question."),
    ("Deleterious",     "adjective", "Causing harm or damage.",
     "Smoking has deleterious effects on health."),
    ("Demagogue",       "noun",      "A political leader who appeals to prejudice.",
     "The demagogue stirred fear rather than reason."),
    ("Didactic",        "adjective", "Intended to teach, particularly with moral instruction.",
     "The film was too didactic to be enjoyable."),
    ("Diffidence",      "noun",      "Modesty or shyness resulting from a lack of confidence.",
     "Her diffidence kept her from speaking up."),
    ("Dilettante",      "noun",      "A person with a superficial interest in an art or field.",
     "He was a dilettante who dabbled in many hobbies but mastered none."),
    ("Discerning",      "adjective", "Having or showing good judgment.",
     "A discerning reader catches what others miss."),
    ("Dissonance",      "noun",      "Lack of harmony; inconsistency.",
     "There was a dissonance between his words and actions."),
    ("Dogmatic",        "adjective", "Inclined to lay down principles as undeniably true.",
     "His dogmatic approach frustrated open-minded colleagues."),
    ("Draconian",       "adjective", "Excessively harsh and severe.",
     "Critics called the new regulations draconian."),
    ("Dubious",         "adjective", "Hesitating or doubting.",
     "She was dubious about his sudden change of heart."),
    ("Duplicitous",     "adjective", "Deceptive in speech or conduct.",
     "The duplicitous negotiator had been hiding his true agenda."),
    ("Ebullience",      "noun",      "The quality of being cheerful and full of energy.",
     "Her ebullience was infectious at every meeting."),
    ("Egregious",       "adjective", "Outstandingly bad; shocking.",
     "It was an egregious violation of trust."),
    ("Elusive",         "adjective", "Difficult to find, catch, or achieve.",
     "Success remained elusive despite years of effort."),
    ("Eminent",         "adjective", "Famous and respected within a particular sphere.",
     "An eminent scientist spoke at the conference."),
    ("Empirical",       "adjective", "Based on observation or experience rather than theory.",
     "The hypothesis required empirical evidence to be accepted."),
    ("Enervate",        "verb",      "To make someone feel drained of energy.",
     "The humid heat enervated the entire team."),
    ("Enigmatic",       "adjective", "Difficult to interpret; mysterious.",
     "She gave an enigmatic smile and said nothing."),
    ("Equivocate",      "verb",      "To use ambiguous language to conceal the truth.",
     "The politician equivocated when asked for a direct answer."),
    ("Erudite",         "adjective", "Having or showing great knowledge or learning.",
     "His erudite commentary impressed even the professors."),
    ("Esoteric",        "adjective", "Intended for a small group with specialized knowledge.",
     "The paper was too esoteric for general audiences."),
    ("Euphemism",       "noun",      "A mild word substituted for an offensive one.",
     "'Passed away' is a euphemism for died."),
    ("Evanescent",      "adjective", "Quickly fading from sight, memory, or existence.",
     "The evanescent mist disappeared by noon."),
    ("Exacerbate",      "verb",      "To make a problem, bad situation, or feeling worse.",
     "His comments only exacerbated the tension."),
    ("Exigent",         "adjective", "Pressing; requiring immediate action.",
     "The exigent circumstances demanded a quick decision."),
    ("Expedient",       "adjective", "Convenient and practical, though possibly improper.",
     "It was expedient to sign the deal, even with reservations."),
    ("Facetious",       "adjective", "Treating serious issues with inappropriate humor.",
     "His facetious remark was not appreciated."),
    ("Fallacious",      "adjective", "Based on a mistaken belief; logically unsound.",
     "The argument rested on a fallacious assumption."),
    ("Fatuous",         "adjective", "Foolish and self-pleased.",
     "His fatuous grin suggested he had missed the point entirely."),
    ("Feckless",        "adjective", "Lacking initiative or strength of character.",
     "The feckless manager avoided all difficult decisions."),
    ("Fervent",         "adjective", "Having or displaying a passionate intensity.",
     "She was a fervent supporter of the cause."),
    ("Fickle",          "adjective", "Changing frequently, especially loyalty or affection.",
     "Fame proved fickle; the star was forgotten within a year."),
    ("Flagrant",        "adjective", "Conspicuously or obviously offensive.",
     "It was a flagrant disregard for the rules."),
    ("Fledgling",       "adjective", "New and still developing.",
     "The fledgling startup showed enormous potential."),
    ("Foment",          "verb",      "To instigate or stir up trouble.",
     "The article was accused of fomenting unrest."),
    ("Forbearance",     "noun",      "Patient self-control; restraint.",
     "She showed great forbearance in the face of repeated insults."),
    ("Forthright",      "adjective", "Direct and outspoken.",
     "His forthright manner was refreshing in a world of corporate speak."),
    ("Fractious",       "adjective", "Easily irritated; difficult to control.",
     "The fractious toddler refused to sit still."),
    ("Furtive",         "adjective", "Attempting to avoid notice; secretive.",
     "He cast a furtive glance over his shoulder."),
    ("Garrulous",       "adjective", "Excessively talkative.",
     "The garrulous neighbor kept them on the porch for an hour."),
    ("Germane",         "adjective", "Relevant to the subject at hand.",
     "Her comment was germane and moved the discussion forward."),
    ("Gregarious",      "adjective", "Fond of company; sociable.",
     "He was gregarious and made friends everywhere he went."),
    ("Guileless",       "adjective", "Devoid of guile; innocent and without deception.",
     "Her guileless expression made her impossible to distrust."),
    ("Hackneyed",       "adjective", "Lacking originality; overused.",
     "The speech was full of hackneyed phrases."),
    ("Harangue",        "noun",      "A lengthy and aggressive speech.",
     "He launched into a harangue about corporate greed."),
    ("Hegemony",        "noun",      "Leadership or dominance, especially of one country.",
     "The nation sought to maintain its economic hegemony."),
    ("Hubris",          "noun",      "Excessive pride or self-confidence.",
     "His hubris led him to underestimate the competition."),
    ("Hypocritical",    "adjective", "Behaving in a way that contradicts stated beliefs.",
     "It was hypocritical to preach honesty while lying."),
    ("Idiosyncratic",   "adjective", "Peculiar to an individual; distinctive.",
     "Her idiosyncratic style set her writing apart."),
    ("Ignoble",         "adjective", "Not honorable in character or purpose.",
     "It was an ignoble end to a once-great career."),
    ("Impassive",       "adjective", "Not feeling or showing emotion.",
     "He remained impassive throughout the difficult testimony."),
    ("Imperious",       "adjective", "Assuming power without justification; arrogant.",
     "Her imperious tone alienated her entire team."),
    ("Implacable",      "adjective", "Unable to be appeased or placated.",
     "The implacable critic rejected every revision."),
    ("Impudent",        "adjective", "Not showing due respect; impertinent.",
     "The impudent student interrupted the professor mid-sentence."),
    ("Impugn",          "verb",      "To dispute the truth or honesty of something.",
     "He impugned the witness's credibility with new evidence."),
    ("Incisive",        "adjective", "Intelligently analytical and clear-thinking.",
     "Her incisive questions cut to the heart of the matter."),
    ("Incongruous",     "adjective", "Not in harmony; out of place.",
     "The modern building was incongruous in the historic district."),
    ("Indolent",        "adjective", "Wanting to avoid activity; lazy.",
     "The indolent student scraped by with minimal effort."),
    ("Ineffable",       "adjective", "Too great or extreme to be expressed in words.",
     "The view from the summit was ineffable."),
    ("Inexorable",      "adjective", "Impossible to stop or prevent.",
     "The inexorable march of time waits for no one."),
    ("Ingenuous",       "adjective", "Innocent and unsuspecting.",
     "His ingenuous trust in people sometimes left him vulnerable."),
    ("Inimical",        "adjective", "Tending to obstruct or harm.",
     "Such habits are inimical to long-term success."),
    ("Insidious",       "adjective", "Proceeding in a gradual, subtle way but with harmful effect.",
     "The insidious spread of misinformation was hard to counter."),
    ("Intransigent",    "adjective", "Refusing to change one's views; uncompromising.",
     "The intransigent negotiator blocked every compromise."),
    ("Intrepid",        "adjective", "Fearless; adventurous.",
     "The intrepid journalist traveled to the conflict zone alone."),
    ("Inveterate",      "adjective", "Having a habit too firmly established to change.",
     "He was an inveterate optimist no matter the circumstances."),
    ("Irascible",       "adjective", "Having or showing a tendency to be easily angered.",
     "The irascible coach yelled at the referees constantly."),
    ("Irresolute",      "adjective", "Showing or feeling hesitancy; uncertain.",
     "The irresolute leader delayed every decision."),
    ("Jejune",          "adjective", "Naive and simplistic; dull.",
     "The jejune analysis ignored the complexity of the problem."),
    ("Judicious",       "adjective", "Having, showing, or done with good judgment.",
     "A judicious use of resources kept the project on budget."),
    ("Juxtapose",       "verb",      "Place two things close together for contrasting effect.",
     "The exhibit juxtaposed old photographs with modern ones."),
    ("Lachrymose",      "adjective", "Tearful; prone to weeping.",
     "The lachrymose film left the whole audience in tears."),
    ("Languid",         "adjective", "Displaying a lack of energy or enthusiasm.",
     "He gave a languid wave and went back to his book."),
    ("Lassitude",       "noun",      "Physical or mental weariness; lack of energy.",
     "A midafternoon lassitude settled over the office."),
    ("Laudable",        "adjective", "Deserving praise and commendation.",
     "Her commitment to the community was laudable."),
    ("Levity",          "noun",      "The treatment of a serious matter with humor.",
     "He used levity to defuse the tension in the room."),
    ("Lithe",           "adjective", "Thin, supple, and graceful.",
     "The lithe gymnast moved effortlessly across the beam."),
    ("Lucid",           "adjective", "Clear and easy to understand.",
     "She gave a lucid account of what had happened."),
    ("Lugubrious",      "adjective", "Looking or sounding sad and dismal.",
     "He delivered the news in a lugubrious tone."),
    ("Malevolent",      "adjective", "Having or showing a wish to do evil.",
     "The villain's malevolent gaze swept the room."),
    ("Malleable",       "adjective", "Easily influenced; pliable.",
     "Young minds are more malleable than older ones."),
    ("Mendacious",      "adjective", "Not telling the truth; lying.",
     "His mendacious account fooled no one in the courtroom."),
    ("Mercurial",       "adjective", "Subject to sudden or unpredictable changes of mood.",
     "Her mercurial temperament made her exciting but exhausting."),
    ("Meticulous",      "adjective", "Showing great attention to detail.",
     "His meticulous records made the audit effortless."),
    ("Misanthrope",     "noun",      "A person who dislikes and avoids other people.",
     "The misanthrope preferred his books to any social gathering."),
    ("Mitigate",        "verb",      "Make less severe, serious, or painful.",
     "New safety measures were taken to mitigate risk."),
    ("Mollify",         "verb",      "Appease the anger or anxiety of someone.",
     "She tried to mollify the upset customer with an apology."),
    ("Morose",          "adjective", "Sullen and ill-tempered.",
     "He was morose for days after the loss."),
    ("Mundane",         "adjective", "Lacking interest or excitement; dull.",
     "Even the most mundane tasks require attention."),
    ("Nefarious",       "adjective", "Wicked or criminal.",
     "The scheme was nefarious from the start."),
    ("Neologism",       "noun",      "A newly coined word or expression.",
     "'Googling' is a neologism that entered everyday language."),
    ("Nihilism",        "noun",      "The rejection of all religious and moral principles.",
     "His nihilism made it hard to motivate him."),
    ("Nocturnal",       "adjective", "Active at night.",
     "The nocturnal owl hunts after dark."),
    ("Nonchalant",      "adjective", "Feeling or appearing casually calm.",
     "She was nonchalant about the award, as if she expected it."),
    ("Nuanced",         "adjective", "Characterized by subtle shades of meaning.",
     "A nuanced reading reveals the author's real intent."),
    ("Obdurate",        "adjective", "Stubbornly refusing to change one's opinion.",
     "Despite the evidence, he remained obdurate."),
    ("Obsequious",      "adjective", "Obedient or attentive to an excessive or servile degree.",
     "The obsequious assistant agreed with everything his boss said."),
    ("Obtuse",          "adjective", "Annoyingly insensitive or slow to understand.",
     "He was being deliberately obtuse to avoid the question."),
    ("Officious",       "adjective", "Asserting authority or interfering in an annoying way.",
     "The officious manager micromanaged every minor decision."),
    ("Ominous",         "adjective", "Giving the impression that something bad is imminent.",
     "Dark clouds gathered in an ominous way."),
    ("Opaque",          "adjective", "Not transparent; hard to understand.",
     "The contract's language was deliberately opaque."),
    ("Ostentatious",    "adjective", "Characterized by vulgar display of wealth.",
     "His ostentatious lifestyle raised eyebrows."),
    ("Ostracize",       "verb",      "Exclude from a society or group.",
     "She was ostracized for speaking out against the group."),
    ("Panacea",         "noun",      "A solution or remedy for all difficulties.",
     "Technology is not a panacea for social problems."),
    ("Parsimonious",    "adjective", "Very unwilling to spend money; extremely frugal.",
     "The parsimonious owner refused to replace the broken chairs."),
    ("Partisan",        "adjective", "Prejudiced in favor of a particular cause.",
     "The partisan coverage ignored opposing viewpoints."),
    ("Pathological",    "adjective", "Compulsive; habitual in an extreme way.",
     "He was a pathological liar even when the truth was harmless."),
    ("Pedantic",        "adjective", "Excessively concerned with minor detail.",
     "His pedantic corrections interrupted the flow of the meeting."),
    ("Pejorative",      "adjective", "Expressing contempt or disapproval.",
     "The term was used in a pejorative sense."),
    ("Penurious",       "adjective", "Extremely poor; unwilling to spend.",
     "The penurious landlord refused all repairs."),
    ("Perfidious",      "adjective", "Deceitful and untrustworthy.",
     "The perfidious ally switched sides without warning."),
    ("Perfunctory",     "adjective", "Carried out with minimal effort.",
     "His perfunctory apology satisfied no one."),
    ("Pervasive",       "adjective", "Spreading through every part of something.",
     "A pervasive sense of unease hung over the office."),
    ("Petulant",        "adjective", "Childishly sulky or bad-tempered.",
     "His petulant outburst embarrassed the entire team."),
    ("Philanthropic",   "adjective", "Seeking to promote the welfare of others.",
     "Their philanthropic work funded hundreds of scholarships."),
    ("Pious",           "adjective", "Devoutly religious; making a show of virtue.",
     "He was pious in public but less so in private."),
    ("Platitude",       "noun",      "A remark so overused it is meaningless.",
     "The speech was full of platitudes that said nothing."),
    ("Plausible",       "adjective", "Seeming reasonable or probable.",
     "She offered a plausible explanation for the delay."),
    ("Poignant",        "adjective", "Evoking a keen sense of sadness or regret.",
     "The reunion was a poignant reminder of lost time."),
    ("Polemic",         "noun",      "A strong verbal or written attack on something.",
     "The essay was a polemic against corporate greed."),
    ("Ponderous",       "adjective", "Slow and clumsy because of great weight.",
     "The ponderous speech lasted three hours."),
    ("Pragmatic",       "adjective", "Dealing with things sensibly and realistically.",
     "A pragmatic approach gets more done than idealism alone."),
    ("Precarious",      "adjective", "Not securely held; uncertain.",
     "The company's precarious finances worried investors."),
    ("Predilection",    "noun",      "A preference or special liking for something.",
     "She had a predilection for strong, black coffee."),
    ("Preemptive",      "adjective", "Serving to preempt or forestall.",
     "The preemptive strike prevented further escalation."),
    ("Pretentious",     "adjective", "Attempting to impress by affecting greater importance.",
     "The pretentious menu listed simple dishes in French."),
    ("Probity",         "noun",      "Strong moral principles; complete honesty.",
     "His probity made him the obvious choice for the role."),
    ("Prodigal",        "adjective", "Spending money or resources freely and recklessly.",
     "His prodigal spending wiped out the inheritance in a year."),
    ("Prodigious",      "adjective", "Remarkably or impressively great in extent.",
     "She had a prodigious appetite for reading."),
    ("Profligate",      "adjective", "Recklessly extravagant or wasteful.",
     "The profligate regime wasted billions on vanity projects."),
    ("Propitious",      "adjective", "Giving or indicating a good chance of success.",
     "The timing seemed propitious for launching the company."),
    ("Prosaic",         "adjective", "Commonplace; lacking poetic beauty.",
     "His prose was accurate but thoroughly prosaic."),
    ("Protracted",      "adjective", "Lasting for a long time; prolonged.",
     "The protracted negotiations exhausted both sides."),
    ("Providential",    "adjective", "Happening at a favorable time; lucky.",
     "His arrival was providential — the pipes burst minutes later."),
    ("Prudent",         "adjective", "Acting with care and thought for the future.",
     "A prudent investor diversifies across asset classes."),
    ("Pugnacious",      "adjective", "Eager or quick to argue or fight.",
     "His pugnacious style won arguments but lost allies."),
    ("Querulous",       "adjective", "Complaining in a petulant way.",
     "The querulous customer complained about everything."),
    ("Quixotic",        "adjective", "Exceedingly idealistic; impractical.",
     "His quixotic plan to save the company alone was doomed."),
    ("Recondite",       "adjective", "Not known by many; obscure.",
     "The professor's recondite knowledge impressed his students."),
    ("Redolent",        "adjective", "Strongly suggestive or reminiscent of something.",
     "The room was redolent of old books and cedar."),
    ("Refractory",      "adjective", "Stubborn or unmanageable.",
     "The refractory patient refused all treatment."),
    ("Remonstrate",     "verb",      "Make a forcefully reproachful protest.",
     "He remonstrated with the council about the new rule."),
    ("Repudiate",       "verb",      "Refuse to accept or be associated with.",
     "She repudiated the claims as completely false."),
    ("Resilient",       "adjective", "Able to withstand or recover quickly from difficulty.",
     "Resilient businesses adapt when circumstances change."),
    ("Reticent",        "adjective", "Not revealing one's thoughts or feelings readily.",
     "He was reticent about discussing his past."),
    ("Reverent",        "adjective", "Feeling or showing deep respect.",
     "The crowd fell into a reverent silence."),
    ("Rhetoric",        "noun",      "Language designed to have a persuasive effect.",
     "His rhetoric was impressive but his record was poor."),
    ("Rigorous",        "adjective", "Extremely thorough and careful.",
     "The study followed rigorous scientific protocols."),
    ("Ruminative",      "adjective", "Deep in thought; meditative.",
     "He spent a ruminative afternoon by the water."),
    ("Sanctimonious",   "adjective", "Making a show of being morally superior.",
     "Nobody liked his sanctimonious lectures."),
    ("Sardonic",        "adjective", "Grimly mocking or cynical.",
     "Her sardonic humor made colleagues nervous."),
    ("Scrupulous",      "adjective", "Diligent, thorough, and extremely attentive to details.",
     "She was scrupulous about documenting every expense."),
    ("Serendipity",     "noun",      "The occurrence of fortunate events by chance.",
     "Their meeting was pure serendipity."),
    ("Sycophant",       "noun",      "A person who acts obsequiously to gain favor.",
     "The executive was surrounded by sycophants who never challenged him."),
    ("Tacit",           "adjective", "Understood without being stated.",
     "There was a tacit agreement not to discuss the matter."),
    ("Tangential",      "adjective", "Diverging from a subject; barely relevant.",
     "His tangential comment distracted the entire meeting."),
    ("Temerity",        "noun",      "Excessive confidence or boldness.",
     "She had the temerity to challenge the board's decision publicly."),
    ("Tempestuous",     "adjective", "Characterized by strong emotion; turbulent.",
     "Their tempestuous partnership produced great work."),
    ("Tendentious",     "adjective", "Promoting a particular cause; biased.",
     "The report was clearly tendentious."),
    ("Timorous",        "adjective", "Showing or suffering from nervousness or a lack of confidence.",
     "The timorous candidate barely answered the question."),
    ("Torpid",          "adjective", "Mentally or physically inactive; lethargic.",
     "The torpid economy showed no signs of growth."),
    ("Tractable",       "adjective", "Easy to deal with; manageable.",
     "The tractable child adapted quickly to the new school."),
    ("Transgress",      "verb",      "Go beyond the limits of what is morally acceptable.",
     "He transgressed every boundary of professional conduct."),
    ("Transient",       "adjective", "Lasting only for a short time.",
     "The pain was transient and disappeared by morning."),
    ("Trite",           "adjective", "Overused and lacking in fresh meaning.",
     "The advice was trite and added nothing new."),
    ("Truculent",       "adjective", "Eager or quick to argue or fight; aggressively defiant.",
     "The truculent suspect refused to cooperate."),
    ("Turbulent",       "adjective", "Characterized by conflict, disorder, or confusion.",
     "The company navigated a turbulent first year."),
    ("Ubiquitous",      "adjective", "Present, appearing, or found everywhere.",
     "Smartphones have become ubiquitous in modern life."),
    ("Umbrage",         "noun",      "Offense or annoyance.",
     "She took umbrage at the offhand remark."),
    ("Uncanny",         "adjective", "Strange or mysterious; beyond normal.",
     "He had an uncanny ability to predict outcomes."),
    ("Unequivocal",     "adjective", "Leaving no doubt; unambiguous.",
     "Her answer was unequivocal: she would not resign."),
    ("Utilitarian",     "adjective", "Designed to be useful rather than attractive.",
     "The design was purely utilitarian."),
    ("Vacuous",         "adjective", "Having or showing a lack of thought or intelligence.",
     "The debate was full of vacuous soundbites."),
    ("Vapid",           "adjective", "Offering nothing stimulating; bland.",
     "His vapid commentary contributed nothing to the discussion."),
    ("Verbose",         "adjective", "Using more words than necessary.",
     "The verbose report could have been half as long."),
    ("Vicarious",       "adjective", "Experienced through another's life rather than one's own.",
     "She lived vicariously through travel blogs."),
    ("Visceral",        "adjective", "Relating to deep inward feelings; gut-level.",
     "The film provoked a visceral reaction."),
    ("Vitriolic",       "adjective", "Filled with bitter criticism or malice.",
     "His vitriolic review destroyed the restaurant's reputation."),
    ("Vociferous",      "adjective", "Expressing opinions loudly and forcefully.",
     "She was a vociferous critic of the proposal."),
    ("Volatile",        "adjective", "Liable to change rapidly and unpredictably.",
     "The volatile market made investors nervous."),
    ("Wanton",          "adjective", "Deliberate and unprovoked.",
     "It was an act of wanton destruction."),
    ("Zealous",         "adjective", "Having or showing great energy and enthusiasm.",
     "The zealous campaigner worked eighteen-hour days."),
    ("Zenith",          "noun",      "The highest point reached; peak.",
     "The company was at the zenith of its success."),
    ("Abstruse",        "adjective", "Difficult to understand; obscure.",
     "The abstruse philosophy paper confused even experts."),
    ("Acerbic",         "adjective", "Sharp and forthright in a critical way.",
     "Her acerbic reviews were feared across the industry."),
    ("Acquiesce",       "verb",      "Accept something reluctantly but without protest.",
     "He acquiesced to the demands to avoid further conflict."),
    ("Adroit",          "adjective", "Clever or skillful.",
     "She made an adroit move to avoid the question."),
    ("Affable",         "adjective", "Friendly, good-natured, and easy to talk to.",
     "The affable host made every guest feel at ease."),
    ("Aloof",           "adjective", "Not friendly or forthcoming; cool.",
     "His aloof manner made him hard to read."),
    ("Altruistic",      "adjective", "Showing unselfish concern for others' wellbeing.",
     "Her altruistic spirit drove her into nonprofit work."),
    ("Ambivalent",      "adjective", "Having mixed or contradictory feelings about something.",
     "She was ambivalent about the job offer."),
    ("Amiable",         "adjective", "Having a friendly and pleasant manner.",
     "He was an amiable colleague whom everyone enjoyed."),
    ("Anachronistic",   "adjective", "Belonging to a period other than that depicted.",
     "The anachronistic costume broke the film's immersion."),
    ("Antipathy",       "noun",      "A deep-seated aversion or dislike.",
     "She felt an instant antipathy toward the new policy."),
    ("Apathy",          "noun",      "Lack of interest, enthusiasm, or concern.",
     "Voter apathy led to record-low turnout."),
    ("Arbitrary",       "adjective", "Based on random choice rather than reason.",
     "The arbitrary ruling frustrated the legal team."),
    ("Arduous",         "adjective", "Involving or requiring strenuous effort.",
     "It was an arduous climb, but the view rewarded them."),
    ("Articulate",      "adjective", "Having or showing the ability to speak clearly.",
     "The articulate speaker held the audience's attention."),
    ("Ascetic",         "adjective", "Characterized by severe self-discipline.",
     "The monk led an ascetic life of prayer and fasting."),
    ("Astute",          "adjective", "Having an ability to accurately assess situations.",
     "The astute manager saw the problem before it grew."),
    ("Atypical",        "adjective", "Not representative of a type; unusual.",
     "Her atypical approach produced unexpected results."),
    ("Avaricious",      "adjective", "Having or showing an extreme greed for wealth.",
     "The avaricious executive prioritized profit over people."),
    ("Benign",          "adjective", "Gentle and kindly; not harmful.",
     "His benign indifference caused no real damage."),
    ("Callous",         "adjective", "Showing insensitive disregard for others.",
     "The callous response to the crisis shocked many."),
    ("Cathartic",       "adjective", "Providing psychological relief through strong emotion.",
     "Writing about the experience proved cathartic."),
    ("Cerebral",        "adjective", "Intellectual rather than emotional.",
     "The film was too cerebral for mainstream audiences."),
    ("Chronic",         "adjective", "Persisting for a long time; constantly recurring.",
     "Chronic stress takes a toll on long-term health."),
    ("Clandestine",     "adjective", "Kept secret or done secretively.",
     "The clandestine meeting was held after hours."),
    ("Clemency",        "noun",      "Mercy and leniency shown toward a criminal.",
     "The judge showed clemency given the circumstances."),
    ("Coercive",        "adjective", "Relating to or using force or threats.",
     "The coercive tactics violated company policy."),
    ("Coherent",        "adjective", "Logical and consistent.",
     "He gave a coherent account of the events."),
    ("Complicit",       "adjective", "Involved with others in wrongdoing.",
     "Silence made them complicit in the fraud."),
    ("Concise",         "adjective", "Giving a lot of information clearly in few words.",
     "A concise summary saves everyone time."),
    ("Condescending",   "adjective", "Having a superior air toward others.",
     "His condescending tone alienated the team."),
    ("Convivial",       "adjective", "Friendly and lively; relating to good company.",
     "The convivial dinner party lasted until midnight."),
    ("Cosmopolitan",    "adjective", "Familiar with and at ease in many countries and cultures.",
     "The cosmopolitan city attracted talent from everywhere."),
    ("Credulous",       "adjective", "Having an excessive readiness to believe things.",
     "The credulous investor fell for every pitch."),
    ("Cynical",         "adjective", "Believing that people are motivated purely by self-interest.",
     "Years of disappointment had made him cynical."),
    ("Daunting",        "adjective", "Seeming difficult to deal with; intimidating.",
     "The daunting list of tasks felt overwhelming at first."),
    ("Deliberate",      "adjective", "Done consciously and intentionally.",
     "It was a deliberate misrepresentation of the facts."),
    ("Despondent",      "adjective", "In low spirits from loss of hope; dejected.",
     "She was despondent after the rejection."),
    ("Determined",      "adjective", "Having made a firm decision; not to be dissuaded.",
     "He was determined to finish the project on time."),
    ("Devoted",         "adjective", "Very loving or loyal.",
     "She was devoted to her family above all else."),
    ("Diligent",        "adjective", "Having or showing care in one's work.",
     "Diligent preparation separates good from great."),
    ("Discordant",      "adjective", "Not in harmony; conflicting.",
     "His views were discordant with the rest of the team."),
]

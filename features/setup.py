"""
alfred/features/setup.py
========================
In-Telegram setup wizard for Alfred.

HOW IT WORKS
────────────
The /setup command launches a conversational onboarding flow directly in
Telegram. Alfred asks guided questions for each memory category, parses the
answers using GPT to extract discrete facts, and stores them in alfred_memory.json.

The wizard uses a simple file-based state machine (setup_state.json) so it
survives bot restarts mid-setup. State is cleared when setup completes or is
cancelled.

FLOW
────
  /setup                     → shows menu: [Memory] [Custom Category] [Reset]
  /setup memory              → starts the full memory onboarding
  /setup memory [category]   → resumes or starts a specific category
  /setup reset               → clears all memory and restarts from scratch (confirms first)
  /setup cancel              → exits the wizard

During an active setup session, all non-command user messages are routed here
by bot.py's message handler. bot.py checks is_setup_active() before passing
to the intent classifier.

COMMAND INTEGRATION
───────────────────
  Register in bot.py:
    app.add_handler(CommandHandler("setup", cmd_setup))
    app.add_handler(CallbackQueryHandler(handle_setup_callback, pattern="^setup_"))

  In the free-text message handler (before intent classification):
    if is_setup_active():
        await handle_setup_message(update, context)
        return
"""

import os
import json
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from core.config import (
    BOT_NAME,
    OPENAI_API_KEY,
    GPT_CHAT_MODEL,
    MEMORY_CATEGORIES,
    MEMORY_SETUP_QUESTIONS,
    SETUP_STATE_FILE,
)
from core.data import (
    load_memory,
    save_memory,
    add_memory_fact,
    add_custom_category,
    get_active_categories,
    load_data,
    save_data,
    get_briefing_settings,
    get_shopping_list_names,
    get_journal_settings,
    get_workout_settings,
    get_reply_settings,
    get_weekly_summary_settings,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# STATE MACHINE
# ─────────────────────────────────────────────────────────────────────────────
# setup_state.json structure:
# {
#   "active":    true,
#   "flow":      "memory",          ← which flow is running
#   "step":      0,                 ← index into FLOW_STEPS
#   "category":  "Me",              ← current category being filled
#   "q_index":   0,                 ← index into MEMORY_SETUP_QUESTIONS[category]
#   "skipped":   ["Finance"],       ← categories the buyer chose to skip
# }

def _load_state() -> dict:
    if os.path.exists(SETUP_STATE_FILE):
        try:
            with open(SETUP_STATE_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"active": False}


def _save_state(state: dict) -> None:
    tmp = SETUP_STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, SETUP_STATE_FILE)


def _clear_state() -> None:
    if os.path.exists(SETUP_STATE_FILE):
        os.remove(SETUP_STATE_FILE)


def is_setup_active() -> bool:
    """Return True if a setup wizard session is currently in progress."""
    return _load_state().get("active", False)


# ─────────────────────────────────────────────────────────────────────────────
# GPT FACT EXTRACTION
# ─────────────────────────────────────────────────────────────────────────────

_EXTRACT_SYSTEM = """You are extracting structured facts from a personal setup answer.
The user was asked: "{question}"
Their answer: "{answer}"

Extract individual facts and return them as a JSON object with a "facts" key.

Rules:
- Split compound answers into separate facts ("I'm 32, live in Austin, and I'm a designer" → 3 facts)
- Rephrase as third-person facts ("I have two kids" → "Has two kids, ages unknown")
- If the answer is vague, uncertain, or a refusal ("skip", "n/a", "not sure", "prefer not"), return empty list
- Keep each fact under 80 characters
- Return ONLY valid JSON like: {"facts": ["fact one", "fact two"]} or {"facts": []}"""


async def _extract_facts(question: str, answer: str) -> list:
    """
    Use GPT to parse a setup answer into a list of discrete memory facts.
    Returns a list of fact strings, or [] if the answer was empty/skipped.
    """
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=OPENAI_API_KEY)

    # Fast path: clearly empty or skip phrases
    lower = answer.strip().lower()
    if not lower or lower in {"skip", "n/a", "na", "no", "none", "nope", "pass", "-", "."}:
        return []

    try:
        resp = await client.chat.completions.create(
            model=GPT_CHAT_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": _EXTRACT_SYSTEM.format(question=question, answer=answer),
                }
            ],
            temperature=0,
            max_tokens=300,
            response_format={"type": "json_object"},
        )
        raw  = resp.choices[0].message.content.strip()
        data = json.loads(raw)
        # Primary expected format: {"facts": [...]}
        if isinstance(data, dict) and "facts" in data and isinstance(data["facts"], list):
            return [str(f).strip() for f in data["facts"] if f]
        # Fallback: bare list (should not occur with json_object format, but handle gracefully)
        if isinstance(data, list):
            return [str(f).strip() for f in data if f]
        return []
    except json.JSONDecodeError as e:
        logger.warning(f"setup: GPT returned invalid JSON in extract_facts: {e}")
        return []
    except Exception as e:
        logger.warning(f"setup extract_facts error: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# /setup COMMAND
# ─────────────────────────────────────────────────────────────────────────────

async def cmd_setup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /setup [subcommand]

    Subcommands:
      (none)         — show setup menu
      memory         — start / resume memory wizard
      memory [cat]   — jump to a specific category
      reset          — clear all memory and restart
      cancel         — exit wizard
    """
    args = context.args or []

    if not args:
        await _show_setup_menu(update, context)
        return

    sub = args[0].lower()

    if sub == "memory":
        category = " ".join(args[1:]).strip().title() if len(args) > 1 else None
        await _start_memory_flow(update, context, jump_to=category)

    elif sub == "reset":
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Yes, reset everything", callback_data="setup_reset_confirm"),
                InlineKeyboardButton("Cancel",               callback_data="setup_reset_cancel"),
            ]
        ])
        await update.message.reply_text(
            "⚠️ This will clear *all* of my memory and restart setup from scratch. Are you sure?",
            parse_mode="Markdown",
            reply_markup=keyboard,
        )

    elif sub == "cancel":
        _clear_state()
        await update.message.reply_text(
            "Setup cancelled. Your memory is unchanged.\n"
            "Run `/setup` anytime to continue.",
            parse_mode="Markdown",
        )

    else:
        await _show_setup_menu(update, context)


async def _show_setup_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the top-level setup menu."""
    mem    = load_memory()
    active = get_active_categories(mem)
    total  = sum(len(mem.get(c, [])) for c in active)

    status = f"_{total} facts stored across {len(active)} categories._" if total else "_No memory stored yet._"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ Configure preferences",  callback_data="setup_start_prefs")],
        [InlineKeyboardButton("🧠 Set up memory",          callback_data="setup_start_memory")],
        [InlineKeyboardButton("➕ Add custom category",    callback_data="setup_addcat")],
        [InlineKeyboardButton("🔄 Reset all memory",       callback_data="setup_reset_confirm_prompt")],
    ])
    await update.message.reply_text(
        f"*{BOT_NAME} Setup*\n\n{status}\n\n"
        "What would you like to do?",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


# ─────────────────────────────────────────────────────────────────────────────
# MEMORY WIZARD FLOW
# ─────────────────────────────────────────────────────────────────────────────

async def _start_memory_flow(
    update:   Update,
    context:  ContextTypes.DEFAULT_TYPE,
    jump_to:  str = None,
) -> None:
    """
    Begin (or resume) the memory setup wizard.

    Walks through each memory category in order, asking the buyer guided
    questions and extracting facts from their answers via GPT.
    """
    mem    = load_memory()
    active = get_active_categories(mem)

    # Determine starting category
    if jump_to:
        if jump_to not in active:
            await update.message.reply_text(
                f"Category '{jump_to}' not found. Active categories: {', '.join(active)}"
            )
            return
        start_category = jump_to
    else:
        start_category = active[0]

    state = {
        "active":   True,
        "flow":     "memory",
        "step":     active.index(start_category),
        "category": start_category,
        "q_index":  0,
        "skipped":  [],
    }
    _save_state(state)

    intro = (
        f"*Memory Setup*\n\n"
        f"I'll ask you a few questions for each category to build up my memory. "
        f"Answer naturally — I'll extract the important facts. "
        f"Type *skip* to skip any question or *done* to finish a category early.\n\n"
        f"You can stop anytime with `/setup cancel`.\n\n"
    )
    await update.message.reply_text(intro, parse_mode="Markdown")
    await _ask_next_question(update, context, state)


async def _ask_next_question(
    update:  Update,
    context: ContextTypes.DEFAULT_TYPE,
    state:   dict,
) -> None:
    """Ask the current question in the wizard flow."""
    mem    = load_memory()
    active = get_active_categories(mem)

    step     = state.get("step", 0)
    category = state.get("category")
    q_index  = state.get("q_index", 0)

    if step >= len(active):
        await _finish_memory_flow(update, context, state)
        return

    questions = MEMORY_SETUP_QUESTIONS.get(category, [
        f"Tell me anything you'd like me to remember about *{category}*."
    ])

    if q_index >= len(questions):
        # All questions for this category done — move to next category
        await _advance_to_next_category(update, context, state)
        return

    question = questions[q_index]

    # Build skip/done button row
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Skip question", callback_data=f"setup_skip_q"),
            InlineKeyboardButton("Done with category", callback_data=f"setup_skip_cat"),
        ]
    ])

    existing = mem.get(category, [])
    existing_note = ""
    if existing:
        existing_note = f"_(Already stored: {len(existing)} fact(s) in this category)_\n\n"

    await update.message.reply_text(
        f"*{category}* — question {q_index + 1} of {len(questions)}\n\n"
        f"{existing_note}"
        f"{question}",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


async def _advance_to_next_category(
    update:  Update,
    context: ContextTypes.DEFAULT_TYPE,
    state:   dict,
) -> None:
    """Move to the next category in the wizard."""
    mem    = load_memory()
    active = get_active_categories(mem)

    state["step"]    = state.get("step", 0) + 1
    state["q_index"] = 0

    if state["step"] >= len(active):
        await _finish_memory_flow(update, context, state)
        return

    state["category"] = active[state["step"]]
    _save_state(state)

    cat = state["category"]
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"Start {cat}", callback_data="setup_next_cat"),
            InlineKeyboardButton("Skip category", callback_data="setup_skip_cat"),
            InlineKeyboardButton("Finish setup",  callback_data="setup_finish"),
        ]
    ])
    await update.message.reply_text(
        f"✓ Done with that category.\n\n"
        f"Next: *{cat}*",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


async def _finish_memory_flow(
    update:  Update,
    context: ContextTypes.DEFAULT_TYPE,
    state:   dict,
) -> None:
    """Called when all categories have been completed."""
    _clear_state()
    mem    = load_memory()
    active = get_active_categories(mem)
    total  = sum(len(mem.get(c, [])) for c in active)

    skipped = state.get("skipped", [])
    skip_note = ""
    if skipped:
        skip_note = f"\n\n_Skipped: {', '.join(skipped)}. Run `/setup memory [category]` anytime to fill those in._"

    await update.message.reply_text(
        f"✅ *Setup complete!*\n\n"
        f"I've stored *{total} facts* across *{len(active)} categories*.\n\n"
        f"You can always:\n"
        f"• `/memory` — view everything I know\n"
        f"• `/memory add [category] [fact]` — add more\n"
        f"• `/setup memory [category]` — redo any category"
        f"{skip_note}",
        parse_mode="Markdown",
    )


# ─────────────────────────────────────────────────────────────────────────────
# FREE-TEXT MESSAGE HANDLER  (called by bot.py when setup is active)
# ─────────────────────────────────────────────────────────────────────────────

async def handle_setup_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Process a free-text message during an active setup session.

    bot.py calls this before the intent classifier whenever is_setup_active()
    returns True.
    """
    text  = (update.message.text or "").strip()
    state = _load_state()

    if not state.get("active"):
        return  # guard — should not happen if bot.py checks correctly

    flow = state.get("flow")

    if flow == "memory":
        await _handle_memory_answer(update, context, state, text)
    elif flow == "addcat":
        await _handle_addcat_answer(update, context, state, text)
    elif flow == "prefs":
        await _handle_prefs_answer(update, context, state, text)
    else:
        _clear_state()


async def _handle_memory_answer(
    update:  Update,
    context: ContextTypes.DEFAULT_TYPE,
    state:   dict,
    text:    str,
) -> None:
    """Process a user's answer to a memory question."""
    category  = state.get("category")
    q_index   = state.get("q_index", 0)
    questions = MEMORY_SETUP_QUESTIONS.get(category, [
        f"Tell me anything you'd like me to remember about *{category}*."
    ])

    question = questions[q_index] if q_index < len(questions) else f"Anything else for {category}?"

    # Extract facts from the answer
    facts = await _extract_facts(question, text)

    saved_count = 0
    for fact in facts:
        ok, _ = add_memory_fact(category, fact)
        if ok:
            saved_count += 1

    # Feedback
    if saved_count > 0:
        plural = "fact" if saved_count == 1 else "facts"
        await update.message.reply_text(
            f"✓ Saved {saved_count} {plural} under *{category}*.",
            parse_mode="Markdown",
        )
    elif text.lower() not in {"skip", "n/a", "na", "no", "none", "nope", "pass", "-", "."}:
        await update.message.reply_text(
            "_Nothing extracted — I'll move on._",
            parse_mode="Markdown",
        )

    # Advance to next question
    state["q_index"] = q_index + 1
    _save_state(state)
    await _ask_next_question(update, context, state)


async def _handle_addcat_answer(
    update:  Update,
    context: ContextTypes.DEFAULT_TYPE,
    state:   dict,
    text:    str,
) -> None:
    """Handle custom category name input."""
    _clear_state()
    ok, err = add_custom_category(text)
    if ok:
        name = text.strip().title()
        await update.message.reply_text(
            f"✓ Added category *{name}*.\n"
            f"Run `/setup memory {name}` to fill it in, "
            f"or `/memory add {name} [fact]` to add facts manually.",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(f"Couldn't add that category: {err}")


# ─────────────────────────────────────────────────────────────────────────────
# CALLBACK HANDLER  (inline button responses for setup wizard)
# ─────────────────────────────────────────────────────────────────────────────

async def handle_setup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle inline button presses from the setup wizard.
    Registered in bot.py as CallbackQueryHandler(pattern="^setup_").
    """
    query = update.callback_query
    await query.answer()
    data  = query.data
    state = _load_state()

    # ── Start preferences flow ────────────────────────────────────────────────
    if data == "setup_start_prefs":
        await query.edit_message_text("Starting preferences setup…")
        await _start_prefs_flow(update, context)
        return

    # ── Tone inline button selection ──────────────────────────────────────────
    if data.startswith("setup_prefs_tone_"):
        tone = data.split("setup_prefs_tone_", 1)[1]
        await query.edit_message_text(f"✓ Default reply tone set to: *{tone}*", parse_mode="Markdown")
        prefs_state = _load_state()
        await _save_prefs_answer("reply_tone", tone, prefs_state, update, context)
        return

    # ── Skip current prefs step ───────────────────────────────────────────────
    if data == "setup_prefs_skip":
        prefs_state = _load_state()
        await query.edit_message_text("_Skipped._", parse_mode="Markdown")
        prefs_state["step"] = prefs_state.get("step", 0) + 1
        _save_state(prefs_state)
        await _ask_prefs_step(update, context, prefs_state)
        return

    # ── Finish prefs early ────────────────────────────────────────────────────
    if data == "setup_prefs_finish":
        await query.edit_message_text("Finishing preferences setup…")
        await _finish_prefs_flow(update, context)
        return

    # ── Start memory flow ─────────────────────────────────────────────────────
    if data == "setup_start_memory":
        await query.edit_message_text("Starting memory setup…")
        await _start_memory_flow(update, context)
        return

    # ── Skip a single question ────────────────────────────────────────────────
    if data == "setup_skip_q":
        state["q_index"] = state.get("q_index", 0) + 1
        _save_state(state)
        await query.edit_message_text("_Skipped._", parse_mode="Markdown")
        await _ask_next_question(update, context, state)
        return

    # ── Skip entire category ──────────────────────────────────────────────────
    if data == "setup_skip_cat":
        skipped = state.get("skipped", [])
        cat     = state.get("category", "")
        if cat and cat not in skipped:
            skipped.append(cat)
        state["skipped"] = skipped
        _save_state(state)
        await query.edit_message_text(f"_Skipped {cat}._", parse_mode="Markdown")
        await _advance_to_next_category(update, context, state)
        return

    # ── Start next category (after between-category prompt) ───────────────────
    if data == "setup_next_cat":
        await query.edit_message_text("_Starting next category…_", parse_mode="Markdown")
        await _ask_next_question(update, context, state)
        return

    # ── Finish early ──────────────────────────────────────────────────────────
    if data == "setup_finish":
        await query.edit_message_text("Wrapping up setup…")
        await _finish_memory_flow(update, context, state)
        return

    # ── Add custom category (from menu) ───────────────────────────────────────
    if data == "setup_addcat":
        state = {"active": True, "flow": "addcat"}
        _save_state(state)
        await query.edit_message_text(
            "What would you like to call the new category? "
            "(e.g. *Pets*, *Hobbies*, *Business*)",
            parse_mode="Markdown",
        )
        return

    # ── Reset prompt ──────────────────────────────────────────────────────────
    if data == "setup_reset_confirm_prompt":
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Yes, reset everything", callback_data="setup_reset_confirm"),
                InlineKeyboardButton("Cancel",               callback_data="setup_reset_cancel"),
            ]
        ])
        await query.edit_message_text(
            "⚠️ This will clear *all* of my memory and restart setup from scratch. Are you sure?",
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
        return

    # ── Reset confirmed ───────────────────────────────────────────────────────
    if data == "setup_reset_confirm":
        mem = load_memory()
        active = get_active_categories(mem)
        for cat in active:
            mem[cat] = []
        save_memory(mem)
        _clear_state()
        await query.edit_message_text(
            "✓ All memory cleared. Run `/setup memory` to start fresh.",
            parse_mode="Markdown",
        )
        return

    # ── Reset cancelled ───────────────────────────────────────────────────────
    if data == "setup_reset_cancel":
        _clear_state()
        await query.edit_message_text("Cancelled — memory unchanged.")
        return


# ─────────────────────────────────────────────────────────────────────────────
# PREFERENCES WIZARD
# ─────────────────────────────────────────────────────────────────────────────
# Walks the buyer through all configurable feature settings in one guided flow.
# State machine key: flow = "prefs", step = index into _PREFS_STEPS.

import re as _re

_ALL_BRIEFING_SECTIONS = [
    "weather", "calendar", "todos", "habits", "quote",
    "word_of_day", "meals", "journal_highlight", "workout_stats",
]

_WEEKDAY_MAP = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
    "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
}

# Ordered list of step keys
_PREFS_STEPS = [
    "reply_tone",
    "briefing_sections",
    "shopping_lists",
    "weekly_summary",
    "workout",
    "meals",
    "journal",
    "meal_nutrition",
    "smart_suggestions",
]

_PREFS_TITLES = {
    "reply_tone":        "🗨️ Reply Tone",
    "briefing_sections": "🌅 Morning Briefing Sections",
    "shopping_lists":    "🛒 Shopping List Names",
    "weekly_summary":    "📊 Weekly Summary Schedule",
    "workout":           "💪 Workout Setup",
    "meals":             "🍽️ Meal Adherence Reminder",
    "journal":           "📓 Journal Reminder",
    "meal_nutrition":    "🥗 Meal Nutrition Goals",
    "smart_suggestions": "💡 Smart Pattern Suggestions",
}

_PREFS_PROMPTS = {
    "reply_tone": (
        "What default tone should I use when drafting reply suggestions?\n\n"
        "Tap a button below, or type: *warm*, *professional*, *casual*, or *playful*."
    ),
    "briefing_sections": (
        "Which sections do you want in your morning briefing, and in what order?\n\n"
        "Available: `weather`, `calendar`, `todos`, `habits`, `quote`, `word_of_day`, "
        "`meals`, `journal_highlight`, `workout_stats`\n\n"
        "Type as a comma-separated list — e.g. *weather, calendar, todos, habits, quote*\n"
        "Type *skip* to keep defaults."
    ),
    "shopping_lists": (
        "What would you like to call your shopping lists?\n"
        "Type 1–5 names separated by commas.\n\n"
        "Example: *groceries, pharmacy, amazon*\n"
        "Type *skip* for defaults: grocery, household, wishlist."
    ),
    "weekly_summary": (
        "When should I deliver your weekly AI summary?\n\n"
        "Format: *Monday 9am* or *Sunday 8:00pm*\n"
        "Type *skip* to keep the current setting."
    ),
    "workout": (
        "Let's set up your workout tracker. Answer these 5 things separated by commas:\n\n"
        "1. Goal: `build_muscle` | `lose_weight` | `strength` | `endurance` | `general_fitness`\n"
        "2. Days per week (1–7)\n"
        "3. Equipment: `gym` | `home` | `bodyweight` | `minimal`\n"
        "4. Preferences / injuries (or *none*)\n"
        "5. Progressive overload: *yes* | *no*\n\n"
        "Example: *build_muscle, 4, gym, none, yes*\n"
        "Type *skip* to keep current setting."
    ),
    "meals": (
        "What time should I check in about meal adherence each evening?\n\n"
        "Format: *8:00pm* or *20:00*\n"
        "Type *skip* for default (8:00pm)."
    ),
    "journal": (
        "What time should I send your evening journal reminder?\n"
        "For multiple reminders, separate with commas: *9:00pm, 10:00pm*\n\n"
        "Type *skip* for default (9:00pm)."
    ),
    "meal_nutrition": (
        "Set your daily macro targets for meal tracking.\n"
        "Format: *calories, protein_g, carbs_g, fat_g*\n\n"
        "Example: *2000, 150, 200, 65*\n"
        "Type *skip* if you don't want to track macros."
    ),
    "smart_suggestions": (
        "Alfred can proactively spot patterns and nudge you. Which areas?\n\n"
        "Type any/all: *habits*, *workout*, *meals*, *mood*, *shopping*\n"
        "Or type *all* to enable everything, *none* to disable.\n\n"
        "Example: *habits, workout, mood*"
    ),
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_time(s: str):
    """Parse '9:30pm', '21:30', '9pm', '9am' → (hour, minute) or None."""
    s = s.strip().lower()
    m = _re.match(r'^(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$', s)
    if not m:
        return None
    hour   = int(m.group(1))
    minute = int(m.group(2) or 0)
    ampm   = m.group(3)
    if ampm == "pm" and hour != 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return (hour, minute)


def _fmt_time(hour: int, minute: int) -> str:
    """Format (hour, minute) → '9:00am' style."""
    suffix = "am" if hour < 12 else "pm"
    h      = hour % 12 or 12
    return f"{h}:{minute:02d}{suffix}"


# ── Flow entry ────────────────────────────────────────────────────────────────

async def _start_prefs_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Begin the preferences wizard from step 0."""
    state = {"active": True, "flow": "prefs", "step": 0}
    _save_state(state)

    # Determine which message object to use (could come from callback or command)
    msg = (
        update.callback_query.message
        if update.callback_query
        else update.message
    )

    total = len(_PREFS_STEPS)
    intro = (
        f"*{BOT_NAME} Preferences*\n\n"
        f"I'll walk you through {total} settings. "
        f"Type your answer or tap *Skip* for each one.\n\n"
        f"Type `/setup cancel` at any time to exit.\n"
    )
    await msg.reply_text(intro, parse_mode="Markdown")
    await _ask_prefs_step(update, context, state)


async def _ask_prefs_step(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    state: dict,
) -> None:
    """Send the prompt for the current preferences step."""
    step  = state.get("step", 0)
    total = len(_PREFS_STEPS)

    if step >= total:
        await _finish_prefs_flow(update, context)
        return

    key    = _PREFS_STEPS[step]
    title  = _PREFS_TITLES[key]
    prompt = _PREFS_PROMPTS[key]

    header = f"*{title}*  _{step + 1}/{total}_\n\n{prompt}"

    # For reply_tone, show inline tone buttons
    if key == "reply_tone":
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Warm 🤗",         callback_data="setup_prefs_tone_warm"),
                InlineKeyboardButton("Professional 💼", callback_data="setup_prefs_tone_professional"),
            ],
            [
                InlineKeyboardButton("Casual 😎",       callback_data="setup_prefs_tone_casual"),
                InlineKeyboardButton("Playful 😄",      callback_data="setup_prefs_tone_playful"),
            ],
            [InlineKeyboardButton("Skip", callback_data="setup_prefs_skip")],
        ])
    else:
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Skip",         callback_data="setup_prefs_skip"),
                InlineKeyboardButton("Finish setup", callback_data="setup_prefs_finish"),
            ]
        ])

    # Determine message target
    msg = (
        update.callback_query.message
        if update.callback_query
        else update.message
    )
    await msg.reply_text(header, parse_mode="Markdown", reply_markup=keyboard)


async def _handle_prefs_answer(
    update:  Update,
    context: ContextTypes.DEFAULT_TYPE,
    state:   dict,
    text:    str,
) -> None:
    """Process a text answer for the current prefs step."""
    await _save_prefs_answer(_PREFS_STEPS[state.get("step", 0)], text, state, update, context)


async def _save_prefs_answer(
    key:    str,
    answer: str,
    state:  dict,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Parse and persist a preference answer, then advance to the next step."""
    msg = (
        update.callback_query.message
        if update.callback_query
        else update.message
    )

    skip = answer.strip().lower() in {"skip", "s", "next", ""}
    data = load_data()
    feedback = ""

    # ── reply_tone ────────────────────────────────────────────────────────────
    if key == "reply_tone":
        if not skip:
            tone = answer.strip().lower()
            if tone in {"warm", "professional", "casual", "playful"}:
                rs = get_reply_settings(data)
                rs["default_tone"] = tone
                save_data(data)
                feedback = f"✓ Reply tone set to *{tone}*."
            else:
                await msg.reply_text(
                    "Please choose: warm, professional, casual, or playful."
                )
                return  # don't advance — ask again

    # ── briefing_sections ─────────────────────────────────────────────────────
    elif key == "briefing_sections":
        if not skip:
            parts = [p.strip().lower() for p in answer.split(",") if p.strip()]
            valid = [p for p in parts if p in _ALL_BRIEFING_SECTIONS]
            if valid:
                bs = get_briefing_settings(data)
                bs["enabled"] = valid
                bs["order"]   = valid
                save_data(data)
                feedback = f"✓ Briefing sections set to: {', '.join(valid)}."
            else:
                await msg.reply_text(
                    "I didn't recognise any of those section names. "
                    "Valid options: " + ", ".join(_ALL_BRIEFING_SECTIONS)
                )
                return

    # ── shopping_lists ────────────────────────────────────────────────────────
    elif key == "shopping_lists":
        if not skip:
            names = [n.strip().lower() for n in answer.split(",") if n.strip()]
            names = names[:5]
            if names:
                data.setdefault("settings", {})["shopping_lists"] = names
                save_data(data)
                feedback = f"✓ Shopping lists set to: {', '.join(n.title() for n in names)}."
            else:
                await msg.reply_text("Please enter at least one list name.")
                return

    # ── weekly_summary ────────────────────────────────────────────────────────
    elif key == "weekly_summary":
        if not skip:
            # Parse "Monday 9am" or "Monday 9:30am"
            parts   = answer.strip().lower().split()
            weekday = None
            time_t  = None
            for p in parts:
                if p in _WEEKDAY_MAP:
                    weekday = _WEEKDAY_MAP[p]
                elif _parse_time(p):
                    time_t = _parse_time(p)
            if weekday is None or time_t is None:
                await msg.reply_text(
                    "Couldn't parse that. Try: *Monday 9am* or *Sunday 8:00pm*",
                    parse_mode="Markdown",
                )
                return
            ws = get_weekly_summary_settings(data)
            ws["weekday"] = weekday
            ws["hour"]    = time_t[0]
            ws["minute"]  = time_t[1]
            save_data(data)
            day_name = [k for k, v in _WEEKDAY_MAP.items() if v == weekday and len(k) > 3][0].title()
            feedback = f"✓ Weekly summary set to {day_name} at {_fmt_time(*time_t)}."

    # ── workout ───────────────────────────────────────────────────────────────
    elif key == "workout":
        if not skip:
            parts = [p.strip() for p in answer.split(",")]
            if len(parts) < 5:
                await msg.reply_text(
                    "Please provide all 5 values separated by commas.\n"
                    "Example: *build_muscle, 4, gym, none, yes*",
                    parse_mode="Markdown",
                )
                return
            goal, days_str, equipment, prefs_str, overload_str = parts[:5]
            valid_goals = {"build_muscle", "lose_weight", "strength", "endurance", "general_fitness"}
            valid_equip = {"gym", "home", "bodyweight", "minimal"}
            goal      = goal.lower().replace(" ", "_")
            equipment = equipment.lower()
            if goal not in valid_goals:
                await msg.reply_text(
                    f"Goal must be one of: {', '.join(valid_goals)}"
                )
                return
            if equipment not in valid_equip:
                await msg.reply_text(
                    f"Equipment must be one of: {', '.join(valid_equip)}"
                )
                return
            try:
                days = max(1, min(7, int(days_str.strip())))
            except ValueError:
                days = 4
            overload = overload_str.strip().lower() in {"yes", "y", "true", "1"}
            ws = get_workout_settings(data)
            ws["goal"]               = goal
            ws["days_per_week"]      = days
            ws["equipment"]          = equipment
            ws["preferences"]        = prefs_str.strip() if prefs_str.strip().lower() != "none" else ""
            ws["progressive_overload"] = overload
            save_data(data)
            feedback = (
                f"✓ Workout: {goal.replace('_', ' ').title()}, "
                f"{days}×/week, {equipment}, "
                f"progressive overload {'on' if overload else 'off'}."
            )

    # ── meals ─────────────────────────────────────────────────────────────────
    elif key == "meals":
        if not skip:
            t = _parse_time(answer.strip())
            if not t:
                await msg.reply_text(
                    "Couldn't parse that time. Try: *8:00pm* or *20:00*",
                    parse_mode="Markdown",
                )
                return
            ms = data.setdefault("settings", {}).setdefault("meals", {})
            ms["adherence_check_time"] = f"{t[0]:02d}:{t[1]:02d}"
            save_data(data)
            feedback = f"✓ Meal adherence check set to {_fmt_time(*t)}."

    # ── journal ───────────────────────────────────────────────────────────────
    elif key == "journal":
        if not skip:
            raw_times = [s.strip() for s in answer.split(",") if s.strip()]
            parsed    = [_parse_time(s) for s in raw_times]
            parsed    = [t for t in parsed if t is not None]
            if not parsed:
                await msg.reply_text(
                    "Couldn't parse time(s). Try: *9:00pm* or *9pm, 10pm*",
                    parse_mode="Markdown",
                )
                return
            js = get_journal_settings(data)
            js["reminder_times"] = [f"{t[0]:02d}:{t[1]:02d}" for t in parsed]
            js["reminder_count"] = len(parsed)
            save_data(data)
            labels   = ", ".join(_fmt_time(*t) for t in parsed)
            feedback = f"✓ Journal reminder(s) set to: {labels}."

    # ── meal_nutrition ────────────────────────────────────────────────────────
    elif key == "meal_nutrition":
        if not skip:
            parts = [p.strip() for p in answer.split(",")]
            if len(parts) >= 4:
                try:
                    cals   = int(parts[0])
                    prot   = int(parts[1])
                    carbs  = int(parts[2])
                    fat    = int(parts[3])
                    data.setdefault("settings", {}).setdefault("meals", {}).update({
                        "target_calories": cals,
                        "target_protein":  prot,
                        "target_carbs":    carbs,
                        "target_fat":      fat,
                    })
                    save_data(data)
                    feedback = f"✓ Nutrition targets: {cals} kcal, {prot}g protein, {carbs}g carbs, {fat}g fat."
                except ValueError:
                    await msg.reply_text("Couldn't parse that. Use: *2000, 150, 200, 65*", parse_mode="Markdown")
                    return
            else:
                await msg.reply_text("Please provide all 4 values: calories, protein, carbs, fat.", parse_mode="Markdown")
                return

    # ── smart_suggestions ─────────────────────────────────────────────────────
    elif key == "smart_suggestions":
        if not skip:
            lower = answer.strip().lower()
            valid_areas = {"habits", "workout", "meals", "mood", "shopping"}
            if lower == "all":
                areas = list(valid_areas)
            elif lower in {"none", "off", "disable"}:
                areas = []
                data.setdefault("settings", {}).setdefault("smart_suggestions", {})["enabled"] = False
            else:
                areas = [a.strip() for a in lower.split(",") if a.strip() in valid_areas]
            ss = data.setdefault("settings", {}).setdefault("smart_suggestions", {})
            ss["areas"]   = areas
            ss["enabled"] = len(areas) > 0
            save_data(data)
            if areas:
                feedback = f"✓ Smart suggestions enabled for: {', '.join(areas)}."
            else:
                feedback = "✓ Smart suggestions disabled."

    # ── Advance state ─────────────────────────────────────────────────────────
    if skip:
        feedback = "_Skipped — keeping current setting._"

    if feedback:
        await msg.reply_text(feedback, parse_mode="Markdown")

    state["step"] = state.get("step", 0) + 1
    _save_state(state)
    await _ask_prefs_step(update, context, state)


async def _finish_prefs_flow(
    update:  Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Called when all preference steps are done."""
    _clear_state()
    msg = (
        update.callback_query.message
        if update.callback_query
        else update.message
    )
    await msg.reply_text(
        "✅ *Preferences saved!*\n\n"
        "Alfred will use these settings going forward. "
        "Run `/setup` anytime to update them.\n\n"
        "Some changes (like journal reminder times) take effect after the next restart.",
        parse_mode="Markdown",
    )

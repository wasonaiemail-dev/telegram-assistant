"""
alfred/features/memory.py
=========================
Handles all Alfred memory operations exposed to the user.

COMMANDS
────────
  /memory                  — show all memory (paginated by category)
  /memory [category]       — show one category
  /memory add [cat] [fact] — add a fact directly
  /memory remove [cat] [#] — remove fact by number
  /memory clear [cat]      — wipe an entire category (with confirmation)
  /memory addcat [name]    — add a custom category
  /memory removecat [name] — remove a custom category

AUTO-SUGGEST
────────────
  suggest_memory_fact(user_text, assistant_text) → None
      Called after every /ask response. Runs a lightweight GPT check to see
      if the user revealed a memorable personal fact. If so, sends a Telegram
      inline keyboard prompt: "Should I remember: [fact]?"
      The user taps Yes/No. Yes triggers add_memory_fact(), No discards silently.

CONTEXT INJECTION (called by other feature modules)
────────────────────────────────────────────────────
  get_context_for_message(text) → str
      Returns the memory block to inject into a GPT system prompt for the
      given user message. Uses relevant-category matching so only applicable
      categories are included.

  get_full_context() → str
      Returns all non-empty memory. Used for briefing, weekly summary, etc.
"""

import json
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from core.config import (
    BOT_NAME,
    OPENAI_API_KEY,
    GPT_CHAT_MODEL,
    MEMORY_MAX_FACTS_PER_CATEGORY,
)
from core.data import (
    load_memory,
    save_memory,
    get_active_categories,
    add_memory_fact,
    remove_memory_fact,
    add_custom_category,
    remove_custom_category,
    get_memory_context,
    get_relevant_categories,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# CONTEXT INJECTION HELPERS  (called by other features, not directly by users)
# ─────────────────────────────────────────────────────────────────────────────

def get_context_for_message(text: str) -> str:
    """
    Return the memory block for injecting into a GPT call for this message.

    Only injects Me + Preferences (always) + keyword-matched categories.
    Returns empty string if memory has no relevant facts.
    """
    return get_memory_context(text=text)


def get_full_context() -> str:
    """
    Return all non-empty memory categories.

    Used by briefing, weekly summary, and any feature that needs the full
    picture rather than just what's relevant to a single message.
    """
    return get_memory_context(text=None)


# ─────────────────────────────────────────────────────────────────────────────
# DISPLAY HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _format_category(cat: str, facts: list, show_numbers: bool = True) -> str:
    """Format a single category for Telegram display."""
    if not facts:
        return f"*{cat}*\n  _nothing stored yet_"
    lines = [f"*{cat}*"]
    for i, fact in enumerate(facts, 1):
        prefix = f"{i}. " if show_numbers else "• "
        lines.append(f"  {prefix}{fact}")
    return "\n".join(lines)


def _format_all_memory(mem: dict = None) -> str:
    """Format the full memory for display, grouped by category."""
    if mem is None:
        mem = load_memory()

    active = get_active_categories(mem)
    sections = []
    for cat in active:
        facts = mem.get(cat, [])
        sections.append(_format_category(cat, facts))

    if not sections:
        return "_No memory stored yet. Run /setup to get started._"

    total = sum(len(mem.get(c, [])) for c in active)
    header = f"🧠 *{BOT_NAME}'s Memory* ({total} facts)\n"
    return header + "\n\n".join(sections)


# ─────────────────────────────────────────────────────────────────────────────
# /memory COMMAND HANDLER
# ─────────────────────────────────────────────────────────────────────────────

async def cmd_memory(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /memory [subcommand] [args]

    Subcommands:
      (none)              — show all memory
      [category]          — show one category
      add [cat] [fact]    — add a fact
      remove [cat] [#]    — remove fact by 1-based index
      clear [cat]         — wipe a category
      addcat [name]       — add a custom category
      removecat [name]    — remove a custom category
    """
    args    = context.args or []
    mem     = load_memory()
    active  = get_active_categories(mem)

    # ── /memory (no args) ────────────────────────────────────────────────────
    if not args:
        await update.message.reply_text(
            _format_all_memory(mem),
            parse_mode="Markdown",
        )
        return

    sub = args[0].lower()

    # ── /memory add [category] [fact...] ─────────────────────────────────────
    if sub == "add":
        if len(args) < 3:
            cats = ", ".join(active)
            await update.message.reply_text(
                f"Usage: `/memory add [category] [fact]`\n"
                f"Categories: {cats}",
                parse_mode="Markdown",
            )
            return

        category = args[1].strip().title()
        fact     = " ".join(args[2:]).strip()

        ok, err = add_memory_fact(category, fact)
        if ok:
            await update.message.reply_text(
                f"✓ Remembered under *{category}*: _{fact}_",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(f"Couldn't save that: {err}")
        return

    # ── /memory remove [category] [#] ────────────────────────────────────────
    if sub == "remove":
        if len(args) < 3:
            await update.message.reply_text(
                "Usage: `/memory remove [category] [number]`\n"
                "Example: `/memory remove Health 2`",
                parse_mode="Markdown",
            )
            return

        category = args[1].strip().title()
        try:
            idx = int(args[2])
        except ValueError:
            await update.message.reply_text("The number must be a whole number, e.g. `/memory remove Me 3`", parse_mode="Markdown")
            return

        removed, err = remove_memory_fact(category, idx)
        if removed:
            await update.message.reply_text(
                f"✓ Removed from *{category}*: _{removed}_",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(f"Couldn't remove that: {err}")
        return

    # ── /memory clear [category] ─────────────────────────────────────────────
    if sub == "clear":
        if len(args) < 2:
            await update.message.reply_text("Usage: `/memory clear [category]`", parse_mode="Markdown")
            return

        category = args[1].strip().title()
        if category not in active:
            await update.message.reply_text(
                f"Unknown category '{category}'. Active: {', '.join(active)}"
            )
            return

        facts = mem.get(category, [])
        if not facts:
            await update.message.reply_text(f"*{category}* is already empty.", parse_mode="Markdown")
            return

        # Store pending clear in bot_data for confirmation step
        context.bot_data["pending_memory_clear"] = category
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Yes, clear it", callback_data=f"mem_clear_confirm:{category}"),
                InlineKeyboardButton("Cancel",        callback_data="mem_clear_cancel"),
            ]
        ])
        await update.message.reply_text(
            f"Clear all {len(facts)} fact(s) from *{category}*? This can't be undone.",
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
        return

    # ── /memory addcat [name] ────────────────────────────────────────────────
    if sub == "addcat":
        if len(args) < 2:
            await update.message.reply_text("Usage: `/memory addcat [category name]`", parse_mode="Markdown")
            return

        name = " ".join(args[1:]).strip()
        ok, err = add_custom_category(name)
        if ok:
            await update.message.reply_text(
                f"✓ Added category *{name.title()}*. Add facts with `/memory add {name.title()} [fact]`.",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(f"Couldn't add category: {err}")
        return

    # ── /memory removecat [name] ─────────────────────────────────────────────
    if sub == "removecat":
        if len(args) < 2:
            await update.message.reply_text("Usage: `/memory removecat [category name]`", parse_mode="Markdown")
            return

        name = " ".join(args[1:]).strip().title()
        ok, err = remove_custom_category(name)
        if ok:
            await update.message.reply_text(f"✓ Removed category *{name}* and all its facts.", parse_mode="Markdown")
        else:
            await update.message.reply_text(f"Couldn't remove: {err}")
        return

    # ── /memory [category name] — show single category ───────────────────────
    # Try to match the first arg (and possibly more) to a category name
    cat_query = " ".join(args).strip().title()
    if cat_query in active:
        facts = mem.get(cat_query, [])
        await update.message.reply_text(
            _format_category(cat_query, facts),
            parse_mode="Markdown",
        )
        return

    # Unknown subcommand
    await update.message.reply_text(
        f"Unknown memory command. Options:\n"
        f"  `/memory` — show all\n"
        f"  `/memory [category]` — show one category\n"
        f"  `/memory add [cat] [fact]` — add a fact\n"
        f"  `/memory remove [cat] [#]` — remove by number\n"
        f"  `/memory clear [cat]` — wipe a category\n"
        f"  `/memory addcat [name]` — add custom category\n"
        f"  `/memory removecat [name]` — remove custom category",
        parse_mode="Markdown",
    )


# ─────────────────────────────────────────────────────────────────────────────
# CALLBACK HANDLER  (inline button responses for memory clear)
# ─────────────────────────────────────────────────────────────────────────────

async def handle_memory_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle inline button presses from memory operations.
    Registered in bot.py as a CallbackQueryHandler matching pattern "^mem_".
    """
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("mem_clear_confirm:"):
        category = data.split(":", 1)[1]
        mem = load_memory()
        if category in mem:
            mem[category] = []
            save_memory(mem)
            await query.edit_message_text(f"✓ *{category}* memory cleared.", parse_mode="Markdown")
        else:
            await query.edit_message_text(f"Category '{category}' not found.")

    elif data == "mem_clear_cancel":
        await query.edit_message_text("Cancelled — memory unchanged.")

    elif data.startswith("mem_suggest_yes:"):
        # User confirmed auto-suggested fact
        payload = data[len("mem_suggest_yes:"):]
        try:
            parts    = json.loads(payload)
            category = parts["category"]
            fact     = parts["fact"]
        except (json.JSONDecodeError, KeyError):
            await query.edit_message_text("Something went wrong saving that fact.")
            return
        ok, err = add_memory_fact(category, fact)
        if ok:
            await query.edit_message_text(
                f"✓ Remembered under *{category}*: _{fact}_",
                parse_mode="Markdown",
            )
        else:
            await query.edit_message_text(f"Couldn't save: {err}")

    elif data == "mem_suggest_no":
        await query.edit_message_text("Got it — I won't remember that.")


# ─────────────────────────────────────────────────────────────────────────────
# AUTO-SUGGEST  (called after /ask responses)
# ─────────────────────────────────────────────────────────────────────────────

_SUGGEST_SYSTEM = """You are a personal assistant deciding whether a user just revealed a memorable fact.

A memorable fact is something personal, long-lived, and useful to remember for future conversations.
Examples of memorable facts: allergies, health conditions, job changes, relationship info, strong preferences, goals.
Examples of NON-memorable things: questions, one-time tasks, vague statements, general opinions.

Given the user's message, reply with JSON ONLY:
  {"memorable": true, "category": "Health", "fact": "I am allergic to shellfish"}
  OR
  {"memorable": false}

Categories to choose from: {categories}

Return JSON only. No explanation."""


async def suggest_memory_fact(
    user_text:       str,
    assistant_text:  str,
    update:          Update,
    context:         ContextTypes.DEFAULT_TYPE,
) -> None:
    """
    After an /ask response, check if the user revealed a memorable personal fact.

    Runs a lightweight GPT call (non-blocking). If a fact is detected, sends
    the user an inline keyboard prompt: "Should I remember this?"

    Args:
        user_text:      The user's original message.
        assistant_text: Alfred's response (for context).
        update:         Telegram Update object.
        context:        Telegram context object.
    """
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=OPENAI_API_KEY)

    mem        = load_memory()
    categories = get_active_categories(mem)
    cats_str   = ", ".join(f'"{c}"' for c in categories)

    try:
        resp = await client.chat.completions.create(
            model=GPT_CHAT_MODEL,
            messages=[
                {"role": "system",    "content": _SUGGEST_SYSTEM.format(categories=cats_str)},
                {"role": "user",      "content": user_text},
                {"role": "assistant", "content": assistant_text},
            ],
            temperature=0,
            max_tokens=100,
            response_format={"type": "json_object"},
            timeout=10,  # non-blocking — if it hangs, skip silently
        )
        raw  = resp.choices[0].message.content.strip()
        data = json.loads(raw)

        if not data.get("memorable"):
            return  # nothing worth remembering

        category = data.get("category", "").strip().title()
        fact     = data.get("fact",     "").strip()

        if not category or not fact:
            return
        if category not in categories:
            return

        # Already know this fact?
        existing = mem.get(category, [])
        if any(f.lower() == fact.lower() for f in existing):
            return

        # Send confirmation prompt with inline buttons
        payload = json.dumps({"category": category, "fact": fact})
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✓ Remember it",    callback_data=f"mem_suggest_yes:{payload}"),
                InlineKeyboardButton("✗ Don't remember", callback_data="mem_suggest_no"),
            ]
        ])
        await update.message.reply_text(
            f"💡 Should I remember this?\n\n"
            f"*{category}:* _{fact}_",
            parse_mode="Markdown",
            reply_markup=keyboard,
        )

    except json.JSONDecodeError:
        pass  # malformed GPT response — silent fail is correct
    except Exception as e:
        logger.warning(f"memory suggest_fact error: {e}")

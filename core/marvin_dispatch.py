"""
marvin/core/marvin_dispatch.py
================================
Platform-agnostic intent dispatcher.

USAGE
-----
Both bot.py (Telegram) and discord_bot.py (Discord) call this:

    from core.marvin_dispatch import marvin_dispatch
    await marvin_dispatch(intent_result, ctx, loaded_plugins)

HOW MIGRATION WORKS
-------------------
Each feature handler is either:

  MIGRATED    — accepts (intent, ents, ctx: MarvinContext)
                Works on all platforms.

  UNMIGRATED  — accepts (intent, ents, update, context)
                On Telegram: works via ctx._update / ctx._context pass-through.
                On Discord:  returns a friendly "coming soon" message.

As we migrate features file by file, move them from the UNMIGRATED
section to the MIGRATED section of this dispatcher. Eventually the
UNMIGRATED section will be empty.

MIGRATION CHECKLIST
-------------------
  MIGRATED (Phase 4 / 4C — all features work on Discord via !command and NL):
    [x] Sports plugin (via plugin_loader dispatch)
    [x] ask / unknown
    [x] todos
    [x] notes
    [x] reminders
    [x] shopping
    [x] calendar
    [x] habits
    [x] gifts
    [x] contacts
    [x] meals          — Phase 4C: !meals added to discord_bot.py
    [x] workout        — Phase 4C: !workout added to discord_bot.py
    [x] journal        — Phase 4C: !journal added to discord_bot.py
    [x] reply_assist   — Phase 4C: !reply added to discord_bot.py
    [x] mood
    [x] links
    [x] export
    [x] memory
    [x] briefing
    [x] weather
    [x] weekly_summary — Phase 4C: !weekly added to discord_bot.py
    [x] expenses       — !expenses added to discord_bot.py
    [x] sleep          — !sleep added to discord_bot.py
    [x] proactive      — !proactive added to discord_bot.py
    [x] vacation       — "vacation on/off" NL on both platforms
    [x] travel         — /travel command on both platforms
    [x] tomorrow_prep  — /tomorrowprep command on both platforms
"""

from __future__ import annotations

import asyncio
import logging
import traceback

from core.marvin_context import MarvinContext

logger = logging.getLogger(__name__)

# Message shown on Discord for features not yet migrated to MarvinContext
_DISCORD_COMING_SOON = (
    "⚙️ This feature isn't available on Discord yet — it's being migrated. "
    "Use the Telegram bot in the meantime."
)


async def marvin_dispatch(
    intent_result,
    ctx: MarvinContext,
    loaded_plugins: list,
) -> None:
    """
    Dispatch a classified intent to the appropriate feature handler.

    For MIGRATED features: passes ctx (works on all platforms).
    For UNMIGRATED features on Telegram: uses ctx._update / ctx._context.
    For UNMIGRATED features on Discord: sends a friendly "coming soon" message.
    """
    from core.intent import (
        TODO_ADD, TODO_LIST, TODO_COMPLETE, TODO_DELETE, TODO_UPDATE,
        SHOP_ADD, SHOP_LIST, SHOP_COMPLETE, SHOP_DELETE, SHOP_CLEAR,
        NOTE_ADD, NOTE_LIST, NOTE_DELETE, NOTE_SEARCH, NOTE_EDIT, NOTE_APPEND,
        CAL_VIEW, CAL_ADD, CAL_DELETE, CAL_UPDATE, CAL_EMOJI_SET, CAL_REPEAT_FILTER,
        HABIT_LOG, HABIT_VIEW,
        REMINDER_ADD, REMINDER_LIST, REMINDER_DONE, REMINDER_DELETE,
        GIFT_ADD, GIFT_LIST, GIFT_DONE, GIFT_DELETE,
        MEMORY_ADD, MEMORY_VIEW, MEMORY_REMOVE,
        CONTACT_VIEW, CONTACT_ADD, CONTACT_UPDATE,
        MEAL_PLAN, MEAL_VIEW, MEAL_ADD, MEAL_RECIPE, MEAL_GENERATE,
        MEAL_IMPORT, MEAL_NUTRITION, MEAL_ADHERENCE, MEAL_EXPORT, MEAL_LEFTOVERS,
        WORKOUT_LOG, WORKOUT_VIEW, WORKOUT_ASK, WORKOUT_PLAN, WORKOUT_REBUILD,
        WORKOUT_TEMPLATE, WORKOUT_EXPORT, WORKOUT_BODY,
        JOURNAL_PROMPT, JOURNAL_VIEW, JOURNAL_SEARCH, JOURNAL_MONTH, JOURNAL_WINS,
        REPLY_ASSIST, EMAIL_ASSIST, REPLY_STYLE_ADD,
        MOOD_LOG, MOOD_VIEW, MOOD_DELETE,
        LINK_SAVE, LINK_VIEW, LINK_SEARCH, LINK_MARK_READ, LINK_SNOOZE,
        EXPORT_DATA,
        EXPENSE_ADD, EXPENSE_VIEW, EXPENSE_DELETE,
        SLEEP_LOG, SLEEP_VIEW,
        BRAINDUMP, UNDO,
        PROACTIVE_TOGGLE, VACATION_MODE, PACKING_OVERRIDE,
        GMAIL_SEND, GMAIL_DRAFT, GMAIL_UNREAD,
        BRIEFING, WEATHER, WEEKLY_SUMMARY,
        ASK, UNKNOWN,
    )

    from core.plugin_loader import dispatch_plugin_intent


    intent = intent_result.intent
    ents   = intent_result.entities

    try:
        # ── PLUGIN INTENTS (try plugins first for sports, betting, etc.) ────────
        if intent not in _CORE_INTENTS:
            handled = await _dispatch_plugin_with_ctx(
                intent_result, ctx, loaded_plugins
            )
            if handled:
                return

        # ─────────────────────────────────────────────────────────────────────
        # MIGRATED FEATURES — accept MarvinContext, work on all platforms
        # ─────────────────────────────────────────────────────────────────────

        # -- TODOS ------------------------------------------------------------
        if intent in (TODO_ADD, TODO_LIST, TODO_COMPLETE, TODO_DELETE, TODO_UPDATE):
            from features.todos import handle_todo_intent
            await handle_todo_intent(intent, ents, ctx)

        # -- NOTES ------------------------------------------------------------
        elif intent in (NOTE_ADD, NOTE_LIST, NOTE_DELETE, NOTE_SEARCH, NOTE_EDIT, NOTE_APPEND):
            from features.notes import handle_note_intent
            await handle_note_intent(intent, ents, ctx)

        # -- REMINDERS --------------------------------------------------------
        elif intent in (REMINDER_ADD, REMINDER_LIST, REMINDER_DONE, REMINDER_DELETE):
            from features.reminders import handle_reminder_intent
            await handle_reminder_intent(intent, ents, ctx)

        # -- SHOPPING ---------------------------------------------------------
        elif intent in (SHOP_ADD, SHOP_LIST, SHOP_COMPLETE, SHOP_DELETE, SHOP_CLEAR):
            from features.shopping import handle_shopping_intent
            await handle_shopping_intent(intent, ents, ctx)

        # -- CALENDAR ---------------------------------------------------------
        elif intent in (CAL_VIEW, CAL_ADD, CAL_DELETE, CAL_UPDATE, CAL_EMOJI_SET, CAL_REPEAT_FILTER):
            from features.calendar import handle_calendar_intent
            await handle_calendar_intent(intent, ents, ctx)

        # -- HABITS -----------------------------------------------------------
        elif intent in (HABIT_LOG, HABIT_VIEW):
            from features.habits import handle_habit_intent
            await handle_habit_intent(intent, ents, ctx)

        # -- GIFTS ------------------------------------------------------------
        elif intent in (GIFT_ADD, GIFT_LIST, GIFT_DONE, GIFT_DELETE):
            from features.gifts import handle_gift_intent
            await handle_gift_intent(intent, ents, ctx)

        # -- CONTACTS ---------------------------------------------------------
        elif intent in (CONTACT_VIEW, CONTACT_ADD, CONTACT_UPDATE):
            from features.contacts import handle_contact_intent
            await handle_contact_intent(intent, ents, ctx)

        # -- MOOD -------------------------------------------------------------
        elif intent in (MOOD_LOG, MOOD_VIEW, MOOD_DELETE):
            from features.mood import handle_mood_intent
            await handle_mood_intent(intent, ents, ctx)

        # -- LINKS (READ-LATER) -----------------------------------------------
        elif intent in (LINK_SAVE, LINK_VIEW, LINK_SEARCH, LINK_MARK_READ, LINK_SNOOZE):
            from features.links import handle_link_intent
            await handle_link_intent(intent, ents, ctx)

        # -- EXPORT -----------------------------------------------------------
        elif intent == EXPORT_DATA:
            from features.export_data import handle_export_intent
            await handle_export_intent(intent, ents, ctx)

        # -- BRIEFING ---------------------------------------------------------
        elif intent == BRIEFING:
            from features.briefing import send_briefing_ctx
            await send_briefing_ctx(ctx)

        # -- WEATHER ----------------------------------------------------------
        elif intent == WEATHER:
            from features.briefing import send_weather_ctx
            location = ents.get("location")
            await send_weather_ctx(ctx, location=location)

        # -- MEMORY -----------------------------------------------------------
        elif intent == MEMORY_ADD:
            cat  = ents.get("category", "")
            fact = ents.get("fact", "")
            if cat and fact:
                from core.data import add_memory_fact
                ok, err = add_memory_fact(cat, fact)
                if ok:
                    await ctx.reply_markdown(f"Remembered under *{cat}*: _{fact}_")
                else:
                    await ctx.reply(f"Couldn't save that: {err}")
            else:
                await ctx.reply(
                    "Use `/memory add [category] [fact]` to save a memory."
                )

        elif intent == MEMORY_REMOVE:
            await ctx.reply(
                "To remove a specific fact, use `/memory remove [category] [number]`."
            )

        elif intent == MEMORY_VIEW:
            if ctx.is_telegram and ctx._update is not None:
                ctx._context.args = [ents.get("category", "")] if ents.get("category") else []
                from features.memory import cmd_memory
                await cmd_memory(ctx._update, ctx._context)
            else:
                # Discord: plain-text memory dump
                cat = ents.get("category", "")
                from core.data import load_data
                data = load_data()
                memories = data.get("memories", {})
                if cat:
                    memories = {cat: memories.get(cat, [])}
                if not memories or not any(memories.values()):
                    await ctx.reply("No memories saved yet.")
                else:
                    lines = ["🧠 *Memories*\n"]
                    for category, facts in memories.items():
                        if facts:
                            lines.append(f"*{category}*")
                            for i, f in enumerate(facts, 1):
                                lines.append(f"  {i}. {f}")
                    await ctx.reply_markdown("\n".join(lines))

        # -- ASK / UNKNOWN ----------------------------------------------------
        elif intent in (ASK, UNKNOWN):
            from features.ask import handle_ask
            await handle_ask(ctx.text, ctx)

        # ── WEEKLY SUMMARY ────────────────────────────────────────────────────
        elif intent == WEEKLY_SUMMARY:
            from features.summary import send_weekly_summary
            await send_weekly_summary(ctx)

        # ── MEALS ─────────────────────────────────────────────────────────────
        elif intent in (MEAL_PLAN, MEAL_VIEW, MEAL_ADD, MEAL_RECIPE, MEAL_GENERATE,
                        MEAL_IMPORT, MEAL_NUTRITION, MEAL_ADHERENCE, MEAL_EXPORT, MEAL_LEFTOVERS):
            from features.meals import handle_meal_intent
            await handle_meal_intent(intent, ents, ctx)

        # ── WORKOUT ───────────────────────────────────────────────────────────
        elif intent in (WORKOUT_LOG, WORKOUT_VIEW, WORKOUT_ASK, WORKOUT_PLAN,
                        WORKOUT_REBUILD, WORKOUT_TEMPLATE, WORKOUT_EXPORT, WORKOUT_BODY):
            from features.workout import handle_workout_intent
            await handle_workout_intent(intent, ents, ctx)

        # ── JOURNAL ───────────────────────────────────────────────────────────
        elif intent in (JOURNAL_PROMPT, JOURNAL_VIEW, JOURNAL_SEARCH,
                        JOURNAL_MONTH, JOURNAL_WINS):
            from features.journal import handle_journal_intent
            await handle_journal_intent(intent, ents, ctx)

        # ── REPLY / EMAIL ASSIST ──────────────────────────────────────────────
        elif intent in (REPLY_ASSIST, EMAIL_ASSIST, REPLY_STYLE_ADD):
            from features.reply_assist import handle_reply_intent
            await handle_reply_intent(intent, ents, ctx)

        # ── UNDO ──────────────────────────────────────────────────────────────
        elif intent == UNDO:
            from features.undo import handle_undo_intent
            await handle_undo_intent(ctx)

        # ── BRAIN DUMP ────────────────────────────────────────────────────────
        elif intent == BRAINDUMP:
            from features.braindump import handle_braindump_intent
            await handle_braindump_intent(intent, ents, ctx)

        # ── EXPENSES ──────────────────────────────────────────────────────────
        elif intent in (EXPENSE_ADD, EXPENSE_VIEW, EXPENSE_DELETE):
            from features.expenses import handle_expense_intent
            await handle_expense_intent(intent, ents, ctx)

        # ── SLEEP ─────────────────────────────────────────────────────────────
        elif intent in (SLEEP_LOG, SLEEP_VIEW):
            from features.sleep import handle_sleep_intent
            await handle_sleep_intent(intent, ents, ctx)

        # ── PROACTIVE TOGGLE ──────────────────────────────────────────────────
        elif intent == PROACTIVE_TOGGLE:
            from features.proactive import handle_proactive_toggle
            await handle_proactive_toggle(intent, ents, ctx)

        # ── VACATION MODE ─────────────────────────────────────────────────────
        elif intent in (VACATION_MODE, PACKING_OVERRIDE):
            from features.vacation import handle_vacation_intent
            await handle_vacation_intent(intent, ents, ctx)

        # ── GMAIL ─────────────────────────────────────────────────────────────
        elif intent in (GMAIL_SEND, GMAIL_DRAFT, GMAIL_UNREAD):
            from features.gmail import handle_gmail_intent
            await handle_gmail_intent(intent, ents, ctx)

        # ── PLUGIN INTENTS (fallback) ─────────────────────────────────────────
        else:
            update  = ctx._update
            context = ctx._context
            if update is not None and context is not None:
                from telegram.constants import ParseMode
                handled = await dispatch_plugin_intent(
                    intent_result, update, context, loaded_plugins
                )
                if not handled:
                    await ctx.reply("I'm not sure how to handle that. Try `/help` to see what I can do.")
            else:
                await ctx.reply("I'm not sure how to handle that. Try `/help` to see what I can do.")

    except ImportError as e:
        logger.warning(f"marvin_dispatch: feature not yet built for intent '{intent}': {e}")
        await ctx.reply("That feature is coming soon. Try `/help` to see what's available.")

    except Exception as e:
        logger.error(
            f"marvin_dispatch: unhandled error for intent '{intent}': {e}\n"
            f"{traceback.format_exc()}"
        )
        await ctx.reply("Something went wrong. Try again, or use a specific command.")


# ═══════════════════════════════════════════════════════════════════════════════
# PLUGIN DISPATCH WITH CTX
# ═══════════════════════════════════════════════════════════════════════════════

async def _dispatch_plugin_with_ctx(
    intent_result,
    ctx: MarvinContext,
    plugins: list,
) -> bool:
    """
    Dispatch a plugin intent.

    Phase 4 transition: plugin handlers still use Telegram (update, context)
    for their command handlers, but the NL intent dispatch is routed here.

    On Telegram: uses ctx._update / ctx._context pass-through (unchanged behavior).
    On Discord: returns False for unmigrated plugins (handled by caller).

    Returns True if handled, False if no plugin claimed this intent.
    """
    intent = intent_result.intent

    for plugin in plugins:
        if intent in plugin.intents and plugin.intent_handler:
            try:
                # Phase 4: all plugin intent handlers accept ctx (MarvinContext).
                # Sports plugin migrated in Phase 4B. Future plugins should follow suit.
                await plugin.intent_handler(intent_result, ctx)
                return True
            except Exception as e:
                logger.error(
                    f"marvin_dispatch: plugin {plugin.name} handler error "
                    f"for '{intent}': {e}"
                )
                await ctx.reply(
                    f"Something went wrong with the {plugin.name} plugin. "
                    "Try again or use the command directly."
                )
                return True

    return False


# ═══════════════════════════════════════════════════════════════════════════════
# INTENT SETS
# ═══════════════════════════════════════════════════════════════════════════════

def _build_core_intents():
    """Build the set of all core (non-plugin) intent strings."""
    try:
        from core.intent import (
            TODO_ADD, TODO_LIST, TODO_COMPLETE, TODO_DELETE, TODO_UPDATE,
            SHOP_ADD, SHOP_LIST, SHOP_COMPLETE, SHOP_DELETE, SHOP_CLEAR,
            NOTE_ADD, NOTE_LIST, NOTE_DELETE, NOTE_SEARCH, NOTE_EDIT, NOTE_APPEND,
            CAL_VIEW, CAL_ADD, CAL_DELETE, CAL_UPDATE, CAL_EMOJI_SET, CAL_REPEAT_FILTER,
            HABIT_LOG, HABIT_VIEW,
            REMINDER_ADD, REMINDER_LIST, REMINDER_DONE, REMINDER_DELETE,
            GIFT_ADD, GIFT_LIST, GIFT_DONE, GIFT_DELETE,
            MEMORY_ADD, MEMORY_VIEW, MEMORY_REMOVE,
            CONTACT_VIEW, CONTACT_ADD, CONTACT_UPDATE,
            MEAL_PLAN, MEAL_VIEW, MEAL_ADD, MEAL_RECIPE, MEAL_GENERATE,
            MEAL_IMPORT, MEAL_NUTRITION, MEAL_ADHERENCE, MEAL_EXPORT, MEAL_LEFTOVERS,
            WORKOUT_LOG, WORKOUT_VIEW, WORKOUT_ASK, WORKOUT_PLAN, WORKOUT_REBUILD,
            WORKOUT_TEMPLATE, WORKOUT_EXPORT, WORKOUT_BODY,
            JOURNAL_PROMPT, JOURNAL_VIEW, JOURNAL_SEARCH, JOURNAL_MONTH, JOURNAL_WINS,
            REPLY_ASSIST, EMAIL_ASSIST, REPLY_STYLE_ADD,
            MOOD_LOG, MOOD_VIEW, MOOD_DELETE,
            LINK_SAVE, LINK_VIEW, LINK_SEARCH, LINK_MARK_READ, LINK_SNOOZE,
            EXPORT_DATA,
            EXPENSE_ADD, EXPENSE_VIEW, EXPENSE_DELETE,
            SLEEP_LOG, SLEEP_VIEW,
            BRAINDUMP, UNDO,
            PROACTIVE_TOGGLE, VACATION_MODE, PACKING_OVERRIDE,
            GMAIL_SEND, GMAIL_DRAFT, GMAIL_UNREAD,
            BRIEFING, WEATHER, WEEKLY_SUMMARY,
            ASK, UNKNOWN,
        )
        return {
            TODO_ADD, TODO_LIST, TODO_COMPLETE, TODO_DELETE, TODO_UPDATE,
            SHOP_ADD, SHOP_LIST, SHOP_COMPLETE, SHOP_DELETE, SHOP_CLEAR,
            NOTE_ADD, NOTE_LIST, NOTE_DELETE, NOTE_SEARCH, NOTE_EDIT, NOTE_APPEND,
            CAL_VIEW, CAL_ADD, CAL_DELETE, CAL_UPDATE, CAL_EMOJI_SET, CAL_REPEAT_FILTER,
            HABIT_LOG, HABIT_VIEW,
            REMINDER_ADD, REMINDER_LIST, REMINDER_DONE, REMINDER_DELETE,
            GIFT_ADD, GIFT_LIST, GIFT_DONE, GIFT_DELETE,
            MEMORY_ADD, MEMORY_VIEW, MEMORY_REMOVE,
            CONTACT_VIEW, CONTACT_ADD, CONTACT_UPDATE,
            MEAL_PLAN, MEAL_VIEW, MEAL_ADD, MEAL_RECIPE, MEAL_GENERATE,
            MEAL_IMPORT, MEAL_NUTRITION, MEAL_ADHERENCE, MEAL_EXPORT, MEAL_LEFTOVERS,
            WORKOUT_LOG, WORKOUT_VIEW, WORKOUT_ASK, WORKOUT_PLAN, WORKOUT_REBUILD,
            WORKOUT_TEMPLATE, WORKOUT_EXPORT, WORKOUT_BODY,
            JOURNAL_PROMPT, JOURNAL_VIEW, JOURNAL_SEARCH, JOURNAL_MONTH, JOURNAL_WINS,
            REPLY_ASSIST, EMAIL_ASSIST, REPLY_STYLE_ADD,
            MOOD_LOG, MOOD_VIEW, MOOD_DELETE,
            LINK_SAVE, LINK_VIEW, LINK_SEARCH, LINK_MARK_READ, LINK_SNOOZE,
            EXPORT_DATA,
            EXPENSE_ADD, EXPENSE_VIEW, EXPENSE_DELETE,
            SLEEP_LOG, SLEEP_VIEW,
            BRAINDUMP, UNDO,
            PROACTIVE_TOGGLE, VACATION_MODE, PACKING_OVERRIDE,
            GMAIL_SEND, GMAIL_DRAFT, GMAIL_UNREAD,
            BRIEFING, WEATHER, WEEKLY_SUMMARY,
            ASK, UNKNOWN,
        }
    except ImportError:
        return set()


# Intent sets — populated lazily
_CORE_INTENTS: set = set()  # populated on first import

# Intents that work on Discord (Phase 4)
# Expand this as more features are migrated to MarvinContext.
_DISCORD_SUPPORTED_INTENTS: set = set()  # all plugin intents + ASK/UNKNOWN once migrated


def _init_intent_sets():
    """Initialize intent sets. Called by discord_bot.py on startup."""
    global _CORE_INTENTS
    _CORE_INTENTS = _build_core_intents()


# Auto-init on import
try:
    _init_intent_sets()
except Exception:
    pass  # Graceful — will retry when first message is dispatched

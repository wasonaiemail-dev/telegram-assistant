"""
Intent dispatcher for sports plugin.

Routes detected intents to the appropriate command handler.
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes

from core.intent import IntentResult
from plugins.sports.commands import (
    cmd_scores,
    cmd_standings,
    cmd_schedule,
    cmd_sports,
    cmd_bets,
)
from plugins.sports import betting

logger = logging.getLogger(__name__)


async def handle_sports_intent(
    intent_result: IntentResult,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """
    Main intent dispatcher for sports plugin.

    Routes intents like "sports_scores" to the appropriate command handler.

    Args:
        intent_result: Intent classification from Layer 2 GPT
        update: Telegram Update object
        context: Telegram context
    """
    intent = intent_result.intent
    entities = intent_result.entities

    logger.debug(f"Sports intent dispatch: {intent} -> {entities}")

    if intent == "sports_scores":
        # Extract league and team from entities if available
        league = entities.get("league", "")
        team = entities.get("team", "")

        # Format as command and call handler
        text = f"/scores {league}".strip()
        if team:
            text += f" {team}"

        # Temporarily modify message to simulate command
        update.message.text = text
        await cmd_scores(update, context)

    elif intent == "sports_standings":
        league = entities.get("league", "")
        update.message.text = f"/standings {league}".strip()
        await cmd_standings(update, context)

    elif intent == "sports_schedule":
        league = entities.get("league", "")
        team = entities.get("team", "")
        text = f"/schedule {league}".strip()
        if team:
            text += f" {team}"
        update.message.text = text
        await cmd_schedule(update, context)

    elif intent == "sports_setup":
        update.message.text = "/sports setup"
        await cmd_sports(update, context)

    elif intent == "sports_alert_toggle":
        update.message.text = "/sports setup"
        await cmd_sports(update, context)

    elif intent == "sports_bet_add":
        # Log a bet from text description
        description = entities.get("bet_description", "")
        if description:
            update.message.text = f"/bets add {description}"
        else:
            update.message.text = "/bets add"
        await cmd_bets(update, context)

    elif intent == "sports_bet_view":
        # View recent bets and summary
        update.message.text = "/bets view"
        await cmd_bets(update, context)

    elif intent == "sports_bet_compare":
        # Show comparative stats
        update.message.text = "/bets stats"
        await cmd_bets(update, context)

    elif intent == "sports_bet_calculate":
        # Bet sizing / Kelly calculator
        await update.message.reply_text(
            "📊 <b>Bet Sizing Calculator</b>\n\n"
            "Available methods:\n"
            "• <b>Fixed Unit:</b> Bet a fixed multiple of your unit size\n"
            "• <b>Percentage:</b> Risk a percentage of bankroll\n"
            "• <b>Kelly Criterion:</b> Optimal sizing based on edge\n\n"
            "Use /bets chart or /bets stats for analysis.",
            parse_mode="HTML"
        )

    else:
        logger.warning(f"Unknown sports intent: {intent}")
        await update.message.reply_text(
            f"Unknown sports intent: {intent}\n"
            "Try /scores, /standings, /schedule, or /bets",
            parse_mode="HTML"
        )

"""
Intent dispatcher for sports plugin.

Routes detected intents to the appropriate handler.

NOTE: We call ESPN API directly here rather than delegating to cmd_*
functions, because cmd_* functions parse arguments from update.message.text
which is read-only in python-telegram-bot v22. Direct API calls are simpler
and more reliable for NL-triggered intents.
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes

from core.intent import IntentResult
from plugins.sports import espn_api
from plugins.sports import formatting
from plugins.sports import config as sports_config
from plugins.sports.commands import (
    cmd_scores,
    cmd_standings,
    cmd_schedule,
    cmd_sports,
    cmd_bets,
    _show_league_menu,
)

logger = logging.getLogger(__name__)


async def handle_sports_intent(
    intent_result: IntentResult,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """
    Main intent dispatcher for sports plugin.

    Routes NL intents to the ESPN API directly and sends formatted results.
    """
    intent = intent_result.intent
    entities = intent_result.entities

    logger.info(f"Sports dispatch: {intent} -> {entities}")

    try:
        if intent == "sports_scores":
            league = entities.get("league", "")
            if not league:
                await _show_league_menu(update, "scores")
                return
            league_slug = sports_config.normalize_league(league)
            if not league_slug:
                await _show_league_menu(update, "scores")
                return
            league_info = sports_config.get_league_info(league_slug)
            emoji = league_info.get("emoji", "🏆")
            scores = await espn_api.get_scores(league_slug)
            if not scores:
                await update.message.reply_text(
                    f"{emoji} <b>{league_info['name']} Scores</b>\n\nCould not fetch scores.",
                    parse_mode="HTML",
                )
                return
            games = scores.get("games", [])
            team = entities.get("team", "")
            if team:
                team_lower = team.lower()
                games = [
                    g for g in games
                    if team_lower in g["home_team"].lower() or team_lower in g["away_team"].lower()
                ]
            message = formatting.format_scoreboard(games, league_info["name"], emoji)
            await update.message.reply_text(message, parse_mode="HTML")

        elif intent == "sports_standings":
            league = entities.get("league", "")
            if not league:
                await _show_league_menu(update, "standings")
                return
            league_slug = sports_config.normalize_league(league)
            if not league_slug:
                await _show_league_menu(update, "standings")
                return
            league_info = sports_config.get_league_info(league_slug)
            emoji = league_info.get("emoji", "🏆")
            standings = await espn_api.get_standings(league_slug)
            if not standings or not standings.get("standings"):
                await update.message.reply_text(
                    f"{emoji} <b>{league_info['name']} Standings</b>\n\nNo data available.",
                    parse_mode="HTML",
                )
                return
            message = formatting.format_standings(
                standings["standings"], league_info["name"], emoji
            )
            await update.message.reply_text(message, parse_mode="HTML")

        elif intent == "sports_schedule":
            league = entities.get("league", "")
            if not league:
                await _show_league_menu(update, "schedule")
                return
            league_slug = sports_config.normalize_league(league)
            if not league_slug:
                await _show_league_menu(update, "schedule")
                return
            league_info = sports_config.get_league_info(league_slug)
            emoji = league_info.get("emoji", "🏆")
            schedule = await espn_api.get_schedule(league_slug)
            if not schedule or not schedule.get("games"):
                await update.message.reply_text(
                    f"{emoji} <b>{league_info['name']} Schedule</b>\n\nNo upcoming games.",
                    parse_mode="HTML",
                )
                return
            message = formatting.format_schedule(
                schedule["games"], league_info["name"], emoji
            )
            await update.message.reply_text(message, parse_mode="HTML")

        elif intent == "sports_setup":
            await _show_league_menu(update, "setup")

        elif intent == "sports_alert_toggle":
            await _show_league_menu(update, "setup")

        elif intent == "sports_bet_add":
            desc = entities.get("bet_description", intent_result.raw)
            from plugins.sports.betting import log_bet_from_text
            settings = sports_config.load_sports_settings()
            result = await log_bet_from_text(desc, settings)
            if result and result.get("success"):
                await update.message.reply_text(
                    f"✅ <b>Bet Logged</b>\n\n{result.get('summary', 'Bet recorded.')}",
                    parse_mode="HTML",
                )
            else:
                await update.message.reply_text(
                    "📝 To log a bet, try:\n"
                    "<code>/bets add $50 on Chiefs -3 at DraftKings</code>\n\n"
                    "Or send a screenshot of your bet slip.",
                    parse_mode="HTML",
                )

        elif intent == "sports_bet_view":
            view = entities.get("view", "")
            if view == "stats":
                from plugins.sports.data import load_bet_history
                from plugins.sports.betting import calculate_stats
                bets = load_bet_history()
                if not bets:
                    await update.message.reply_text("No bets tracked yet. Use /bets add to log one.")
                    return
                stats = calculate_stats(bets)
                msg = (
                    f"📊 <b>Betting Stats</b>\n\n"
                    f"Total bets: {stats.get('total_bets', 0)}\n"
                    f"Record: {stats.get('wins', 0)}-{stats.get('losses', 0)}\n"
                    f"Win rate: {stats.get('win_rate', 0):.1%}\n"
                    f"Net P&L: ${stats.get('net_pnl', 0):+.2f}\n"
                    f"ROI: {stats.get('roi', 0):+.1%}"
                )
                await update.message.reply_text(msg, parse_mode="HTML")
            else:
                from plugins.sports.data import load_bet_history
                bets = load_bet_history()
                if not bets:
                    await update.message.reply_text(
                        "No bets tracked yet.\n\nUse /bets add or send a bet slip screenshot."
                    )
                else:
                    recent = bets[-5:]
                    lines = ["📋 <b>Recent Bets</b>\n"]
                    for b in reversed(recent):
                        result = b.get("result", "pending")
                        icon = {"won": "✅", "lost": "❌", "push": "↩️"}.get(result, "⏳")
                        lines.append(
                            f"{icon} {b.get('pick', 'Unknown')} @ {b.get('odds', '')}"
                            f" — ${b.get('stake', 0)}"
                        )
                    await update.message.reply_text("\n".join(lines), parse_mode="HTML")

        elif intent == "sports_bet_compare":
            await update.message.reply_text(
                "📸 Send a screenshot of sportsbook odds and I'll compare lines across books.\n\n"
                "Supported: DraftKings, FanDuel, BetMGM, Caesars, ESPN Bet, Fanatics, Bovada, MyBookie",
                parse_mode="HTML",
            )

        elif intent == "sports_bet_calculate":
            await update.message.reply_text(
                "📊 <b>Bet Sizing Calculator</b>\n\n"
                "Use /bets bankroll to set your unit size, then:\n"
                "• <b>Fixed Unit:</b> Bet a set multiple of your unit\n"
                "• <b>Percentage:</b> Risk a % of bankroll\n"
                "• <b>Kelly Criterion:</b> Optimal sizing based on edge\n\n"
                "Use /bets stats for full analysis.",
                parse_mode="HTML",
            )

        else:
            logger.warning(f"Unknown sports intent: {intent}")
            await update.message.reply_text(
                "Try /scores, /standings, /schedule, or /bets",
                parse_mode="HTML",
            )

    except Exception as e:
        logger.error(f"Sports dispatch error for {intent}: {e}", exc_info=True)
        await update.message.reply_text(
            "Something went wrong. Try the command directly:\n"
            "/scores, /standings, /schedule, or /bets",
            parse_mode="HTML",
        )

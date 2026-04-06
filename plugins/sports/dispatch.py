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
from plugins.sports import stats_api
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

# Words to strip when extracting player/team names from NL queries
_STOP_WORDS = {
    "what", "whats", "what's", "show", "get", "me", "the", "are", "is",
    "how", "how's", "hows", "doing", "playing", "performing", "did",
    "stats", "stat", "statistics", "averages", "average", "numbers",
    "for", "of", "on", "about", "a", "an", "his", "her", "their",
    "game", "log", "gamelog", "recent", "games", "last", "roster",
    "team", "record", "please", "can", "you", "tell", "give", "look",
    "up", "check", "find", "search", "player", "players",
    "this", "that", "season", "year", "today", "tonight", "currently",
    "current", "right", "now", "so", "far", "in", "at", "with", "been",
    "has", "have", "had", "do", "does", "not", "just", "like",
}


def _extract_name_from_query(query: str) -> str:
    """
    Extract a likely player or team name from a natural language query.

    Examples:
      "what are LeBron's stats" -> "LeBron"
      "show me stats for Patrick Mahomes" -> "Patrick Mahomes"
      "how is Ohtani doing" -> "Ohtani"
    """
    # Remove possessives
    cleaned = query.replace("'s", "").replace("'s", "")
    words = cleaned.split()
    # Filter out stop words, keeping capitalized words and unknown words
    name_parts = []
    for w in words:
        w_lower = w.lower().strip("?!.,")
        if w_lower in _STOP_WORDS:
            continue
        if w_lower.isdigit():
            continue
        name_parts.append(w.strip("?!.,"))
    return " ".join(name_parts).strip()


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

        elif intent == "sports_player_stats":
            query = entities.get("query", intent_result.raw)
            # Extract a likely player name from the query
            player_name = _extract_name_from_query(query)
            if not player_name:
                await update.message.reply_text(
                    "Who would you like stats for? Try: <code>LeBron stats</code>",
                    parse_mode="HTML",
                )
                return
            await update.message.reply_text(f"🔍 Looking up {player_name}...")
            results = await stats_api.search_player(player_name)
            if not results:
                await update.message.reply_text(
                    f"❌ No players found matching: <b>{player_name}</b>",
                    parse_mode="HTML",
                )
                return
            if len(results) == 1:
                player = results[0]
                league_raw = player.get("league") or ""
                from plugins.sports.commands import _map_league_name_to_slug
                league_slug = _map_league_name_to_slug(league_raw) if league_raw else None
                if not league_slug:
                    sport_val = (player.get("sport") or "").lower()
                    if "football" in sport_val:
                        league_slug = "nfl"
                    elif "baseball" in sport_val:
                        league_slug = "mlb"
                    elif "hockey" in sport_val:
                        league_slug = "nhl"
                    else:
                        league_slug = "nba"
                league_info = sports_config.get_league_info(league_slug)
                sport = league_info["sport"] if league_info else "basketball"
                league = league_info["league"] if league_info else "nba"
                player_stats = await stats_api.get_player_stats(
                    player["id"], sport, league,
                    player_name=player.get("name", player_name),
                )
                if player_stats:
                    msg = formatting.format_player_stats(player_stats)
                    await update.message.reply_text(msg, parse_mode="HTML")
                else:
                    await update.message.reply_text(
                        f"❌ Could not fetch stats for {player.get('name', player_name)}",
                        parse_mode="HTML",
                    )
            else:
                msg = formatting.format_player_search_results(results[:5])
                await update.message.reply_text(msg, parse_mode="HTML")

        elif intent == "sports_player_gamelog":
            query = entities.get("query", intent_result.raw)
            player_name = _extract_name_from_query(query)
            if not player_name:
                await update.message.reply_text(
                    "Whose game log? Try: <code>LeBron game log</code>",
                    parse_mode="HTML",
                )
                return
            await update.message.reply_text(f"🔍 Looking up {player_name}...")
            results = await stats_api.search_player(player_name)
            if not results:
                await update.message.reply_text(
                    f"❌ No players found matching: <b>{player_name}</b>",
                    parse_mode="HTML",
                )
                return
            player = results[0]
            league_raw = player.get("league") or ""
            league_slug = _map_league_name_to_slug(league_raw) if league_raw else None
            if not league_slug:
                sport_val = (player.get("sport") or "").lower()
                if "football" in sport_val:
                    league_slug = "nfl"
                elif "baseball" in sport_val:
                    league_slug = "mlb"
                elif "hockey" in sport_val:
                    league_slug = "nhl"
                else:
                    league_slug = "nba"
            league_info = sports_config.get_league_info(league_slug)
            sport = league_info["sport"] if league_info else "basketball"
            league = league_info["league"] if league_info else "nba"
            gamelog = await stats_api.get_player_gamelog(
                player["id"], sport, league,
                player_name=player.get("name", player_name),
            )
            if gamelog:
                msg = formatting.format_player_gamelog(gamelog)
                await update.message.reply_text(msg, parse_mode="HTML")
            else:
                await update.message.reply_text(
                    f"❌ Could not fetch game log for {player.get('name', player_name)}",
                    parse_mode="HTML",
                )

        elif intent == "sports_leaders":
            query = entities.get("query", intent_result.raw)
            # Try to extract league from query
            league = entities.get("league", "")
            if not league:
                # Attempt to find league name in query
                query_lower = query.lower()
                league_keywords = {
                    "nba": "nba", "basketball": "nba",
                    "nfl": "nfl", "football": "nfl",
                    "mlb": "mlb", "baseball": "mlb",
                    "nhl": "nhl", "hockey": "nhl",
                    "epl": "epl", "premier league": "epl",
                    "mls": "mls", "soccer": "epl",
                    "bundesliga": "bundesliga", "la liga": "laliga",
                }
                for keyword, slug in league_keywords.items():
                    if keyword in query_lower:
                        league = slug
                        break

            if not league:
                await _show_league_menu(update, "leaders")
                return

            league_slug = sports_config.normalize_league(league)
            if not league_slug:
                await _show_league_menu(update, "leaders")
                return

            league_info = sports_config.get_league_info(league_slug)
            emoji = league_info.get("emoji", "🏆")
            await update.message.reply_text(f"🔍 Fetching {league_info['name']} leaders...")
            leaders = await stats_api.get_league_leaders(league_slug)
            if leaders:
                msg = formatting.format_leaders(leaders, emoji)
                await update.message.reply_text(msg, parse_mode="HTML")
            else:
                await update.message.reply_text(
                    f"❌ Could not fetch leaders for {league_info['name']}",
                    parse_mode="HTML",
                )

        elif intent == "sports_compare":
            query = entities.get("query", intent_result.raw)
            await update.message.reply_text(
                "For player comparison, use:\n"
                "<code>/compare Player1 vs Player2</code>\n\n"
                "Example: <code>/compare LeBron James vs Kevin Durant</code>",
                parse_mode="HTML",
            )

        elif intent == "sports_team_stats":
            query = entities.get("query", intent_result.raw)
            await update.message.reply_text(
                "For team stats, use: <code>/stats team nba lakers</code>\n"
                "Specify the league and team name.",
                parse_mode="HTML",
            )

        elif intent == "sports_roster":
            query = entities.get("query", intent_result.raw)
            await update.message.reply_text(
                "For a roster, use: <code>/stats roster nba lakers</code>\n"
                "Specify the league and team name.",
                parse_mode="HTML",
            )

        else:
            logger.warning(f"Unknown sports intent: {intent}")
            await update.message.reply_text(
                "Try /scores, /standings, /schedule, /stats, or /bets",
                parse_mode="HTML",
            )

    except Exception as e:
        logger.error(f"Sports dispatch error for {intent}: {e}", exc_info=True)
        await update.message.reply_text(
            "Something went wrong. Try the command directly:\n"
            "/scores, /standings, /schedule, or /bets",
            parse_mode="HTML",
        )

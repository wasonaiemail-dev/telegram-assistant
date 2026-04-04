"""
Background jobs for sports plugin.

Scheduled tasks for game alerts and score updates.
"""

import logging
from datetime import datetime, timedelta
from telegram.ext import ContextTypes

from core.config import ALLOWED_USER_ID
from plugins.sports import config as sports_config
from plugins.sports import espn_api
from plugins.sports import formatting

logger = logging.getLogger(__name__)


async def job_score_updates(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Periodic job to check for score updates on favorite teams.

    Runs every 30 minutes during game days.
    Sends notifications when games end.

    Called by job_queue.run_repeating() in plugin loader.
    """
    settings = sports_config.load_sports_settings()

    # Check if alerts enabled
    if not settings.get("alerts_enabled", True):
        return

    fav_teams = settings.get("favorite_teams", [])
    if not fav_teams:
        return

    try:
        # Group favorite teams by league
        leagues = {}
        for team in fav_teams:
            league = team.get("league", "")
            if league not in leagues:
                leagues[league] = []
            leagues[league].append(team)

        # Check each league for updates
        for league_slug, teams in leagues.items():
            scores = await espn_api.get_scores(league_slug)
            if not scores:
                continue

            league_info = sports_config.get_league_info(league_slug)
            emoji = league_info.get("emoji", "🏆") if league_info else "🏆"

            # Check for games involving favorite teams
            games = scores.get("games", [])
            for game in games:
                home = game.get("home_team", "").lower()
                away = game.get("away_team", "").lower()
                status = game.get("status", "")

                for team in teams:
                    team_name = team.get("team_name", "").lower()

                    if team_name in home or team_name in away:
                        # Check if game just finished
                        if "Final" in status and "Final" not in (context.bot_data.get("last_status", {}).get(game.get("id"), "")):
                            # Send notification
                            message = formatting.format_game_preview(game, emoji)
                            try:
                                await context.bot.send_message(
                                    chat_id=ALLOWED_USER_ID,
                                    text=message,
                                    parse_mode="HTML"
                                )
                            except Exception as e:
                                logger.error(f"Failed to send score update: {e}")

                            # Store status
                            if "last_status" not in context.bot_data:
                                context.bot_data["last_status"] = {}
                            context.bot_data["last_status"][game.get("id")] = status

    except Exception as e:
        logger.error(f"job_score_updates error: {e}")


async def job_game_alerts(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Daily job to alert user about upcoming games for favorite teams.

    Runs once per day at 9 AM (configurable).
    Shows games happening within the next 48 hours.

    Called by job_queue.run_daily() in plugin loader.
    """
    settings = sports_config.load_sports_settings()

    # Check if alerts enabled
    if not settings.get("alerts_enabled", True):
        return

    fav_teams = settings.get("favorite_teams", [])
    if not fav_teams:
        return

    try:
        # Group favorite teams by league
        leagues = {}
        for team in fav_teams:
            league = team.get("league", "")
            if league not in leagues:
                leagues[league] = []
            leagues[league].append(team)

        today = datetime.utcnow()
        tomorrow = today + timedelta(days=2)

        upcoming_games = []

        # Check each league for upcoming games
        for league_slug, teams in leagues.items():
            schedule = await espn_api.get_schedule(league_slug, days=2)
            if not schedule:
                continue

            games = schedule.get("games", [])
            league_info = sports_config.get_league_info(league_slug)
            league_name = league_info.get("name", league_slug) if league_info else league_slug

            for game in games:
                try:
                    game_date = datetime.fromisoformat(game.get("date", "").replace("Z", "+00:00"))
                except:
                    continue

                # Filter to next 48 hours
                if game_date < today or game_date > tomorrow:
                    continue

                home = game.get("home_team", "").lower()
                away = game.get("away_team", "").lower()

                for team in teams:
                    team_name = team.get("team_name", "").lower()

                    if team_name in home or team_name in away:
                        upcoming_games.append({
                            "league": league_name,
                            "game": game,
                            "team": team.get("team_name", ""),
                        })
                        break  # Only count each game once

        # Send alert if there are games
        if upcoming_games:
            message = "<b>🏆 Upcoming Games Alert</b>\n\n"
            for item in upcoming_games:
                league = item["league"]
                team = item["team"]
                game = item["game"]

                away = game.get("away_team", "")
                home = game.get("home_team", "")
                date_str = game.get("date", "")

                try:
                    dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    time_str = dt.strftime("%a, %b %d at %I:%M %p")
                except:
                    time_str = date_str[:10]

                message += f"<b>{league}</b> — {team}\n"
                message += f"{away} @ {home}\n"
                message += f"{time_str}\n\n"

            try:
                await context.bot.send_message(
                    chat_id=ALLOWED_USER_ID,
                    text=message,
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Failed to send game alert: {e}")

    except Exception as e:
        logger.error(f"job_game_alerts error: {e}")

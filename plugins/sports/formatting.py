"""
Formatting utilities for sports data to Telegram HTML messages.
"""

import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


def format_scoreboard(games: List[Dict[str, Any]], league: str, emoji: str = "🏆") -> str:
    """
    Format a list of games into a Telegram HTML message.

    Args:
        games: List of game dicts from get_scores()
        league: League name
        emoji: League emoji

    Returns:
        Formatted HTML string
    """
    if not games:
        return f"<b>{emoji} {league}</b>\n\nNo games found."

    lines = [f"<b>{emoji} {league}</b>"]
    lines.append("")

    for game in games:
        home = game.get("home_team", "Unknown")
        away = game.get("away_team", "Unknown")
        home_score = game.get("home_score", "-")
        away_score = game.get("away_score", "-")
        status = game.get("status", "Scheduled")

        # Format score line
        if home_score != "" and away_score != "":
            score_line = f"<code>{away:20} {away_score:3}</code>\n<code>{home:20} {home_score:3}</code>"
        else:
            score_line = f"{away} @ {home}"

        # Status indicator
        status_symbol = "🔴" if "Live" in status else "✓" if "Final" in status else "⏱"

        lines.append(f"{status_symbol} {status}")
        lines.append(score_line)
        lines.append("")

    return "\n".join(lines)


def format_standings(
    standings: List[Dict[str, Any]],
    league: str,
    emoji: str = "🏆",
) -> str:
    """
    Format standings into a Telegram HTML message.

    Args:
        standings: List of division dicts from get_standings()
        league: League name
        emoji: League emoji

    Returns:
        Formatted HTML string
    """
    if not standings:
        return f"<b>{emoji} {league} Standings</b>\n\nNo data available."

    lines = [f"<b>{emoji} {league} Standings</b>"]
    lines.append("")

    for division in standings:
        div_name = division.get("division", "Standings")
        lines.append(f"<u>{div_name}</u>")
        lines.append("")

        teams = division.get("teams", [])
        for idx, team in enumerate(teams, 1):
            name = team.get("name", "Unknown")
            wins = team.get("wins", "0")
            losses = team.get("losses", "0")
            pct = team.get("win_pct", ".000")
            gb = team.get("games_behind", "-")

            # Truncate name if too long
            if len(name) > 15:
                name = name[:12] + "..."

            line = f"{idx:2}. {name:15} {wins:2}W-{losses:2}L ({pct}) [{gb:>4} GB]"
            lines.append(f"<code>{line}</code>")

        lines.append("")

    return "\n".join(lines)


def format_schedule(
    games: List[Dict[str, Any]],
    league: str,
    emoji: str = "🏆",
    team: str = "",
) -> str:
    """
    Format upcoming schedule into a Telegram HTML message.

    Args:
        games: List of game dicts from get_schedule()
        league: League name
        emoji: League emoji
        team: Optional team name filter

    Returns:
        Formatted HTML string
    """
    if not games:
        filter_text = f" ({team})" if team else ""
        return f"<b>{emoji} {league} Schedule{filter_text}</b>\n\nNo upcoming games."

    lines = [f"<b>{emoji} {league} Schedule</b>"]
    if team:
        lines.append(f"<i>Games involving {team}</i>")
    lines.append("")

    for game in games:
        date_str = game.get("date", "")
        if date_str:
            # Parse ISO date and format nicely
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                formatted_date = dt.strftime("%a, %b %d %I:%M %p")
            except:
                formatted_date = date_str[:10]
        else:
            formatted_date = "TBD"

        away = game.get("away_team", "Unknown")
        home = game.get("home_team", "Unknown")
        status = game.get("status", "Scheduled")

        # Truncate team names if needed
        if len(away) > 15:
            away = away[:12] + "."
        if len(home) > 15:
            home = home[:12] + "."

        lines.append(f"<b>{formatted_date}</b>")
        lines.append(f"{away} @ {home}")
        lines.append(f"<i>{status}</i>")
        lines.append("")

    return "\n".join(lines)


def format_game_preview(game: Dict[str, Any], league_emoji: str = "🏆") -> str:
    """
    Format a single game into a detailed preview.

    Args:
        game: Game dict from get_scores() or get_schedule()
        league_emoji: League emoji

    Returns:
        Formatted HTML string
    """
    lines = [f"{league_emoji} <b>Game Preview</b>"]
    lines.append("")

    away = game.get("away_team", "Unknown")
    home = game.get("home_team", "Unknown")
    date_str = game.get("date", "TBD")
    status = game.get("status", "Scheduled")
    venue = game.get("venue", "")

    lines.append(f"<b>{away}</b> @ <b>{home}</b>")
    lines.append(f"<i>{date_str}</i>")
    lines.append("")
    lines.append(f"Status: {status}")
    if venue:
        lines.append(f"Venue: {venue}")
    lines.append("")

    away_score = game.get("away_score", "")
    home_score = game.get("home_score", "")
    if away_score and home_score:
        lines.append(f"<code>{away:20} {away_score:3}</code>")
        lines.append(f"<code>{home:20} {home_score:3}</code>")

    return "\n".join(lines)


def format_error(error_msg: str, league: str = "") -> str:
    """Format an error message."""
    if league:
        return f"❌ Could not fetch data for <b>{league}</b>.\n\n{error_msg}"
    return f"❌ Error: {error_msg}"

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
        raw_status = game.get("status", "Scheduled")

        # Map ESPN status codes to friendly display text
        status_map = {
            "STATUS_SCHEDULED": "Scheduled",
            "STATUS_IN_PROGRESS": "Live",
            "STATUS_HALFTIME": "Halftime",
            "STATUS_FINAL": "Final",
            "STATUS_FINAL_OVERTIME": "Final (OT)",
            "STATUS_POSTPONED": "Postponed",
            "STATUS_CANCELED": "Canceled",
            "STATUS_DELAYED": "Delayed",
            "STATUS_END_PERIOD": "End of Period",
        }
        status = status_map.get(raw_status, raw_status.replace("STATUS_", "").replace("_", " ").title())

        # Status indicator emoji
        if "Live" in status or "Progress" in status or "Halftime" in status:
            status_symbol = "🔴"
        elif "Final" in status:
            status_symbol = "✅"
        elif "Postponed" in status or "Canceled" in status or "Delayed" in status:
            status_symbol = "⚠️"
        else:
            status_symbol = "🕐"

        # Format based on game state
        if status in ("Final", "Final (OT)") or "Live" in status or "Halftime" in status:
            # Show scores
            score_line = (
                f"<code>{away:20} {away_score:>3}</code>\n"
                f"<code>{home:20} {home_score:>3}</code>"
            )
        elif home_score and away_score and home_score != "0" and away_score != "0":
            score_line = (
                f"<code>{away:20} {away_score:>3}</code>\n"
                f"<code>{home:20} {home_score:>3}</code>"
            )
        else:
            # Scheduled game — show matchup and time
            date_str = game.get("date", "")
            time_str = ""
            if date_str:
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    time_str = dt.strftime("%I:%M %p ET")
                except Exception:
                    pass
            score_line = f"{away} @ {home}"
            if time_str:
                score_line += f"  ({time_str})"

        lines.append(f"{status_symbol} <b>{status}</b>")
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
        raw_status = game.get("status", "Scheduled")

        # Map ESPN status codes to friendly display text
        status_map = {
            "STATUS_SCHEDULED": "Scheduled",
            "STATUS_IN_PROGRESS": "Live",
            "STATUS_HALFTIME": "Halftime",
            "STATUS_FINAL": "Final",
            "STATUS_FINAL_OVERTIME": "Final (OT)",
            "STATUS_POSTPONED": "Postponed",
            "STATUS_CANCELED": "Canceled",
            "STATUS_DELAYED": "Delayed",
        }
        status = status_map.get(raw_status, raw_status.replace("STATUS_", "").replace("_", " ").title())

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

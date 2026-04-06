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


def format_player_stats(player_data: Dict[str, Any]) -> str:
    """Format player stats into Telegram HTML message."""
    if not player_data:
        return "❌ Could not load player stats."

    lines = ["📊 <b>Player Stats</b>", ""]

    # Player header info
    name = player_data.get("name", "Unknown")
    team = player_data.get("team", "")
    position = player_data.get("position", "")
    jersey = player_data.get("jersey", "")

    lines.append(f"<b>{name}</b>")
    if team:
        lines.append(f"<i>{team}</i>")
    if position or jersey:
        info_parts = []
        if position:
            info_parts.append(position)
        if jersey:
            info_parts.append(f"#{jersey}")
        lines.append(f"<i>{' | '.join(info_parts)}</i>")
    lines.append("")

    # Stats by category
    stats = player_data.get("stats", {})
    if stats:
        for category, stat_list in stats.items():
            lines.append(f"<b>{category}</b>")
            if isinstance(stat_list, list):
                for stat in stat_list:
                    stat_name = stat.get("displayName") or stat.get("name", "")
                    stat_value = stat.get("value", "-")
                    if stat_name:
                        lines.append(f"  <code>{stat_name:25} {stat_value:>10}</code>")
            lines.append("")

    return "\n".join(lines)


def format_player_gamelog(gamelog_data: Dict[str, Any], limit: int = 5) -> str:
    """Format recent game log into Telegram HTML message.

    v3 format: each game has stats dict keyed by label (MIN, PTS, REB, etc.)
    """
    if not gamelog_data:
        return "❌ Could not load game log."

    lines = ["📈 <b>Recent Games</b>", ""]

    # Player header
    name = gamelog_data.get("name", "Unknown")
    team = gamelog_data.get("team", "")

    lines.append(f"<b>{name}</b>")
    if team:
        lines.append(f"<i>{team}</i>")
    lines.append("")

    # Key stat labels to show (in order)
    KEY_LABELS = ["PTS", "REB", "AST", "STL", "BLK", "FG", "3PT", "MIN"]

    # Game entries
    games = gamelog_data.get("games", [])
    for game in games[:limit]:
        try:
            date_str = game.get("date", "")
            opponent = game.get("opponent", "Unknown")
            at_vs = game.get("at_vs", "vs")
            result = game.get("result", "")
            score = game.get("score", "")
            game_stats = game.get("stats", {})

            # Parse date if ISO format
            if date_str:
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    formatted_date = dt.strftime("%m/%d")
                except Exception:
                    formatted_date = date_str[:10]
            else:
                formatted_date = "TBD"

            # Result + score line
            result_str = f" ({result} {score})" if result and score else ""
            lines.append(f"<b>{formatted_date}</b> {at_vs} {opponent}{result_str}")

            # Show key stats
            if game_stats:
                stat_items = []
                for label in KEY_LABELS:
                    val = game_stats.get(label, "")
                    if val and str(val) != "0":
                        stat_items.append(f"{label}: {val}")
                if stat_items:
                    lines.append(f"  <code>{' | '.join(stat_items)}</code>")
            lines.append("")
        except Exception:
            continue

    return "\n".join(lines)


def format_team_stats(team_data: Dict[str, Any]) -> str:
    """Format team stats into Telegram HTML message."""
    if not team_data:
        return "❌ Could not load team stats."

    lines = ["🏆 <b>Team Stats</b>", ""]

    # Team header
    name = team_data.get("name", "Unknown")
    abbrev = team_data.get("abbreviation", "")

    lines.append(f"<b>{name}</b>")
    if abbrev:
        lines.append(f"<i>{abbrev}</i>")

    # Record / standing info
    record_summary = team_data.get("record_summary", "")
    standing_summary = team_data.get("standing_summary", "")
    if record_summary:
        lines.append(f"<b>Record:</b> {record_summary}")
    if standing_summary:
        lines.append(f"<b>Standing:</b> {standing_summary}")
    lines.append("")

    # Key stats to highlight (abbreviation -> display priority)
    # Show the most useful per-game stats, skip raw totals
    KEY_STATS = {
        "avgPoints", "avgRebounds", "avgAssists", "avgSteals", "avgBlocks",
        "avgTurnovers", "avgFouls", "fieldGoalPct", "threePointPct",
        "freeThrowPct", "avgOffensiveRebounds", "avgDefensiveRebounds",
        "assistTurnoverRatio", "twoPointFieldGoalPct",
        "avgFieldGoalsMade", "avgFieldGoalsAttempted",
        "avgThreePointFieldGoalsMade", "avgThreePointFieldGoalsAttempted",
        "avgFreeThrowsMade", "avgFreeThrowsAttempted",
        "gamesPlayed",
    }

    # Stats by category
    stats = team_data.get("stats", {})
    if stats:
        for category, stat_list in stats.items():
            category_display = category.replace("general", "General").replace("offensive", "Offensive").replace("defensive", "Defensive")
            if category_display[0].islower():
                category_display = category_display.capitalize()
            lines.append(f"<b>{category_display}</b>")
            if isinstance(stat_list, list):
                shown = 0
                for stat in stat_list:
                    stat_name_key = stat.get("name", "")
                    # Filter to key stats only
                    if stat_name_key not in KEY_STATS:
                        continue
                    display_name = stat.get("displayName") or stat_name_key
                    stat_value = stat.get("displayValue") or stat.get("value", "-")
                    rank = stat.get("rank", "")

                    if display_name:
                        rank_str = f" (#{rank})" if rank else ""
                        lines.append(f"  <code>{display_name:28} {str(stat_value):>8}{rank_str}</code>")
                        shown += 1
                if shown == 0:
                    # Show first 6 if no key stats matched
                    for stat in stat_list[:6]:
                        display_name = stat.get("displayName") or stat.get("name", "")
                        stat_value = stat.get("displayValue") or stat.get("value", "-")
                        if display_name:
                            lines.append(f"  <code>{display_name:28} {str(stat_value):>8}</code>")
            lines.append("")

    return "\n".join(lines)


def format_leaders(leaders_data: Dict[str, Any], emoji: str = "🏆") -> str:
    """Format league leaders into Telegram HTML message."""
    if not leaders_data:
        return "❌ Could not load league leaders."

    league_name = leaders_data.get("league_name", "League")
    categories = leaders_data.get("categories", [])

    lines = [f"<b>{emoji} {league_name} Leaders</b>", ""]

    for cat in categories:
        cat_name = cat.get("name", "")
        cat_emoji = cat.get("emoji", "🏆")
        leaders = cat.get("leaders", [])

        if not leaders:
            continue

        lines.append(f"<b>{cat_emoji} {cat_name}</b>")

        for idx, leader in enumerate(leaders[:10], 1):
            name = leader.get("name", "Unknown")
            team = leader.get("team", "")
            value = leader.get("value", "")

            team_str = f" ({team})" if team else ""
            lines.append(f"<code>{idx:2}. {name:20}{team_str:10} {value:>6}</code>")

        lines.append("")

    return "\n".join(lines)


def format_player_comparison(
    player1: Dict[str, Any],
    player2: Dict[str, Any],
) -> str:
    """
    Format side-by-side player comparison into Telegram HTML message.

    Both player dicts should have 'name', 'team', 'stats' keys
    where stats is a dict of {category: [{name, displayName, value}]}.
    """
    if not player1 or not player2:
        return "❌ Could not load player comparison."

    name1 = player1.get("name", "Player 1")
    name2 = player2.get("name", "Player 2")
    team1 = player1.get("team", "")
    team2 = player2.get("team", "")

    lines = ["<b>⚔️ Player Comparison</b>", ""]
    lines.append(f"<b>{name1}</b>" + (f" ({team1})" if team1 else ""))
    lines.append(f"  vs")
    lines.append(f"<b>{name2}</b>" + (f" ({team2})" if team2 else ""))
    lines.append("")

    # Collect all stats from both players into a flat dict for comparison
    stats1 = _flatten_stats(player1.get("stats", {}))
    stats2 = _flatten_stats(player2.get("stats", {}))

    # Find common stat names (match by abbreviation/name)
    all_keys = []
    seen = set()
    for key in list(stats1.keys()) + list(stats2.keys()):
        if key not in seen:
            all_keys.append(key)
            seen.add(key)

    if not all_keys:
        lines.append("<i>No comparable stats found.</i>")
        return "\n".join(lines)

    # Build comparison table
    # Header
    short1 = name1.split()[-1][:8] if name1 else "P1"
    short2 = name2.split()[-1][:8] if name2 else "P2"
    lines.append(f"<code>{'Stat':18} {short1:>8}  {short2:>8}</code>")
    lines.append(f"<code>{'─' * 38}</code>")

    for key in all_keys[:20]:  # Limit to 20 stats
        val1 = stats1.get(key, "-")
        val2 = stats2.get(key, "-")
        display = key

        # Highlight the better value
        try:
            v1_float = float(val1.replace("%", "").replace(",", ""))
            v2_float = float(val2.replace("%", "").replace(",", ""))
            if v1_float > v2_float:
                val1_str = f"✓{val1}"
                val2_str = f" {val2}"
            elif v2_float > v1_float:
                val1_str = f" {val1}"
                val2_str = f"✓{val2}"
            else:
                val1_str = f" {val1}"
                val2_str = f" {val2}"
        except (ValueError, AttributeError):
            val1_str = f" {val1}"
            val2_str = f" {val2}"

        lines.append(f"<code>{display:18} {val1_str:>8}  {val2_str:>8}</code>")

    lines.append("")
    return "\n".join(lines)


def _flatten_stats(stats: Dict) -> Dict[str, str]:
    """Flatten nested stats categories into a single {name: value} dict."""
    flat = {}
    if isinstance(stats, dict):
        for category, stat_list in stats.items():
            if isinstance(stat_list, list):
                for stat in stat_list:
                    key = stat.get("name", "") or stat.get("displayName", "")
                    value = stat.get("value", "-")
                    if key:
                        flat[key] = str(value)
    return flat


def format_player_search_results(results: list) -> str:
    """Format player search results for selection."""
    if not results:
        return "❌ No players found."

    lines = ["<b>🔍 Player Search Results</b>", ""]

    for idx, player in enumerate(results, 1):
        name = player.get("name", "Unknown")
        team = player.get("team", "")
        position = player.get("position", "")
        league = player.get("league", "")

        info_parts = []
        if position:
            info_parts.append(position)
        if team:
            info_parts.append(team)
        if league:
            info_parts.append(f"({league.upper()})")

        info_str = " | ".join(info_parts)
        lines.append(f"<code>{idx}. {name}</code>")
        if info_str:
            lines.append(f"   <i>{info_str}</i>")

    lines.append("")
    lines.append("<i>Reply with the number to select a player</i>")

    return "\n".join(lines)

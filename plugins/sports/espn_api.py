"""
ESPN API client for fetching live sports data.

Uses ESPN's free public API (no authentication required).
All functions are async and return None on failure.
"""

import aiohttp
import asyncio
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta, timezone

from plugins.sports.config import (
    LEAGUES,
    get_scoreboard_url,
    get_standings_url,
    get_schedule_url,
    get_teams_url,
    get_team_detail_url,
)

logger = logging.getLogger(__name__)

# HTTP session timeout (seconds)
TIMEOUT = aiohttp.ClientTimeout(total=10)


# ═══════════════════════════════════════════════════════════════════════════════
# GENERIC HTTP HELPER
# ═══════════════════════════════════════════════════════════════════════════════

async def _fetch_json(url: str) -> Optional[Dict[str, Any]]:
    """
    Fetch and parse JSON from a URL.

    Returns None on any failure (network, timeout, parse error).
    Logs errors but never crashes.
    """
    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    logger.warning(f"ESPN API returned status {resp.status}: {url}")
                    return None
    except asyncio.TimeoutError:
        logger.warning(f"ESPN API timeout: {url}")
        return None
    except Exception as e:
        logger.error(f"ESPN API error fetching {url}: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# SCORES
# ═══════════════════════════════════════════════════════════════════════════════

async def get_scores(league_slug: str, yesterday: bool = True) -> Optional[Dict[str, Any]]:
    """
    Get scores for a league. Defaults to yesterday's completed games.

    Args:
        league_slug: One of "nfl", "nba", "mlb", "nhl", "ncaaf", "ncaab",
                     "epl", "mls", "bundesliga", "laliga"
        yesterday: If True (default), fetch yesterday's scores. If False,
                   fetch today's games (schedule/live).

    Returns:
        dict with keys:
            "games": List of game objects with home, away, status, score
            "league": League name and emoji
            "date_label": "Yesterday" or "Today"
        or None if API fails
    """
    league_info = LEAGUES.get(league_slug.lower())
    if not league_info:
        logger.warning(f"Unknown league: {league_slug}")
        return None

    base_url = get_scoreboard_url(league_info["sport"], league_info["league"])

    # ESPN scoreboard supports ?dates=YYYYMMDD
    if yesterday:
        target = datetime.now(timezone.utc) - timedelta(days=1)
        date_label = "Yesterday"
    else:
        target = datetime.now(timezone.utc)
        date_label = "Today"

    date_str = target.strftime("%Y%m%d")
    url = f"{base_url}?dates={date_str}"
    logger.info(f"Fetching scores from: {url}")
    data = await _fetch_json(url)

    if not data:
        return None

    # Extract games
    games = []
    for event in data.get("events", []):
        try:
            # Get competitors (home/away)
            competitors = event.get("competitions", [{}])[0].get("competitors", [])
            if len(competitors) >= 2:
                away = competitors[1]  # Usually index 0 is home, 1 is away
                home = competitors[0]

                game = {
                    "id": event.get("id"),
                    "date": event.get("date"),
                    "status": event.get("status", {}).get("type", {}).get("name", "Scheduled"),
                    "home_team": home.get("team", {}).get("displayName", "Unknown"),
                    "home_logo": home.get("team", {}).get("logo", ""),
                    "home_score": home.get("score", ""),
                    "away_team": away.get("team", {}).get("displayName", "Unknown"),
                    "away_logo": away.get("team", {}).get("logo", ""),
                    "away_score": away.get("score", ""),
                    "game_url": event.get("links", [{}])[0].get("href", ""),
                }
                games.append(game)
        except (IndexError, KeyError, TypeError) as e:
            logger.debug(f"Error parsing game: {e}")
            continue

    return {
        "games": games,
        "league": league_info["name"],
        "emoji": league_info["emoji"],
        "date_label": date_label,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# STANDINGS
# ═══════════════════════════════════════════════════════════════════════════════

async def get_standings(league_slug: str) -> Optional[Dict[str, Any]]:
    """
    Get league standings/rankings.

    Args:
        league_slug: League identifier

    Returns:
        dict with:
            "standings": List of division/conference groups with team rankings
            "league": League name
        or None if API fails
    """
    league_info = LEAGUES.get(league_slug.lower())
    if not league_info:
        return None

    url = get_standings_url(league_info["sport"], league_info["league"])
    data = await _fetch_json(url)

    if not data:
        return None

    standings = []

    # ESPN standings API returns data in multiple possible structures:
    #   Format A: data.children[] → .standings.entries[]  (NBA, NFL, MLB, NHL)
    #   Format B: data.standings[] → .groups[].entries[]  (older format)
    #   Format C: data.children[] → .children[] → .standings.entries[]  (nested conferences)

    def _parse_entries(entries: list) -> list:
        """Parse a list of team standing entries."""
        teams = []
        for team_entry in entries:
            try:
                team = team_entry.get("team", {})
                stats = team_entry.get("stats", [])

                wins = losses = gb = pct = "0"
                for stat in stats:
                    sname = stat.get("name", "")
                    sval = stat.get("displayValue", "0")
                    if sname == "wins":
                        wins = sval
                    elif sname == "losses":
                        losses = sval
                    elif sname == "gamesBehind":
                        gb = sval
                    elif sname in ("winPercent", "winPct"):
                        pct = sval

                teams.append({
                    "name": team.get("displayName", "Unknown"),
                    "logo": team.get("logo", ""),
                    "wins": wins,
                    "losses": losses,
                    "games_behind": gb,
                    "win_pct": pct,
                })
            except (KeyError, TypeError):
                continue

        # Sort by wins descending (ESPN sometimes returns unsorted data)
        def _sort_key(t):
            try:
                return -int(t.get("wins", "0"))
            except (ValueError, TypeError):
                return 0
        teams.sort(key=_sort_key)
        return teams

    # Try Format A: data.children[]
    for child in data.get("children", []):
        child_name = child.get("name", child.get("abbreviation", "Standings"))

        # Check for nested children (Format C: conferences → divisions)
        if "children" in child:
            for sub_child in child.get("children", []):
                sub_name = sub_child.get("name", sub_child.get("abbreviation", ""))
                entries = sub_child.get("standings", {}).get("entries", [])
                teams = _parse_entries(entries)
                if teams:
                    label = f"{child_name} — {sub_name}" if sub_name else child_name
                    standings.append({"division": label, "teams": teams})

        # Direct standings (Format A: conference → standings.entries)
        entries = child.get("standings", {}).get("entries", [])
        if entries:
            teams = _parse_entries(entries)
            if teams:
                standings.append({"division": child_name, "teams": teams})

    # Fallback: Format B — data.standings[]
    if not standings:
        for division in data.get("standings", []):
            div_name = division.get("name", "Standings")
            for group in division.get("groups", [{}]):
                entries = group.get("entries", [])
                teams = _parse_entries(entries)
                if teams:
                    standings.append({"division": div_name, "teams": teams})

    # Last fallback: flat entries at top level
    if not standings:
        entries = data.get("standings", {}).get("entries", []) if isinstance(data.get("standings"), dict) else []
        teams = _parse_entries(entries)
        if teams:
            standings.append({"division": "Standings", "teams": teams})

    return {
        "standings": standings,
        "league": league_info["name"],
        "emoji": league_info["emoji"],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# SCHEDULE
# ═══════════════════════════════════════════════════════════════════════════════

async def get_schedule(
    league_slug: str,
    team_name: Optional[str] = None,
    days: int = 7,
) -> Optional[Dict[str, Any]]:
    """
    Get upcoming games/schedule.

    Args:
        league_slug: League identifier
        team_name: Optional; filter to a specific team
        days: How many days ahead to fetch (default 7)

    Returns:
        dict with:
            "games": List of upcoming games
            "league": League name
            "team": Team name (if filtered)
        or None if API fails
    """
    league_info = LEAGUES.get(league_slug.lower())
    if not league_info:
        return None

    url = get_schedule_url(league_info["sport"], league_info["league"])
    data = await _fetch_json(url)

    if not data:
        return None

    games = []
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=days)

    for event in data.get("events", []):
        try:
            event_date = datetime.fromisoformat(event.get("date", "").replace("Z", "+00:00"))

            # Filter by date range
            if event_date < now or event_date > cutoff:
                continue

            competitors = event.get("competitions", [{}])[0].get("competitors", [])
            if len(competitors) < 2:
                continue

            away = competitors[1]
            home = competitors[0]

            home_team = home.get("team", {}).get("displayName", "")
            away_team = away.get("team", {}).get("displayName", "")

            # Filter by team if specified
            if team_name:
                if team_name.lower() not in home_team.lower() and team_name.lower() not in away_team.lower():
                    continue

            game = {
                "id": event.get("id"),
                "date": event.get("date"),
                "home_team": home_team,
                "home_logo": home.get("team", {}).get("logo", ""),
                "away_team": away_team,
                "away_logo": away.get("team", {}).get("logo", ""),
                "status": event.get("status", {}).get("type", {}).get("name", "Scheduled"),
                "venue": event.get("competitions", [{}])[0].get("venue", {}).get("fullName", ""),
            }
            games.append(game)
        except (IndexError, KeyError, TypeError, ValueError):
            continue

    return {
        "games": games,
        "league": league_info["name"],
        "emoji": league_info["emoji"],
        "team": team_name,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# TEAMS
# ═══════════════════════════════════════════════════════════════════════════════

async def get_teams(league_slug: str) -> Optional[List[Dict[str, Any]]]:
    """
    Get all teams in a league.

    Returns a list of teams with id, name, logo, or None on failure.
    """
    league_info = LEAGUES.get(league_slug.lower())
    if not league_info:
        return None

    url = get_teams_url(league_info["sport"], league_info["league"])
    data = await _fetch_json(url)

    if not data:
        return None

    teams = []
    for team_data in data.get("teams", []):
        try:
            team = {
                "id": team_data.get("id"),
                "name": team_data.get("displayName", ""),
                "abbreviation": team_data.get("abbreviation", ""),
                "logo": team_data.get("logo", ""),
            }
            teams.append(team)
        except (KeyError, TypeError):
            continue

    return teams


async def get_team_info(league_slug: str, team_name: str) -> Optional[Dict[str, Any]]:
    """
    Search for a team by name in a league.

    Returns the matching team dict or None.
    """
    teams = await get_teams(league_slug)
    if not teams:
        return None

    # Case-insensitive search
    team_lower = team_name.lower()
    for team in teams:
        if (team_lower in team["name"].lower() or
            team_lower == team.get("abbreviation", "").lower()):
            return team

    return None


# ═══════════════════════════════════════════════════════════════════════════════
# GAME DETAIL
# ═══════════════════════════════════════════════════════════════════════════════

async def get_game_detail(game_id: str) -> Optional[Dict[str, Any]]:
    """
    Get detailed information about a specific game.

    Args:
        game_id: ESPN game ID

    Returns:
        dict with game details or None if not found
    """
    # ESPN doesn't have a direct game detail endpoint in the public API,
    # so we return the data from the scoreboard endpoints.
    # In a real implementation, you'd parse the game_id to determine league,
    # then fetch from that league's scoreboard and find the game.
    # For now, return None as a placeholder.
    logger.debug(f"get_game_detail called for {game_id}")
    return None

"""
ESPN Stats API — Team and Player statistics for Big 4 US leagues.

Provides functions to fetch player and team statistics from ESPN's public APIs.
All functions are async and return None on failure.
"""

import logging
import aiohttp
import asyncio
from typing import Optional, Dict, Any, List

from .espn_api import _fetch_json
from .config import LEAGUES, ESPN_BASE, ESPN_SITE

logger = logging.getLogger(__name__)

# Additional ESPN API endpoints for stats/athletes
ESPN_COMMON = f"{ESPN_BASE}/common/v3"
ESPN_WEB = "https://site.web.api.espn.com/apis/common/v3"


# ═══════════════════════════════════════════════════════════════════════════════
# PLAYER SEARCH
# ═══════════════════════════════════════════════════════════════════════════════

async def search_player(
    name: str,
    sport: Optional[str] = None,
    league: Optional[str] = None,
) -> Optional[List[Dict[str, Any]]]:
    """
    Search ESPN for a player by name.

    Args:
        name: Player name to search for
        sport: Optional sport filter (e.g., "football", "basketball")
        league: Optional league filter (e.g., "nfl", "nba")

    Returns:
        List of matching players with id, name, team, position, sport, league,
        and headshot_url. Returns None if API fails or no results found.

    Endpoint:
        https://site.api.espn.com/apis/common/v3/search?query={name}&type=player&limit=5
    """
    if not name or not name.strip():
        return None

    try:
        # Build search URL with query parameters
        url = f"{ESPN_COMMON}/search"
        params = {
            "query": name.strip(),
            "type": "player",
            "limit": "5",
            "region": "us",
            "lang": "en",
            "contentorigin": "espn",
        }

        # Build query string
        query_str = "&".join(f"{k}={v}" for k, v in params.items())
        full_url = f"{url}?{query_str}"

        data = await _fetch_json(full_url)
        if not data:
            return None

        results = []
        # ESPN search API returns results in various formats
        items = data.get("results", []) or data.get("items", [])

        for item in items:
            try:
                # Format 1: {type, player: {}, team: {}}
                if item.get("type") == "player" or "player" in item:
                    player_data = item.get("player", item)
                    athlete_id = player_data.get("id") or item.get("id")
                    display_name = player_data.get("displayName", "") or item.get("displayName", "")
                    pos = player_data.get("position", "")
                    position = pos.get("name", "") if isinstance(pos, dict) else str(pos)
                    headshot = player_data.get("headshot", "")

                    team_data = item.get("team", player_data.get("team", {}))
                    if isinstance(team_data, dict):
                        team_name = team_data.get("displayName", "")
                        sport_val = team_data.get("sport", "")
                        league_obj = team_data.get("league", {})
                        league_val = league_obj.get("name", "") if isinstance(league_obj, dict) else str(league_obj)
                    else:
                        team_name = ""
                        sport_val = ""
                        league_val = ""

                    if athlete_id and display_name:
                        results.append({
                            "id": str(athlete_id),
                            "name": display_name,
                            "team": team_name,
                            "position": position,
                            "sport": sport_val,
                            "league": league_val,
                            "headshot_url": headshot if isinstance(headshot, str) else "",
                        })

                # Format 2: flat athlete objects
                elif item.get("id") and item.get("displayName"):
                    results.append({
                        "id": str(item["id"]),
                        "name": item["displayName"],
                        "team": item.get("team", {}).get("displayName", "") if isinstance(item.get("team"), dict) else "",
                        "position": "",
                        "sport": "",
                        "league": "",
                        "headshot_url": "",
                    })

            except (KeyError, TypeError) as e:
                logger.debug(f"Error parsing player search result: {e}")
                continue

        return results if results else None

    except Exception as e:
        logger.error(f"Error searching for player '{name}': {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# PLAYER STATS
# ═══════════════════════════════════════════════════════════════════════════════

async def get_player_stats(
    athlete_id: str,
    sport: str,
    league: str,
    player_name: str = "",
) -> Optional[Dict[str, Any]]:
    """
    Get detailed player statistics from ESPN.

    Args:
        athlete_id: ESPN athlete ID
        sport: Sport slug (e.g., "football", "basketball")
        league: League slug (e.g., "nfl", "nba")

    Returns:
        Dict with name, team, position, jersey, headshot, and stats organized
        by category. Returns None if not found or API fails.

    Tries multiple endpoints:
        1. https://site.web.api.espn.com/apis/common/v3/sports/{sport}/{league}/athletes/{id}/stats
        2. https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/athletes/{id}
    """
    if not athlete_id or not sport or not league:
        return None

    try:
        # Primary endpoint: common/v3 web stats (confirmed working)
        url1 = f"{ESPN_WEB}/sports/{sport}/{league}/athletes/{athlete_id}/stats?region=us&lang=en&contentorigin=espn"
        logger.info(f"Fetching player stats from: {url1}")
        data = await _fetch_json(url1)

        if data:
            logger.info(f"Got stats data, top-level keys: {list(data.keys())}")
            result = _parse_player_stats(data, athlete_id)
            if result:
                # Ensure we have a name (API may not return one)
                if not result.get("name") and player_name:
                    result["name"] = player_name
                return result
            logger.warning(f"Failed to parse stats from web endpoint")

        # Fallback: site/v2 athlete overview
        url2 = f"{ESPN_SITE}/sports/{sport}/{league}/athletes/{athlete_id}"
        logger.info(f"Trying fallback: {url2}")
        data = await _fetch_json(url2)

        if data:
            logger.info(f"Got fallback data, top-level keys: {list(data.keys())}")
            result = _parse_player_stats(data, athlete_id)
            if result:
                if not result.get("name") and player_name:
                    result["name"] = player_name
                return result
            logger.warning(f"Failed to parse stats from v2 endpoint")

        return None

    except Exception as e:
        logger.error(f"Error fetching player stats for {athlete_id}: {e}")
        return None


def _parse_player_stats(data: Dict[str, Any], athlete_id: str) -> Optional[Dict[str, Any]]:
    """
    Parse player stats from ESPN API response.

    Handles two main formats:
    1. common/v3/stats: {athlete: {...}, categories: [{name, labels, stats}]}
       - labels and stats are parallel arrays
    2. site/v2/athletes: {athlete: {displayName, statistics: [{name, stats: [{name, value}]}]}}
       - stats are individual objects with name/value
    """
    try:
        # ── Get athlete info ──────────────────────────────────────────────
        athlete = data.get("athlete", {})

        if not athlete:
            athletes_list = data.get("athletes", [])
            if athletes_list:
                athlete = athletes_list[0]

        result = {
            "id": athlete_id,
            "name": "",
            "position": "",
            "jersey": "",
            "headshot": "",
            "team": "",
            "stats": {},
        }

        # If athlete dict exists, extract info from it
        if athlete:
            result["name"] = athlete.get("displayName", "")
            result["jersey"] = athlete.get("jersey", "")
            result["headshot"] = athlete.get("headshot", "")

            pos = athlete.get("position", "")
            if isinstance(pos, dict):
                result["position"] = pos.get("name", "") or pos.get("displayName", "")
            elif isinstance(pos, str):
                result["position"] = pos

            team = athlete.get("team", {})
            if isinstance(team, dict) and team:
                result["team"] = team.get("displayName", "")
                result["team_id"] = team.get("id", "")

        # ── Fallback: extract athlete info from "teams" (v3/stats format) ─
        # The v3/stats endpoint has no "athlete" key; info is in "teams"
        if not result["name"]:
            teams_list = data.get("teams", [])
            if teams_list and isinstance(teams_list, list):
                team_data = teams_list[0]
                if isinstance(team_data, dict):
                    # Team data might have athlete info
                    result["team"] = team_data.get("displayName", "") or team_data.get("name", "")
                    result["team_id"] = str(team_data.get("id", ""))
                    # Try to get athlete from team
                    team_athlete = team_data.get("athlete", {})
                    if team_athlete:
                        result["name"] = team_athlete.get("displayName", "")
                        result["position"] = team_athlete.get("position", "")
                        result["jersey"] = team_athlete.get("jersey", "")

        # ── Last resort: search for name in the data ─────────────────────
        if not result["name"]:
            # Try displayName at root level
            result["name"] = data.get("displayName", "")

        logger.info(f"Athlete info: name={result['name']}, team={result.get('team', '')}")

        # ── Parse statistics ──────────────────────────────────────────────
        # Check multiple locations for categories/statistics data
        categories = data.get("categories", [])
        if not categories:
            categories = data.get("statistics", [])
        if not categories and athlete:
            categories = athlete.get("statistics", [])
        if not categories and athlete:
            categories = athlete.get("categories", [])

        logger.info(f"Found {len(categories)} stat categories")

        for stat_category in categories:
            try:
                category_name = (
                    stat_category.get("name", "")
                    or stat_category.get("displayName", "")
                    or stat_category.get("type", "")
                )

                if not category_name:
                    continue

                stats = []

                # ESPN v3/stats has parallel arrays: labels + totals/statistics
                # v2 format has individual stat objects with name/value
                labels = stat_category.get("labels", [])
                display_names = stat_category.get("displayNames", [])

                # Prefer "totals" (flat summary array) over "statistics" (may be 2D)
                totals = stat_category.get("totals", [])
                raw_statistics = stat_category.get("statistics", [])
                raw_stats_legacy = stat_category.get("stats", [])

                if labels and totals and isinstance(totals, list):
                    # Flat parallel arrays: labels=["PTS","REB"], totals=["26.4","12.3"]
                    for i, label in enumerate(labels):
                        if i < len(totals):
                            display = display_names[i] if i < len(display_names) else label
                            stats.append({
                                "name": label,
                                "displayName": display,
                                "value": str(totals[i]),
                                "abbreviation": label,
                            })
                elif labels and raw_statistics and isinstance(raw_statistics, list):
                    # statistics might be 2D (list of rows) or flat
                    flat_row = raw_statistics
                    if raw_statistics and isinstance(raw_statistics[0], list):
                        # 2D: take most recent row (last one)
                        flat_row = raw_statistics[-1] if raw_statistics else []
                    if flat_row and not isinstance(flat_row[0], dict):
                        for i, label in enumerate(labels):
                            if i < len(flat_row):
                                display = display_names[i] if i < len(display_names) else label
                                stats.append({
                                    "name": label,
                                    "displayName": display,
                                    "value": str(flat_row[i]),
                                    "abbreviation": label,
                                })
                elif raw_stats_legacy and isinstance(raw_stats_legacy, list):
                    if raw_stats_legacy and isinstance(raw_stats_legacy[0], dict):
                        # Object format: stats=[{name, displayName, value, ...}]
                        for stat in raw_stats_legacy:
                            stats.append({
                                "name": stat.get("name", "") or stat.get("abbreviation", ""),
                                "displayName": stat.get("displayName", "") or stat.get("name", ""),
                                "value": str(stat.get("value", "")),
                                "abbreviation": stat.get("abbreviation", ""),
                            })

                if stats:
                    result["stats"][category_name] = stats

            except (KeyError, TypeError) as e:
                logger.debug(f"Error parsing stat category: {e}")
                continue

        # Parse splits if available
        splits = data.get("splits", {})
        if not splits and athlete:
            splits = athlete.get("splits", {})
        if splits:
            result["splits"] = splits

        logger.info(f"Parsed stats: name={result.get('name')}, stat_categories={list(result.get('stats', {}).keys())}")

        return result if (result.get("name") or result.get("stats")) else None

    except Exception as e:
        logger.error(f"Error parsing player stats: {e}", exc_info=True)
        return None


async def get_player_gamelog(
    athlete_id: str,
    sport: str,
    league: str,
) -> Optional[Dict[str, Any]]:
    """
    Get recent game log for a player.

    Args:
        athlete_id: ESPN athlete ID
        sport: Sport slug
        league: League slug

    Returns:
        Dict with player name, team, and list of recent game performances.
        Returns None if not found.

    Endpoint:
        https://site.web.api.espn.com/apis/common/v3/sports/{sport}/{league}/athletes/{id}/gamelog
    """
    if not athlete_id or not sport or not league:
        return None

    try:
        # Try site/v2 first, then web API
        url1 = f"{ESPN_SITE}/sports/{sport}/{league}/athletes/{athlete_id}/gamelog"
        data = await _fetch_json(url1)

        if not data:
            url2 = f"{ESPN_WEB}/sports/{sport}/{league}/athletes/{athlete_id}/gamelog?region=us&lang=en&contentorigin=espn"
            data = await _fetch_json(url2)

        if not data:
            return None

        athlete = data.get("athlete", {})

        result = {
            "id": athlete_id,
            "name": athlete.get("displayName", ""),
            "position": athlete.get("position", {}).get("name", ""),
            "games": [],
        }

        # Extract team
        team = athlete.get("team", {})
        if team:
            result["team"] = team.get("displayName", "")

        # Parse game log entries
        events = data.get("events", [])
        for event in events:
            try:
                game_entry = {
                    "date": event.get("date", ""),
                    "game_id": event.get("id", ""),
                    "opponent": "",
                    "stats": {},
                }

                # Get opponent info
                competitions = event.get("competitions", [])
                if competitions:
                    competition = competitions[0]
                    competitors = competition.get("competitors", [])
                    if len(competitors) >= 2:
                        # Find the opponent (the one that isn't the player's team)
                        for competitor in competitors:
                            if competitor.get("homeAway") == "away":
                                game_entry["opponent"] = competitor.get("team", {}).get("displayName", "")
                                break

                # Parse game stats
                stats_list = event.get("statistics", []) or event.get("categories", [])
                for stat_category in stats_list:
                    try:
                        cat_name = stat_category.get("name", "") or stat_category.get("displayName", "")
                        if not cat_name:
                            continue

                        stats = {}
                        for stat in stat_category.get("stats", []):
                            stat_name = stat.get("name", "") or stat.get("abbreviation", "")
                            if stat_name:
                                stats[stat_name] = stat.get("value", "")

                        if stats:
                            game_entry["stats"][cat_name] = stats

                    except (KeyError, TypeError):
                        continue

                result["games"].append(game_entry)

            except (KeyError, TypeError):
                continue

        return result if result.get("name") else None

    except Exception as e:
        logger.error(f"Error fetching player gamelog for {athlete_id}: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# TEAM STATS
# ═══════════════════════════════════════════════════════════════════════════════

async def get_team_stats(
    team_id: str,
    sport: str,
    league: str,
) -> Optional[Dict[str, Any]]:
    """
    Get team statistics from ESPN.

    Args:
        team_id: ESPN team ID
        sport: Sport slug
        league: League slug

    Returns:
        Dict with team name, abbreviation, logo, record, and statistics.
        Returns None if not found.

    Tries endpoints:
        1. https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/teams/{id}/statistics
        2. https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/teams/{id}
    """
    if not team_id or not sport or not league:
        return None

    try:
        # Try endpoint 1: statistics-specific
        url1 = f"{ESPN_SITE}/sports/{sport}/{league}/teams/{team_id}/statistics"
        data = await _fetch_json(url1)

        if data:
            return _parse_team_stats(data)

        # Fallback to endpoint 2: general team info (includes stats)
        url2 = f"{ESPN_SITE}/sports/{sport}/{league}/teams/{team_id}"
        data = await _fetch_json(url2)

        if data:
            return _parse_team_stats(data)

        return None

    except Exception as e:
        logger.error(f"Error fetching team stats for {team_id}: {e}")
        return None


def _parse_team_stats(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Parse team stats from ESPN API response."""
    try:
        # Handle different response formats
        team = data.get("team", {}) or data.get("teams", [{}])[0]

        if not team.get("id"):
            return None

        result = {
            "id": team.get("id"),
            "name": team.get("displayName", ""),
            "abbreviation": team.get("abbreviation", ""),
            "logo": team.get("logo", ""),
            "stats": {},
        }

        # Extract record if available
        record = team.get("record", {})
        if record:
            result["record"] = {
                "wins": record.get("items", [{}])[0].get("wins", "") if record.get("items") else "",
                "losses": record.get("items", [{}])[0].get("losses", "") if record.get("items") else "",
            }

        # Parse statistics
        stats_list = team.get("statistics", []) or team.get("categories", [])

        for stat_category in stats_list:
            try:
                category_name = stat_category.get("name", "") or stat_category.get("displayName", "")

                if not category_name:
                    continue

                stats = []
                for stat in stat_category.get("stats", []):
                    stat_obj = {
                        "name": stat.get("name", ""),
                        "displayName": stat.get("displayName", ""),
                        "value": stat.get("value", ""),
                        "rank": stat.get("rank", ""),
                    }
                    stats.append(stat_obj)

                if stats:
                    result["stats"][category_name] = stats

            except (KeyError, TypeError):
                continue

        return result if result.get("name") else None

    except Exception as e:
        logger.debug(f"Error parsing team stats: {e}")
        return None


async def get_team_roster(
    team_id: str,
    sport: str,
    league: str,
) -> Optional[Dict[str, Any]]:
    """
    Get team roster from ESPN.

    Args:
        team_id: ESPN team ID
        sport: Sport slug
        league: League slug

    Returns:
        Dict with team_name and players list containing id, name, position,
        jersey, headshot. Returns None if not found.

    Endpoint:
        https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/teams/{id}/roster
    """
    if not team_id or not sport or not league:
        return None

    try:
        url = f"{ESPN_SITE}/sports/{sport}/{league}/teams/{team_id}/roster"
        data = await _fetch_json(url)

        if not data:
            return None

        result = {
            "team_id": team_id,
            "players": [],
        }

        # Get team name if available
        team = data.get("team", {})
        if team:
            result["team_name"] = team.get("displayName", "")

        # Parse roster entries
        athletes = data.get("athletes", [])
        for athlete in athletes:
            try:
                player = {
                    "id": athlete.get("id", ""),
                    "name": athlete.get("displayName", ""),
                    "position": athlete.get("position", {}).get("name", "") if isinstance(athlete.get("position"), dict) else athlete.get("position", ""),
                    "jersey": athlete.get("jersey", ""),
                    "headshot": athlete.get("headshot", ""),
                }

                if player["id"] and player["name"]:
                    result["players"].append(player)

            except (KeyError, TypeError):
                continue

        return result if result.get("players") else None

    except Exception as e:
        logger.error(f"Error fetching roster for team {team_id}: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# TEAM SEARCH
# ═══════════════════════════════════════════════════════════════════════════════

async def search_team(
    name: str,
    league_slug: Optional[str] = None,
) -> Optional[List[Dict[str, Any]]]:
    """
    Search for a team by name within a league.

    Args:
        name: Team name to search for (supports partial matching)
        league_slug: Optional league slug to filter (e.g., "nfl", "nba")

    Returns:
        List of matching teams with id, name, abbreviation, logo, and league.
        Returns None if no matches found.

    Uses the teams list endpoint and performs fuzzy/case-insensitive matching:
        https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/teams
    """
    if not name or not name.strip():
        return None

    try:
        results = []
        name_lower = name.strip().lower()

        # If league specified, search just that league
        if league_slug:
            league_info = LEAGUES.get(league_slug.lower())
            if not league_info:
                return None

            teams = await _fetch_teams_for_league(league_info["sport"], league_info["league"])
            if teams:
                for team in teams:
                    if _team_matches(team, name_lower):
                        results.append({
                            "id": team.get("id"),
                            "name": team.get("displayName", ""),
                            "abbreviation": team.get("abbreviation", ""),
                            "logo": team.get("logo", ""),
                            "league": league_slug,
                        })

        else:
            # Search across all leagues
            for league_slug_iter, league_info in LEAGUES.items():
                teams = await _fetch_teams_for_league(league_info["sport"], league_info["league"])
                if teams:
                    for team in teams:
                        if _team_matches(team, name_lower):
                            results.append({
                                "id": team.get("id"),
                                "name": team.get("displayName", ""),
                                "abbreviation": team.get("abbreviation", ""),
                                "logo": team.get("logo", ""),
                                "league": league_slug_iter,
                            })

        return results if results else None

    except Exception as e:
        logger.error(f"Error searching for team '{name}': {e}")
        return None


async def _fetch_teams_for_league(sport: str, league: str) -> Optional[List[Dict[str, Any]]]:
    """Fetch the teams list for a specific league."""
    try:
        url = f"{ESPN_SITE}/sports/{sport}/{league}/teams"
        data = await _fetch_json(url)

        if not data:
            return None

        raw_teams = data.get("sports", [{}])[0].get("leagues", [{}])[0].get("teams", [])
        if not raw_teams:
            raw_teams = data.get("teams", [])

        # ESPN often nests team data under a "team" key
        teams = []
        for entry in raw_teams:
            if isinstance(entry, dict) and "team" in entry:
                teams.append(entry["team"])
            else:
                teams.append(entry)

        return teams if teams else None

    except Exception as e:
        logger.debug(f"Error fetching teams for {sport}/{league}: {e}")
        return None


def _team_matches(team: Dict[str, Any], query: str) -> bool:
    """Check if a team matches a search query (case-insensitive, partial match)."""
    try:
        name_lower = team.get("displayName", "").lower()
        abbrev_lower = team.get("abbreviation", "").lower()

        # Exact match or partial match on name
        if query in name_lower or name_lower in query:
            return True

        # Exact match on abbreviation
        if query == abbrev_lower:
            return True

        return False

    except (TypeError, AttributeError):
        return False

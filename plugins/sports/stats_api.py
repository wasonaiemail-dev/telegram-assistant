"""
Sports Stats API — Player and Team statistics with ESPN + API-Sports failover.

Primary source: ESPN public API (free, no key needed)
Fallback source: API-Sports (free 100 req/day, requires API_SPORTS_KEY)

Failover pattern:
    1. Try ESPN first (free, proven for basic stats)
    2. If ESPN fails or returns empty → try API-Sports
    3. If both fail → return None

This ensures zero cost for most queries while having a reliable backup.
"""

import logging
import aiohttp
import asyncio
from typing import Optional, Dict, Any, List

from .espn_api import _fetch_json
from .config import LEAGUES, ESPN_BASE, ESPN_SITE
from . import api_sports

logger = logging.getLogger(__name__)

# Additional ESPN API endpoints for stats/athletes
ESPN_COMMON = f"{ESPN_BASE}/common/v3"
ESPN_WEB = "https://site.web.api.espn.com/apis/common/v3"


# ═══════════════════════════════════════════════════════════════════════════════
# HELPER: Map ESPN sport/league to our league slug
# ═══════════════════════════════════════════════════════════════════════════════

def _find_league_slug(sport: str, league: str) -> Optional[str]:
    """
    Find our league slug from ESPN sport/league values.

    Args:
        sport: ESPN sport (e.g., "basketball", "football")
        league: ESPN league (e.g., "nba", "nfl")

    Returns:
        League slug (e.g., "nba", "nfl") or None if not found.
    """
    # Direct match on league
    league_lower = league.lower()
    if league_lower in LEAGUES:
        return league_lower

    # Try to match by sport + league combo
    for slug, info in LEAGUES.items():
        if info["sport"] == sport and info["league"] == league:
            return slug

    return None


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

        if results:
            return results

        # ESPN returned no results — try API-Sports fallback
        league_slug = league.lower() if league else None
        if not league_slug and sport:
            # Guess the league slug from sport
            sport_to_league = {
                "basketball": "nba", "football": "nfl",
                "baseball": "mlb", "hockey": "nhl", "soccer": "epl",
            }
            league_slug = sport_to_league.get(sport.lower())

        if league_slug and api_sports.is_available() and api_sports.has_player_stats(league_slug):
            logger.info(f"ESPN player search empty, trying API-Sports (league={league_slug})")
            api_results = await api_sports.search_player(name, league_slug)
            if api_results:
                return api_results

        return None

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

        # Fallback 1: ESPN site/v2 athlete overview
        url2 = f"{ESPN_SITE}/sports/{sport}/{league}/athletes/{athlete_id}"
        logger.info(f"Trying ESPN fallback: {url2}")
        data = await _fetch_json(url2)

        if data:
            logger.info(f"Got fallback data, top-level keys: {list(data.keys())}")
            result = _parse_player_stats(data, athlete_id)
            if result:
                if not result.get("name") and player_name:
                    result["name"] = player_name
                return result
            logger.warning(f"Failed to parse stats from v2 endpoint")

        # Fallback 2: API-Sports (if configured)
        # We need to find the league slug from sport/league to use API-Sports
        league_slug = _find_league_slug(sport, league)
        if league_slug and api_sports.is_available() and api_sports.has_player_stats(league_slug):
            logger.info(f"ESPN failed, trying API-Sports for player stats (league={league_slug})")
            # We need the API-Sports player ID — search by name
            if player_name:
                api_players = await api_sports.search_player(player_name, league_slug)
                if api_players:
                    api_player_id = api_players[0]["id"]
                    api_result = await api_sports.get_player_stats(api_player_id, league_slug)
                    if api_result:
                        logger.info(f"Got player stats from API-Sports fallback")
                        return api_result

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
    player_name: str = "",
) -> Optional[Dict[str, Any]]:
    """
    Get recent game log for a player.

    ESPN v3 gamelog format:
        labels: ["MIN", "FG", "FG%", ...] — stat column headers
        events: {eventId: {gameDate, opponent, atVs, score, gameResult, ...}} — game info
        seasonTypes[0].categories[]: monthly groups, each with
            events[]: {eventId, stats: ["44", "13-25", ...]} — parallel to labels

    We join seasonTypes events with the events dict by eventId.
    """
    if not athlete_id or not sport or not league:
        return None

    try:
        # v3 web API is the only working endpoint for gamelog
        url = f"{ESPN_WEB}/sports/{sport}/{league}/athletes/{athlete_id}/gamelog?region=us&lang=en&contentorigin=espn"
        logger.info(f"Fetching gamelog from: {url}")
        data = await _fetch_json(url)

        if not data:
            return None

        # Get stat labels
        labels = data.get("labels", [])
        if not labels:
            logger.warning("Gamelog has no labels")
            return None

        result = {
            "id": athlete_id,
            "name": player_name,
            "games": [],
            "labels": labels,
        }

        # events dict: eventId -> game info (date, opponent, score, result)
        events_dict = data.get("events", {})
        if not isinstance(events_dict, dict):
            events_dict = {}

        # Collect all game stat entries from seasonTypes (most recent first)
        # seasonTypes[0] = Regular Season, categories are by month (newest first)
        season_types = data.get("seasonTypes", [])
        all_stat_events = []

        for st in season_types:
            st_name = st.get("displayName", "")
            # Skip preseason
            if "preseason" in st_name.lower():
                continue
            categories = st.get("categories", [])
            for cat in categories:
                cat_events = cat.get("events", [])
                for cev in cat_events:
                    all_stat_events.append(cev)

        # Build game entries by joining stat events with event info
        for stat_event in all_stat_events:
            try:
                event_id = stat_event.get("eventId", "")
                stats_values = stat_event.get("stats", [])

                # Look up game info from events dict
                event_info = events_dict.get(event_id, {})

                # Build stat dict: label -> value
                game_stats = {}
                for i, label in enumerate(labels):
                    if i < len(stats_values):
                        game_stats[label] = stats_values[i]

                opponent = event_info.get("opponent", {})
                at_vs = event_info.get("atVs", "vs")
                opp_name = opponent.get("displayName", "") if isinstance(opponent, dict) else ""
                opp_abbrev = opponent.get("abbreviation", "") if isinstance(opponent, dict) else ""
                game_result = event_info.get("gameResult", "")
                score = event_info.get("score", "")

                game_entry = {
                    "date": event_info.get("gameDate", ""),
                    "game_id": event_id,
                    "opponent": opp_name or opp_abbrev,
                    "opponent_abbrev": opp_abbrev,
                    "at_vs": at_vs,
                    "result": game_result,
                    "score": score,
                    "stats": game_stats,
                }

                result["games"].append(game_entry)

            except (KeyError, TypeError, IndexError):
                continue

        return result if result.get("games") else None

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
        # Primary: v2 statistics (confirmed working, has full stats)
        url1 = f"{ESPN_SITE}/sports/{sport}/{league}/teams/{team_id}/statistics"
        logger.info(f"Fetching team stats from: {url1}")
        data = await _fetch_json(url1)

        if data:
            logger.info(f"Got team stats data (v2), top-level keys: {list(data.keys())}")
            result = _parse_team_stats(data)
            if result and result.get("stats"):
                return result

        # Fallback 1: ESPN general team info (at least has name/record)
        url2 = f"{ESPN_SITE}/sports/{sport}/{league}/teams/{team_id}"
        logger.info(f"Trying ESPN team overview: {url2}")
        data = await _fetch_json(url2)

        if data:
            logger.info(f"Got team overview data, top-level keys: {list(data.keys())}")
            result = _parse_team_stats(data)
            if result:
                return result

        # Fallback 2: API-Sports team stats (if configured)
        league_slug = _find_league_slug(sport, league)
        if league_slug and api_sports.is_available():
            logger.info(f"ESPN failed, trying API-Sports for team stats (league={league_slug})")
            api_result = await api_sports.get_team_stats(team_id, league_slug)
            if api_result:
                logger.info(f"Got team stats from API-Sports fallback")
                return api_result

        return None

    except Exception as e:
        logger.error(f"Error fetching team stats for {team_id}: {e}")
        return None


def _parse_team_stats(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Parse team stats from ESPN API response."""
    try:
        # Get team info from multiple possible locations
        team = data.get("team", {})
        if not team:
            teams_list = data.get("teams", [])
            if teams_list:
                team = teams_list[0]
                # Unwrap {"team": {...}} wrapper if present
                if "team" in team and isinstance(team["team"], dict):
                    team = team["team"]

        if not team.get("id") and not team.get("displayName"):
            return None

        result = {
            "id": team.get("id", ""),
            "name": team.get("displayName", ""),
            "abbreviation": team.get("abbreviation", ""),
            "logo": team.get("logo", ""),
            "stats": {},
        }

        # Extract record — use recordSummary/standingSummary if available
        record_summary = team.get("recordSummary", "")
        standing_summary = team.get("standingSummary", "")
        season_summary = team.get("seasonSummary", "")
        if record_summary:
            result["record_summary"] = record_summary
        if standing_summary:
            result["standing_summary"] = standing_summary
        if season_summary:
            result["season_summary"] = season_summary

        # Fallback: nested record object
        if not record_summary:
            record = team.get("record", {})
            if record:
                items = record.get("items", [])
                if items:
                    first_item = items[0] if isinstance(items[0], dict) else {}
                    summary = first_item.get("summary", "")
                    if summary:
                        result["record_summary"] = summary

        # ── Find statistics in multiple locations ─────────────────────────
        stats_list = []

        # Location 1: results.stats.categories (v2/statistics endpoint)
        # ESPN v2 format: {results: {stats: {categories: [{name, stats: [...]}]}}}
        results_obj = data.get("results", {})
        if isinstance(results_obj, dict):
            stats_obj = results_obj.get("stats", {})
            if isinstance(stats_obj, dict):
                cats = stats_obj.get("categories", [])
                if cats and isinstance(cats, list):
                    stats_list = cats
            elif isinstance(stats_obj, list) and stats_obj:
                # If results.stats is already a flat list of stat objects
                stats_list = [{"name": "Team Statistics", "stats": stats_obj}]

        # Location 2: root-level "splits" -> "categories"
        if not stats_list:
            splits = data.get("splits", {})
            if isinstance(splits, dict):
                stats_list = splits.get("categories", [])

        # Location 3: team-level "statistics"
        if not stats_list:
            stats_list = team.get("statistics", [])

        # Location 4: team-level "categories"
        if not stats_list:
            stats_list = team.get("categories", [])

        # Location 5: root-level "statistics"
        if not stats_list:
            stats_list = data.get("statistics", [])

        # Location 6: root-level "categories"
        if not stats_list:
            stats_list = data.get("categories", [])

        logger.info(f"Team stats: found {len(stats_list)} categories for {result.get('name', 'unknown')}")

        # Handle case where stats_list is a flat list of stat objects (not categorized)
        if stats_list and isinstance(stats_list[0], dict) and "value" in stats_list[0]:
            # Flat list — wrap as single category
            stats_list = [{"name": "Team Statistics", "stats": stats_list}]

        for stat_category in stats_list:
            try:
                category_name = (
                    stat_category.get("name", "")
                    or stat_category.get("displayName", "")
                    or stat_category.get("type", "")
                )
                if not category_name:
                    continue

                stats = []
                raw_stats = (
                    stat_category.get("stats", [])
                    or stat_category.get("statistics", [])
                )

                # Handle parallel arrays (labels + totals)
                labels = stat_category.get("labels", [])
                totals = stat_category.get("totals", [])
                display_names = stat_category.get("displayNames", [])

                if labels and totals and isinstance(totals, list) and totals and not isinstance(totals[0], dict):
                    for i, label in enumerate(labels):
                        if i < len(totals):
                            display = display_names[i] if i < len(display_names) else label
                            stats.append({
                                "name": label,
                                "displayName": display,
                                "value": str(totals[i]),
                                "rank": "",
                            })
                elif raw_stats and isinstance(raw_stats[0], dict):
                    for stat in raw_stats:
                        stats.append({
                            "name": stat.get("name", "") or stat.get("abbreviation", ""),
                            "displayName": stat.get("displayName", "") or stat.get("name", ""),
                            "value": str(stat.get("value", "")),
                            "displayValue": stat.get("displayValue", ""),
                            "rank": str(stat.get("rank", "")) if stat.get("rank") else "",
                        })

                if stats:
                    result["stats"][category_name] = stats

            except (KeyError, TypeError) as e:
                logger.debug(f"Error parsing team stat category: {e}")
                continue

        logger.info(f"Team stats parsed: {result.get('name')}, categories={list(result.get('stats', {}).keys())}")

        return result if result.get("name") else None

    except Exception as e:
        logger.error(f"Error parsing team stats: {e}", exc_info=True)
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# LEAGUE LEADERS
# ═══════════════════════════════════════════════════════════════════════════════

async def get_league_leaders(
    league_slug: str,
) -> Optional[Dict[str, Any]]:
    """
    Get league leaders / top performers.

    For soccer leagues: Uses API-Sports /players/topscorers and /players/topassists
    For NBA/NFL/MLB/NHL: Uses ESPN leaders endpoint

    Returns dict with:
        - league_name: str
        - categories: [{"name": "Points", "leaders": [{"name", "team", "value"}]}]
    """
    league_info = LEAGUES.get(league_slug)
    if not league_info:
        return None

    sport = league_info["sport"]
    league = league_info["league"]

    # ── Soccer: Use API-Sports top scorers / assists ─────────────────────
    if sport == "soccer" and api_sports.is_available():
        logger.info(f"Fetching soccer leaders from API-Sports for {league_slug}")
        result = {"league_name": league_info["name"], "categories": []}

        # Top scorers
        scorers = await api_sports.get_top_scorers(league_slug)
        if scorers:
            scorer_list = []
            for entry in scorers[:10]:
                player = entry.get("player", {})
                stats_list = entry.get("statistics", [])
                goals = 0
                team_name = ""
                if stats_list:
                    goals = stats_list[0].get("goals", {}).get("total", 0) or 0
                    team_name = stats_list[0].get("team", {}).get("name", "")
                scorer_list.append({
                    "name": player.get("name", ""),
                    "team": team_name,
                    "value": str(goals),
                    "stat_label": "Goals",
                })
            if scorer_list:
                result["categories"].append({
                    "name": "Top Scorers",
                    "emoji": "⚽",
                    "leaders": scorer_list,
                })

        # Top assists
        assists = await api_sports.get_top_assists(league_slug)
        if assists:
            assist_list = []
            for entry in assists[:10]:
                player = entry.get("player", {})
                stats_list = entry.get("statistics", [])
                assist_count = 0
                team_name = ""
                if stats_list:
                    assist_count = stats_list[0].get("goals", {}).get("assists", 0) or 0
                    team_name = stats_list[0].get("team", {}).get("name", "")
                assist_list.append({
                    "name": player.get("name", ""),
                    "team": team_name,
                    "value": str(assist_count),
                    "stat_label": "Assists",
                })
            if assist_list:
                result["categories"].append({
                    "name": "Top Assists",
                    "emoji": "🅰️",
                    "leaders": assist_list,
                })

        if result["categories"]:
            return result

    # ── NBA/NFL/MLB/NHL: Use ESPN leaders endpoint ───────────────────────
    try:
        url = f"{ESPN_SITE}/sports/{sport}/{league}/leaders"
        logger.info(f"Fetching leaders from ESPN: {url}")
        data = await _fetch_json(url)

        if not data:
            return None

        result = {"league_name": league_info["name"], "categories": []}

        # ESPN leaders format: {leaders: {categories: [{name, leaders: [{athlete, value}]}]}}
        leaders_data = data.get("leaders", {})
        categories = leaders_data.get("categories", [])

        if not categories:
            # Alternate format: root-level categories
            categories = data.get("categories", [])

        for cat in categories[:6]:  # Limit to 6 stat categories
            cat_name = cat.get("displayName", "") or cat.get("name", "")
            if not cat_name:
                continue

            leaders = cat.get("leaders", [])
            leader_list = []

            for leader in leaders[:10]:
                athlete = leader.get("athlete", {})
                if not athlete:
                    continue

                athlete_name = athlete.get("displayName", "")
                team_info = athlete.get("team", {})
                team_name = ""
                if isinstance(team_info, dict):
                    team_name = team_info.get("abbreviation", "") or team_info.get("displayName", "")

                value = leader.get("displayValue", "") or str(leader.get("value", ""))

                if athlete_name and value:
                    leader_list.append({
                        "name": athlete_name,
                        "team": team_name,
                        "value": value,
                        "stat_label": cat_name,
                    })

            if leader_list:
                result["categories"].append({
                    "name": cat_name,
                    "emoji": "🏆",
                    "leaders": leader_list,
                })

        return result if result["categories"] else None

    except Exception as e:
        logger.error(f"Error fetching leaders for {league_slug}: {e}")
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

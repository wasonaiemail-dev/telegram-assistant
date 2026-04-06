"""
API-Sports client — Multi-sport stats, scores, standings, and odds.

Provides async functions to fetch sports data from API-Sports (api-sports.io).
Supports NBA, NFL, MLB, NHL, and Soccer (EPL, MLS, Bundesliga, La Liga, World Cup).

Authentication: x-apisports-key header
Free tier: 100 requests/day per sport, all endpoints included.
Each sport uses its own subdomain and may use a different API version.

All functions return None on failure for clean failover to ESPN.
"""

import os
import logging
import aiohttp
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

API_SPORTS_KEY = os.environ.get("API_SPORTS_KEY", "")

# Timeout for all API requests
TIMEOUT = aiohttp.ClientTimeout(total=10)

# Base URLs per sport (each sport has its own subdomain and API version)
SPORT_BASES = {
    "nba":        "https://v2.nba.api-sports.io",
    "nfl":        "https://v1.american-football.api-sports.io",
    "mlb":        "https://v1.baseball.api-sports.io",
    "nhl":        "https://v1.hockey.api-sports.io",
    "soccer":     "https://v3.football.api-sports.io",
}

# Map our league slugs to API-Sports league IDs
# These are required parameters for most API-Sports endpoints
LEAGUE_IDS = {
    # NBA
    "nba":        {"base": "nba",    "league_id": 12,   "season": "2024-2025"},
    # NFL
    "nfl":        {"base": "nfl",    "league_id": 1,    "season": "2024"},
    # MLB
    "mlb":        {"base": "mlb",    "league_id": 1,    "season": "2024"},
    # NHL
    "nhl":        {"base": "nhl",    "league_id": 57,   "season": "2024"},
    # Soccer leagues
    "epl":        {"base": "soccer", "league_id": 39,   "season": "2024"},
    "mls":        {"base": "soccer", "league_id": 253,  "season": "2024"},
    "bundesliga": {"base": "soccer", "league_id": 78,   "season": "2024"},
    "laliga":     {"base": "soccer", "league_id": 140,  "season": "2024"},
}

# Which sports support player-level endpoints
# Hockey and Baseball only have team-level stats on API-Sports
PLAYER_SPORTS = {"nba", "nfl", "soccer"}


# ═══════════════════════════════════════════════════════════════════════════════
# HTTP CLIENT
# ═══════════════════════════════════════════════════════════════════════════════

async def _api_fetch(
    base_key: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Make an authenticated GET request to an API-Sports endpoint.

    Args:
        base_key: Key into SPORT_BASES (e.g., "nba", "nfl", "soccer")
        endpoint: Path after base URL (e.g., "/players", "/standings")
        params: Optional query parameters

    Returns:
        Parsed JSON dict on success, None on any failure.
        API-Sports wraps all responses in: {"get": ..., "parameters": ...,
        "errors": ..., "results": N, "response": [...]}
        We return the full wrapper so callers can check "results" count.
    """
    if not API_SPORTS_KEY:
        logger.debug("API_SPORTS_KEY not set, skipping API-Sports call")
        return None

    base_url = SPORT_BASES.get(base_key)
    if not base_url:
        logger.warning(f"Unknown sport base: {base_key}")
        return None

    url = f"{base_url}{endpoint}"
    headers = {
        "x-apisports-key": API_SPORTS_KEY,
    }

    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.get(url, headers=headers, params=params) as resp:
                # Log rate limit info
                remaining = resp.headers.get("x-ratelimit-requests-remaining", "?")
                logger.info(
                    f"API-Sports {base_key}{endpoint} → {resp.status} "
                    f"(remaining: {remaining})"
                )

                if resp.status != 200:
                    logger.warning(f"API-Sports returned {resp.status} for {url}")
                    return None

                data = await resp.json()

                # Check for API-level errors
                errors = data.get("errors", {})
                if errors:
                    # errors can be a dict or list
                    if isinstance(errors, dict) and errors:
                        logger.warning(f"API-Sports errors: {errors}")
                        return None
                    elif isinstance(errors, list) and errors:
                        logger.warning(f"API-Sports errors: {errors}")
                        return None

                return data

    except aiohttp.ClientError as e:
        logger.error(f"API-Sports request failed: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error in API-Sports request: {e}")
        return None


def _get_league_config(league_slug: str) -> Optional[Dict[str, Any]]:
    """Get the API-Sports config for a league slug."""
    return LEAGUE_IDS.get(league_slug.lower())


# ═══════════════════════════════════════════════════════════════════════════════
# PLAYER SEARCH
# ═══════════════════════════════════════════════════════════════════════════════

async def search_player(
    name: str,
    league_slug: str,
) -> Optional[List[Dict[str, Any]]]:
    """
    Search for a player by name in a specific league.

    NBA endpoint: GET /players?search={name}&season=2024-2025
    NFL endpoint: GET /players?search={name}&season=2024
    Soccer endpoint: GET /players?search={name}&league={id}&season=2024

    Returns list of players with id, name, team, position, etc.
    Returns None if no results or API unavailable.
    """
    if not name or not name.strip():
        return None

    config = _get_league_config(league_slug)
    if not config:
        return None

    base = config["base"]

    # Only NBA, NFL, and Soccer have player endpoints
    if base not in PLAYER_SPORTS:
        return None

    params = {"search": name.strip()}

    # Add season for context
    if config.get("season"):
        params["season"] = config["season"]

    # Soccer requires league_id for player search
    if base == "soccer":
        params["league"] = config["league_id"]

    data = await _api_fetch(base, "/players", params)
    if not data:
        return None

    results = []
    for player in data.get("response", []):
        try:
            player_info = player if base != "nba" else player

            # NBA format: {id, firstname, lastname, ...}
            # NFL format: {id, name, ...}
            # Soccer format: {player: {id, name, ...}, statistics: [...]}
            if base == "soccer":
                p = player.get("player", {})
                stats_list = player.get("statistics", [])
                team_name = ""
                position = ""
                if stats_list:
                    team_name = stats_list[0].get("team", {}).get("name", "")
                    games = stats_list[0].get("games", {})
                    position = games.get("position", "") if isinstance(games, dict) else ""
                results.append({
                    "id": str(p.get("id", "")),
                    "name": p.get("name", ""),
                    "team": team_name,
                    "position": position,
                    "source": "api_sports",
                })
            elif base == "nba":
                first = player_info.get("firstname", "")
                last = player_info.get("lastname", "")
                full_name = f"{first} {last}".strip()
                team = player_info.get("team", {})
                results.append({
                    "id": str(player_info.get("id", "")),
                    "name": full_name or player_info.get("name", ""),
                    "team": team.get("name", "") if isinstance(team, dict) else "",
                    "position": player_info.get("pos", ""),
                    "source": "api_sports",
                })
            elif base == "nfl":
                results.append({
                    "id": str(player_info.get("id", "")),
                    "name": player_info.get("name", ""),
                    "team": player_info.get("team", {}).get("name", "") if isinstance(player_info.get("team"), dict) else "",
                    "position": player_info.get("position", ""),
                    "source": "api_sports",
                })

        except (KeyError, TypeError) as e:
            logger.debug(f"Error parsing API-Sports player result: {e}")
            continue

    return results if results else None


# ═══════════════════════════════════════════════════════════════════════════════
# PLAYER STATISTICS
# ═══════════════════════════════════════════════════════════════════════════════

async def get_player_stats(
    player_id: str,
    league_slug: str,
) -> Optional[Dict[str, Any]]:
    """
    Get season statistics for a player.

    NBA: GET /players/statistics?id={player_id}&season=2024-2025
    NFL: GET /players/{id}/statistics?season=2024
    Soccer: GET /players?id={player_id}&season=2024

    Returns dict with player info and stats, or None.
    """
    if not player_id:
        return None

    config = _get_league_config(league_slug)
    if not config:
        return None

    base = config["base"]
    if base not in PLAYER_SPORTS:
        return None

    if base == "nba":
        params = {"id": player_id, "season": config["season"]}
        data = await _api_fetch(base, "/players/statistics", params)
        if not data or not data.get("response"):
            return None
        return _parse_nba_player_stats(data["response"])

    elif base == "nfl":
        params = {"season": config["season"]}
        data = await _api_fetch(base, f"/players/{player_id}/statistics", params)
        if not data or not data.get("response"):
            return None
        return _parse_nfl_player_stats(data["response"])

    elif base == "soccer":
        params = {"id": player_id, "season": config["season"]}
        data = await _api_fetch(base, "/players", params)
        if not data or not data.get("response"):
            return None
        return _parse_soccer_player_stats(data["response"])

    return None


def _parse_nba_player_stats(response: list) -> Optional[Dict[str, Any]]:
    """Parse NBA player statistics from API-Sports response."""
    if not response:
        return None

    # NBA /players/statistics returns a list of game stats
    # We need to aggregate or find season averages
    # The response is game-level stats, so we'll calculate averages
    games = response
    if not games:
        return None

    # Get player info from first game
    first = games[0]
    player = first.get("player", {})
    team = first.get("team", {})

    # Aggregate stats
    total_games = len(games)
    totals = {
        "points": 0, "rebounds": 0, "assists": 0, "steals": 0,
        "blocks": 0, "turnovers": 0, "fgm": 0, "fga": 0,
        "tpm": 0, "tpa": 0, "ftm": 0, "fta": 0, "minutes": 0,
    }

    for g in games:
        totals["points"] += g.get("points", 0) or 0
        totals["rebounds"] += (g.get("totReb", 0) or 0)
        totals["assists"] += g.get("assists", 0) or 0
        totals["steals"] += g.get("steals", 0) or 0
        totals["blocks"] += g.get("blocks", 0) or 0
        totals["turnovers"] += g.get("turnovers", 0) or 0
        totals["fgm"] += g.get("fgm", 0) or 0
        totals["fga"] += g.get("fga", 0) or 0
        totals["tpm"] += g.get("tpm", 0) or 0
        totals["tpa"] += g.get("tpa", 0) or 0
        totals["ftm"] += g.get("ftm", 0) or 0
        totals["fta"] += g.get("fta", 0) or 0
        mins = g.get("min", "0") or "0"
        # min can be "34:12" format
        if isinstance(mins, str) and ":" in mins:
            parts = mins.split(":")
            totals["minutes"] += int(parts[0]) + int(parts[1]) / 60
        else:
            totals["minutes"] += float(mins) if mins else 0

    if total_games == 0:
        return None

    avg = {k: round(v / total_games, 1) for k, v in totals.items()}
    fg_pct = round(totals["fgm"] / totals["fga"] * 100, 1) if totals["fga"] else 0
    tp_pct = round(totals["tpm"] / totals["tpa"] * 100, 1) if totals["tpa"] else 0
    ft_pct = round(totals["ftm"] / totals["fta"] * 100, 1) if totals["fta"] else 0

    return {
        "source": "api_sports",
        "name": f"{player.get('firstname', '')} {player.get('lastname', '')}".strip(),
        "team": team.get("name", ""),
        "position": first.get("pos", ""),
        "games_played": total_games,
        "stats": {
            "Season Averages": [
                {"name": "PPG", "displayName": "Points Per Game", "value": str(avg["points"])},
                {"name": "RPG", "displayName": "Rebounds Per Game", "value": str(avg["rebounds"])},
                {"name": "APG", "displayName": "Assists Per Game", "value": str(avg["assists"])},
                {"name": "SPG", "displayName": "Steals Per Game", "value": str(avg["steals"])},
                {"name": "BPG", "displayName": "Blocks Per Game", "value": str(avg["blocks"])},
                {"name": "TPG", "displayName": "Turnovers Per Game", "value": str(avg["turnovers"])},
                {"name": "MPG", "displayName": "Minutes Per Game", "value": str(avg["minutes"])},
                {"name": "FG%", "displayName": "Field Goal %", "value": f"{fg_pct}%"},
                {"name": "3P%", "displayName": "Three Point %", "value": f"{tp_pct}%"},
                {"name": "FT%", "displayName": "Free Throw %", "value": f"{ft_pct}%"},
            ],
        },
    }


def _parse_nfl_player_stats(response: list) -> Optional[Dict[str, Any]]:
    """Parse NFL player statistics from API-Sports response."""
    if not response:
        return None

    # NFL returns categorized stats per team per season
    result_stats = {}
    player_name = ""
    team_name = ""

    for entry in response:
        team = entry.get("team", {})
        if not team_name:
            team_name = team.get("name", "")

        # Each entry has category groups (passing, rushing, receiving, etc.)
        for category_key in ["passing", "rushing", "receiving", "defensive",
                             "kick_returns", "punt_returns", "kicking", "punting"]:
            cat_data = entry.get(category_key)
            if not cat_data or not isinstance(cat_data, dict):
                continue

            stats = []
            for stat_name, stat_value in cat_data.items():
                if stat_value is not None and stat_name not in ("player",):
                    display = stat_name.replace("_", " ").title()
                    stats.append({
                        "name": stat_name,
                        "displayName": display,
                        "value": str(stat_value),
                    })

                    # Extract player name from nested player object
                    if stat_name == "player" and isinstance(stat_value, dict):
                        player_name = stat_value.get("name", "")

            if stats:
                result_stats[category_key.title()] = stats

    if not result_stats:
        return None

    return {
        "source": "api_sports",
        "name": player_name,
        "team": team_name,
        "stats": result_stats,
    }


def _parse_soccer_player_stats(response: list) -> Optional[Dict[str, Any]]:
    """Parse soccer player statistics from API-Sports response."""
    if not response:
        return None

    entry = response[0]
    player = entry.get("player", {})
    stats_list = entry.get("statistics", [])

    if not stats_list:
        return None

    # Take most recent league stats
    stat = stats_list[0]
    team_name = stat.get("team", {}).get("name", "")
    games = stat.get("games", {})
    goals = stat.get("goals", {})
    passes = stat.get("passes", {})
    tackles = stat.get("tackles", {})
    shots = stat.get("shots", {})
    cards = stat.get("cards", {})

    result_stats = []
    if games.get("appearences"):
        result_stats.append({"name": "Apps", "displayName": "Appearances", "value": str(games["appearences"])})
    if games.get("minutes"):
        result_stats.append({"name": "MIN", "displayName": "Minutes", "value": str(games["minutes"])})
    if goals.get("total") is not None:
        result_stats.append({"name": "G", "displayName": "Goals", "value": str(goals["total"] or 0)})
    if goals.get("assists") is not None:
        result_stats.append({"name": "A", "displayName": "Assists", "value": str(goals["assists"] or 0)})
    if passes.get("total"):
        result_stats.append({"name": "PASS", "displayName": "Passes", "value": str(passes["total"])})
    if passes.get("accuracy"):
        result_stats.append({"name": "PASS%", "displayName": "Pass Accuracy", "value": f"{passes['accuracy']}%"})
    if shots.get("total"):
        result_stats.append({"name": "SH", "displayName": "Shots", "value": str(shots["total"])})
    if shots.get("on"):
        result_stats.append({"name": "SOT", "displayName": "Shots on Target", "value": str(shots["on"])})
    if tackles.get("total"):
        result_stats.append({"name": "TKL", "displayName": "Tackles", "value": str(tackles["total"])})
    if cards.get("yellow"):
        result_stats.append({"name": "YC", "displayName": "Yellow Cards", "value": str(cards["yellow"])})
    if cards.get("red"):
        result_stats.append({"name": "RC", "displayName": "Red Cards", "value": str(cards["red"])})

    return {
        "source": "api_sports",
        "name": player.get("name", ""),
        "team": team_name,
        "position": games.get("position", ""),
        "stats": {"Season Stats": result_stats} if result_stats else {},
    }


# ═══════════════════════════════════════════════════════════════════════════════
# TEAM STATISTICS
# ═══════════════════════════════════════════════════════════════════════════════

async def get_team_stats(
    team_id: str,
    league_slug: str,
) -> Optional[Dict[str, Any]]:
    """
    Get team statistics for a season.

    NBA: GET /teams/statistics?id={team_id}&season=2024-2025
    NFL: Game-level stats (not a direct endpoint)
    MLB: GET /teams/statistics?league={id}&season=2024&team={team_id}
    NHL: GET /teams/statistics?league={id}&season=2024&team={team_id}
    Soccer: GET /teams/statistics?league={id}&season=2024&team={team_id}

    Returns dict with team info and stats, or None.
    """
    if not team_id:
        return None

    config = _get_league_config(league_slug)
    if not config:
        return None

    base = config["base"]

    if base == "nba":
        params = {"id": team_id, "season": config["season"]}
        data = await _api_fetch(base, "/teams/statistics", params)
    elif base == "soccer":
        params = {
            "league": config["league_id"],
            "season": config["season"],
            "team": team_id,
        }
        data = await _api_fetch(base, "/teams/statistics", params)
    elif base in ("mlb", "nhl"):
        params = {
            "league": config["league_id"],
            "season": config["season"],
            "team": team_id,
        }
        data = await _api_fetch(base, "/teams/statistics", params)
    elif base == "nfl":
        # NFL doesn't have a direct team statistics endpoint;
        # team stats come from game-level aggregation
        # Fall through to return None — ESPN handles this
        return None
    else:
        return None

    if not data or not data.get("response"):
        return None

    return _parse_team_stats(data["response"], base, league_slug)


def _parse_team_stats(
    response: list,
    base: str,
    league_slug: str,
) -> Optional[Dict[str, Any]]:
    """Parse team statistics from API-Sports response (sport-specific)."""
    if not response:
        return None

    if base == "soccer":
        return _parse_soccer_team_stats(response)
    elif base == "nba":
        return _parse_nba_team_stats(response)
    elif base in ("mlb", "nhl"):
        return _parse_generic_team_stats(response, base)

    return None


def _parse_nba_team_stats(response: list) -> Optional[Dict[str, Any]]:
    """Parse NBA team statistics."""
    if not response:
        return None

    # NBA team stats response is a list of stat objects
    stats = response[0] if response else {}
    if not stats:
        return None

    team = stats.get("team", {})
    result_stats = []

    # Extract key stats
    stat_keys = [
        ("points", "PPG", "Points Per Game"),
        ("fgm", "FGM", "Field Goals Made"),
        ("fga", "FGA", "Field Goals Attempted"),
        ("fgp", "FG%", "Field Goal %"),
        ("tpm", "3PM", "Three Pointers Made"),
        ("tpa", "3PA", "Three Pointers Attempted"),
        ("tpp", "3P%", "Three Point %"),
        ("ftm", "FTM", "Free Throws Made"),
        ("fta", "FTA", "Free Throws Attempted"),
        ("ftp", "FT%", "Free Throw %"),
        ("totReb", "REB", "Rebounds"),
        ("assists", "AST", "Assists"),
        ("steals", "STL", "Steals"),
        ("blocks", "BLK", "Blocks"),
        ("turnovers", "TO", "Turnovers"),
    ]

    for key, abbrev, display in stat_keys:
        val = stats.get(key)
        if val is not None:
            result_stats.append({
                "name": abbrev,
                "displayName": display,
                "value": str(val),
            })

    return {
        "source": "api_sports",
        "name": team.get("name", ""),
        "id": str(team.get("id", "")),
        "stats": {"Team Statistics": result_stats} if result_stats else {},
    }


def _parse_soccer_team_stats(response: dict) -> Optional[Dict[str, Any]]:
    """Parse soccer team statistics."""
    # Soccer team stats response is a single dict (not a list)
    stats = response if isinstance(response, dict) else (response[0] if response else {})
    if not stats:
        return None

    team = stats.get("team", {})
    league = stats.get("league", {})
    fixtures = stats.get("fixtures", {})
    goals_for = stats.get("goals", {}).get("for", {})
    goals_against = stats.get("goals", {}).get("against", {})

    result_stats = []

    # Record
    played = fixtures.get("played", {})
    wins = fixtures.get("wins", {})
    draws = fixtures.get("draws", {})
    losses = fixtures.get("loses", {})

    if played.get("total"):
        result_stats.append({"name": "GP", "displayName": "Games Played", "value": str(played["total"])})
    if wins.get("total") is not None:
        result_stats.append({"name": "W", "displayName": "Wins", "value": str(wins["total"])})
    if draws.get("total") is not None:
        result_stats.append({"name": "D", "displayName": "Draws", "value": str(draws["total"])})
    if losses.get("total") is not None:
        result_stats.append({"name": "L", "displayName": "Losses", "value": str(losses["total"])})

    gf_total = goals_for.get("total", {}).get("total")
    ga_total = goals_against.get("total", {}).get("total")
    if gf_total is not None:
        result_stats.append({"name": "GF", "displayName": "Goals For", "value": str(gf_total)})
    if ga_total is not None:
        result_stats.append({"name": "GA", "displayName": "Goals Against", "value": str(ga_total)})

    clean_sheets = stats.get("clean_sheet", {})
    if clean_sheets.get("total") is not None:
        result_stats.append({"name": "CS", "displayName": "Clean Sheets", "value": str(clean_sheets["total"])})

    return {
        "source": "api_sports",
        "name": team.get("name", ""),
        "id": str(team.get("id", "")),
        "logo": team.get("logo", ""),
        "stats": {"Season Stats": result_stats} if result_stats else {},
    }


def _parse_generic_team_stats(response: list, base: str) -> Optional[Dict[str, Any]]:
    """Parse team stats for MLB/NHL (similar structure)."""
    if not response:
        return None

    # These sports return grouped stats
    entry = response[0] if isinstance(response, list) else response
    if not entry:
        return None

    team = entry.get("team", {})
    result_stats = []

    # Generic: iterate all top-level stat keys
    skip_keys = {"team", "league", "country", "season", "games"}
    for key, val in entry.items():
        if key in skip_keys:
            continue
        if isinstance(val, dict):
            # Nested category (e.g., goals: {for: 5, against: 3})
            for sub_key, sub_val in val.items():
                if sub_val is not None and not isinstance(sub_val, dict):
                    display = f"{key.title()} {sub_key.title()}"
                    result_stats.append({
                        "name": f"{key}_{sub_key}",
                        "displayName": display,
                        "value": str(sub_val),
                    })
        elif val is not None and not isinstance(val, (list, dict)):
            result_stats.append({
                "name": key,
                "displayName": key.replace("_", " ").title(),
                "value": str(val),
            })

    return {
        "source": "api_sports",
        "name": team.get("name", ""),
        "id": str(team.get("id", "")),
        "stats": {"Team Statistics": result_stats} if result_stats else {},
    }


# ═══════════════════════════════════════════════════════════════════════════════
# STANDINGS
# ═══════════════════════════════════════════════════════════════════════════════

async def get_standings(
    league_slug: str,
) -> Optional[List[Dict[str, Any]]]:
    """
    Get league standings.

    NBA: GET /standings?league={id}&season=2024-2025
    NFL: GET /standings?league={id}&season=2024
    Soccer: GET /standings?league={id}&season=2024

    Returns list of team standings, or None.
    """
    config = _get_league_config(league_slug)
    if not config:
        return None

    base = config["base"]
    params = {
        "league": config["league_id"],
        "season": config["season"],
    }

    data = await _api_fetch(base, "/standings", params)
    if not data or not data.get("response"):
        return None

    return data["response"]


# ═══════════════════════════════════════════════════════════════════════════════
# GAMES / SCORES
# ═══════════════════════════════════════════════════════════════════════════════

async def get_games(
    league_slug: str,
    date: Optional[str] = None,
    team_id: Optional[str] = None,
    live: bool = False,
) -> Optional[List[Dict[str, Any]]]:
    """
    Get games/fixtures for a league.

    Args:
        league_slug: League slug (e.g., "nba", "epl")
        date: Optional date filter (YYYY-MM-DD)
        team_id: Optional team ID filter
        live: If True, get only live games

    Returns list of game objects, or None.
    """
    config = _get_league_config(league_slug)
    if not config:
        return None

    base = config["base"]

    # Soccer uses /fixtures, others use /games
    endpoint = "/fixtures" if base == "soccer" else "/games"

    params = {
        "league": config["league_id"],
        "season": config["season"],
    }

    if date:
        params["date"] = date
    if team_id:
        params["team"] = team_id
    if live:
        params["live"] = "all"

    data = await _api_fetch(base, endpoint, params)
    if not data or not data.get("response"):
        return None

    return data["response"]


# ═══════════════════════════════════════════════════════════════════════════════
# LEAGUE LEADERS (Soccer only — API-Sports has Top Scorers/Assists for football)
# ═══════════════════════════════════════════════════════════════════════════════

async def get_top_scorers(
    league_slug: str,
) -> Optional[List[Dict[str, Any]]]:
    """
    Get top scorers for a soccer league.

    Soccer only: GET /players/topscorers?league={id}&season=2024

    Returns list of player objects with goals, or None.
    """
    config = _get_league_config(league_slug)
    if not config or config["base"] != "soccer":
        return None

    params = {
        "league": config["league_id"],
        "season": config["season"],
    }

    data = await _api_fetch("soccer", "/players/topscorers", params)
    if not data or not data.get("response"):
        return None

    return data["response"]


async def get_top_assists(
    league_slug: str,
) -> Optional[List[Dict[str, Any]]]:
    """
    Get top assist providers for a soccer league.

    Soccer only: GET /players/topassists?league={id}&season=2024
    """
    config = _get_league_config(league_slug)
    if not config or config["base"] != "soccer":
        return None

    params = {
        "league": config["league_id"],
        "season": config["season"],
    }

    data = await _api_fetch("soccer", "/players/topassists", params)
    if not data or not data.get("response"):
        return None

    return data["response"]


# ═══════════════════════════════════════════════════════════════════════════════
# ODDS (NFL, MLB, NHL, Soccer — not NBA)
# ═══════════════════════════════════════════════════════════════════════════════

async def get_odds(
    league_slug: str,
    game_id: Optional[str] = None,
) -> Optional[List[Dict[str, Any]]]:
    """
    Get betting odds for a league's games.

    NFL: GET /odds?game={game_id}
    Soccer: GET /odds?fixture={fixture_id}

    Returns list of odds objects, or None.
    NBA does NOT have odds on API-Sports (use The-Odds-API instead).
    """
    config = _get_league_config(league_slug)
    if not config:
        return None

    base = config["base"]

    # NBA doesn't have odds on API-Sports
    if base == "nba":
        return None

    if base == "soccer":
        params = {}
        if game_id:
            params["fixture"] = game_id
        else:
            params["league"] = config["league_id"]
            params["season"] = config["season"]
        data = await _api_fetch(base, "/odds", params)
    else:
        params = {}
        if game_id:
            params["game"] = game_id
        data = await _api_fetch(base, "/odds", params)

    if not data or not data.get("response"):
        return None

    return data["response"]


# ═══════════════════════════════════════════════════════════════════════════════
# TEAM SEARCH
# ═══════════════════════════════════════════════════════════════════════════════

async def search_team(
    name: str,
    league_slug: str,
) -> Optional[List[Dict[str, Any]]]:
    """
    Search for a team by name in a specific league.

    NBA: GET /teams?search={name}
    NFL: GET /teams?search={name}
    Soccer: GET /teams?search={name}
    NHL/MLB: GET /teams?search={name}

    Returns list of matching teams, or None.
    """
    if not name or not name.strip():
        return None

    config = _get_league_config(league_slug)
    if not config:
        return None

    base = config["base"]
    params = {"search": name.strip()}

    # Some sports need league filter
    if base == "soccer":
        params["league"] = config["league_id"]
        params["season"] = config["season"]

    data = await _api_fetch(base, "/teams", params)
    if not data or not data.get("response"):
        return None

    results = []
    for entry in data["response"]:
        try:
            if base == "soccer":
                team = entry.get("team", entry)
            else:
                team = entry

            results.append({
                "id": str(team.get("id", "")),
                "name": team.get("name", ""),
                "logo": team.get("logo", ""),
                "source": "api_sports",
            })
        except (KeyError, TypeError):
            continue

    return results if results else None


# ═══════════════════════════════════════════════════════════════════════════════
# UTILITY: Check if API-Sports is available
# ═══════════════════════════════════════════════════════════════════════════════

def is_available() -> bool:
    """Check if API-Sports key is configured."""
    return bool(API_SPORTS_KEY)


def has_player_stats(league_slug: str) -> bool:
    """Check if a league supports player-level stats on API-Sports."""
    config = _get_league_config(league_slug)
    if not config:
        return False
    return config["base"] in PLAYER_SPORTS

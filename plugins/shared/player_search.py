"""
Shared Player Search Module — unified player/team lookup for all plugins.

Consolidates the search → resolve league → fetch stats pattern that was
previously duplicated across commands.py and dispatch.py.

Usage from any plugin:

    from plugins.shared.player_search import (
        search_and_resolve_player,
        resolve_player_league,
        map_league_name_to_slug,
        extract_name_from_query,
    )

    # Full pipeline: search + resolve in one call
    player, league_slug, league_info = await search_and_resolve_player("LeBron James")

    # Or step by step:
    results = await stats_api.search_player("LeBron")
    league_slug = resolve_player_league(results[0])
"""

import logging
from typing import Optional, Tuple, Dict, Any, List

from plugins.sports import stats_api
from plugins.sports import config as sports_config

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# LEAGUE NAME MAPPING
# ═══════════════════════════════════════════════════════════════════════════════

# ESPN league display names → our internal league slugs
_LEAGUE_NAME_MAP = {
    "nba": "nba",
    "nfl": "nfl",
    "mlb": "mlb",
    "major league baseball": "mlb",
    "nhl": "nhl",
    "ncaaf": "ncaaf",
    "college football": "ncaaf",
    "ncaab": "ncaab",
    "college basketball": "ncaab",
    "mens college basketball": "ncaab",
    "men's college basketball": "ncaab",
    "epl": "epl",
    "premier league": "epl",
    "english premier league": "epl",
    "mls": "mls",
    "bundesliga": "bundesliga",
    "laliga": "laliga",
    "la liga": "laliga",
}

# Sport field → default league slug (fallback when ESPN doesn't return league)
_SPORT_TO_LEAGUE = {
    "football": "nfl",
    "basketball": "nba",
    "baseball": "mlb",
    "hockey": "nhl",
    "soccer": "epl",
}


def map_league_name_to_slug(league_name: str) -> Optional[str]:
    """
    Map ESPN league display names to internal league slugs.

    ESPN returns league names like "NBA", "Major League Baseball", etc.
    This maps them to our slug format: "nba", "mlb", etc.

    Args:
        league_name: ESPN league name string

    Returns:
        League slug or None if unrecognized.
    """
    if not league_name:
        return None
    return _LEAGUE_NAME_MAP.get(league_name.lower().strip())


# ═══════════════════════════════════════════════════════════════════════════════
# PLAYER LEAGUE RESOLUTION
# ═══════════════════════════════════════════════════════════════════════════════

def resolve_player_league(player: Dict[str, Any], default: str = "nba") -> str:
    """
    Determine the league slug for a player search result.

    Tries in order:
      1. player["league"] → map_league_name_to_slug
      2. player["sport"]  → _SPORT_TO_LEAGUE mapping
      3. default fallback

    Args:
        player: Player dict from stats_api.search_player()
        default: Fallback league slug if resolution fails

    Returns:
        League slug string (e.g., "nba", "nfl")
    """
    # Try league field first
    league_raw = player.get("league") or ""
    if league_raw:
        slug = map_league_name_to_slug(league_raw)
        if slug:
            return slug

    # Try sport field
    sport_val = (player.get("sport") or "").lower()
    for keyword, slug in _SPORT_TO_LEAGUE.items():
        if keyword in sport_val:
            return slug

    return default


def get_player_league_info(
    player: Dict[str, Any],
    default: str = "nba",
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    Resolve a player's league slug AND league info dict in one call.

    Args:
        player: Player dict from search results
        default: Fallback league slug

    Returns:
        (league_slug, league_info) tuple. league_info may be None if slug
        doesn't match any configured league.
    """
    slug = resolve_player_league(player, default)
    info = sports_config.get_league_info(slug)
    return slug, info


# ═══════════════════════════════════════════════════════════════════════════════
# SEARCH + RESOLVE PIPELINE
# ═══════════════════════════════════════════════════════════════════════════════

async def search_and_resolve_player(
    name: str,
    default_league: str = "nba",
) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[Dict[str, Any]]]:
    """
    Search for a player by name and resolve their league in one call.

    This is the most common pattern across all sports commands:
      1. Search ESPN for player by name
      2. If exactly one result, resolve their league
      3. Return (player, league_slug, league_info)

    Args:
        name: Player name to search for
        default_league: Fallback league if ESPN doesn't specify

    Returns:
        (player_dict, league_slug, league_info) if exactly one match found.
        (None, None, None) if no results.

    Note: If multiple results are found, returns the FIRST match.
          Callers that want to show disambiguation should use
          stats_api.search_player() directly and handle multiple results.
    """
    if not name or not name.strip():
        return None, None, None

    results = await stats_api.search_player(name)
    if not results:
        return None, None, None

    player = results[0]
    slug, info = get_player_league_info(player, default_league)

    return player, slug, info


async def search_and_resolve_players(
    name: str,
    default_league: str = "nba",
) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str], Optional[Dict[str, Any]]]:
    """
    Search for a player, return ALL results plus league info of the first match.

    Use this when you want to show disambiguation (multiple results) but still
    need league info for the top result.

    Args:
        name: Player name to search for
        default_league: Fallback league

    Returns:
        (results_list, first_league_slug, first_league_info) or (None, None, None)
    """
    if not name or not name.strip():
        return None, None, None

    results = await stats_api.search_player(name)
    if not results:
        return None, None, None

    first = results[0]
    slug, info = get_player_league_info(first, default_league)

    return results, slug, info


# ═══════════════════════════════════════════════════════════════════════════════
# NL NAME EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════════

# Words to strip when extracting player/team names from natural language
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
    "leaders", "leader", "leading", "top", "best", "compare", "vs",
    "versus", "or", "better", "worse", "than",
}


def extract_name_from_query(query: str) -> str:
    """
    Extract a likely player or team name from a natural language query.

    Strips common stop words and returns the remaining words joined
    as a name string.

    Examples:
        "what are LeBron's stats"       -> "LeBron"
        "show me stats for Patrick Mahomes" -> "Patrick Mahomes"
        "how is Ohtani doing"           -> "Ohtani"
        "compare LeBron vs Durant"      -> "LeBron Durant"

    Args:
        query: Raw natural language text

    Returns:
        Extracted name string (may be empty if nothing remains).
    """
    if not query:
        return ""

    # Remove possessives
    cleaned = query.replace("\u2019s", "").replace("'s", "")
    words = cleaned.split()

    # Filter out stop words, keeping capitalized/unknown words
    name_parts = []
    for w in words:
        w_lower = w.lower().strip("?!.,")
        if w_lower in _STOP_WORDS:
            continue
        if w_lower.isdigit():
            continue
        name_parts.append(w.strip("?!.,"))

    return " ".join(name_parts).strip()

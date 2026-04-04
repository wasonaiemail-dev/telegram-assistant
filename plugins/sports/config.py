"""
Sports plugin configuration and helpers.

Defines league mappings, ESPN API endpoints, and user settings management.
"""

import os
import json
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# LEAGUE DEFINITIONS
# ═══════════════════════════════════════════════════════════════════════════════

LEAGUES = {
    "nfl": {
        "name": "NFL",
        "sport": "football",
        "league": "nfl",
        "emoji": "🏈",
        "season": 2024,
    },
    "nba": {
        "name": "NBA",
        "sport": "basketball",
        "league": "nba",
        "emoji": "🏀",
        "season": 2024,
    },
    "mlb": {
        "name": "MLB",
        "sport": "baseball",
        "league": "mlb",
        "emoji": "⚾",
        "season": 2024,
    },
    "nhl": {
        "name": "NHL",
        "sport": "hockey",
        "league": "nhl",
        "emoji": "🏒",
        "season": 2024,
    },
    "ncaaf": {
        "name": "NCAAF",
        "sport": "football",
        "league": "college-football",
        "emoji": "🏈",
        "season": 2024,
    },
    "ncaab": {
        "name": "NCAAB",
        "sport": "basketball",
        "league": "mens-college-basketball",
        "emoji": "🏀",
        "season": 2024,
    },
    "epl": {
        "name": "EPL",
        "sport": "soccer",
        "league": "eng.1",
        "emoji": "⚽",
        "season": 2024,
    },
    "mls": {
        "name": "MLS",
        "sport": "soccer",
        "league": "usa.1",
        "emoji": "⚽",
        "season": 2024,
    },
    "bundesliga": {
        "name": "Bundesliga",
        "sport": "soccer",
        "league": "ger.1",
        "emoji": "⚽",
        "season": 2024,
    },
    "laliga": {
        "name": "La Liga",
        "sport": "soccer",
        "league": "esp.1",
        "emoji": "⚽",
        "season": 2024,
    },
}

# Short aliases for user convenience
LEAGUE_ALIASES = {
    "nfl": "nfl",
    "football": "nfl",
    "nba": "nba",
    "basketball": "nba",
    "mlb": "mlb",
    "baseball": "mlb",
    "nhl": "nhl",
    "hockey": "nhl",
    "ncaaf": "ncaaf",
    "college": "ncaaf",
    "ncaab": "ncaab",
    "college hoops": "ncaab",
    "epl": "epl",
    "premier league": "epl",
    "mls": "mls",
    "bundesliga": "bundesliga",
    "laliga": "laliga",
    "la liga": "laliga",
    "spanish": "laliga",
}

# ═══════════════════════════════════════════════════════════════════════════════
# ESPN API ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

ESPN_BASE = "https://site.api.espn.com/apis"
ESPN_SITE = f"{ESPN_BASE}/site/v2"
ESPN_API = f"{ESPN_BASE}/v2"


def get_scoreboard_url(sport: str, league: str) -> str:
    """Get the scoreboard/scores endpoint for a league."""
    return f"{ESPN_SITE}/sports/{sport}/{league}/scoreboard"


def get_standings_url(sport: str, league: str) -> str:
    """Get the standings endpoint for a league."""
    return f"{ESPN_API}/sports/{sport}/{league}/standings"


def get_schedule_url(sport: str, league: str) -> str:
    """Get the schedule endpoint for a league."""
    return f"{ESPN_SITE}/sports/{sport}/{league}/scoreboard"


def get_teams_url(sport: str, league: str) -> str:
    """Get the teams list endpoint for a league."""
    return f"{ESPN_SITE}/sports/{sport}/{league}/teams"


def get_team_detail_url(sport: str, league: str, team_id: str) -> str:
    """Get the team detail endpoint for a specific team."""
    return f"{ESPN_SITE}/sports/{sport}/{league}/teams/{team_id}"


# ═══════════════════════════════════════════════════════════════════════════════
# DATA FILE PATHS
# ═══════════════════════════════════════════════════════════════════════════════

PERSIST_DIR = "/data" if os.path.isdir("/data") else "/tmp"
SPORTS_PLUGIN_DIR = os.path.join(PERSIST_DIR, "sports_plugin")

# Create sports plugin data directory
os.makedirs(SPORTS_PLUGIN_DIR, exist_ok=True)

SPORTS_SETTINGS_FILE = os.path.join(SPORTS_PLUGIN_DIR, "settings.json")
BET_HISTORY_FILE = os.path.join(SPORTS_PLUGIN_DIR, "bets.json")
TEAM_CACHE_FILE = os.path.join(SPORTS_PLUGIN_DIR, "teams_cache.json")
GAME_ALERTS_FILE = os.path.join(SPORTS_PLUGIN_DIR, "game_alerts.json")


# ═══════════════════════════════════════════════════════════════════════════════
# SETTINGS MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════════

def get_default_settings() -> Dict[str, Any]:
    """Return default user settings for sports plugin."""
    return {
        "favorite_teams": [],  # List of {league, team_id, team_name}
        "favorite_leagues": [],  # List of league slugs to follow
        "alerts_enabled": True,
        "bankroll": 0.0,
        "unit_size": 0.0,
        "kelly_fraction": 0.25,
        "min_odds": -110,  # Minimum acceptable odds
    }


def load_sports_settings() -> Dict[str, Any]:
    """Load user settings from file, or return defaults if not exists."""
    if not os.path.exists(SPORTS_SETTINGS_FILE):
        return get_default_settings()

    try:
        with open(SPORTS_SETTINGS_FILE, "r") as f:
            settings = json.load(f)
            # Merge with defaults to ensure all keys exist
            defaults = get_default_settings()
            defaults.update(settings)
            return defaults
    except Exception as e:
        logger.error(f"Failed to load sports settings: {e}")
        return get_default_settings()


def save_sports_settings(settings: Dict[str, Any]) -> bool:
    """Save user settings to file. Returns True on success."""
    try:
        with open(SPORTS_SETTINGS_FILE, "w") as f:
            json.dump(settings, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Failed to save sports settings: {e}")
        return False


def add_favorite_team(league: str, team_id: str, team_name: str) -> bool:
    """Add a team to user's favorites."""
    settings = load_sports_settings()
    # Check if already exists
    for team in settings.get("favorite_teams", []):
        if team["league"] == league and team["team_id"] == team_id:
            return True  # Already added
    settings["favorite_teams"].append({
        "league": league,
        "team_id": team_id,
        "team_name": team_name,
    })
    return save_sports_settings(settings)


def remove_favorite_team(league: str, team_id: str) -> bool:
    """Remove a team from favorites."""
    settings = load_sports_settings()
    settings["favorite_teams"] = [
        t for t in settings.get("favorite_teams", [])
        if not (t["league"] == league and t["team_id"] == team_id)
    ]
    return save_sports_settings(settings)


def get_favorite_teams(league: Optional[str] = None) -> list:
    """Get user's favorite teams, optionally filtered by league."""
    settings = load_sports_settings()
    teams = settings.get("favorite_teams", [])
    if league:
        teams = [t for t in teams if t["league"] == league]
    return teams


def set_alerts_enabled(enabled: bool) -> bool:
    """Toggle game alerts on/off."""
    settings = load_sports_settings()
    settings["alerts_enabled"] = enabled
    return save_sports_settings(settings)


def set_bankroll(bankroll: float, unit_size: float = 0.0) -> bool:
    """Set user's betting bankroll and unit size."""
    settings = load_sports_settings()
    settings["bankroll"] = float(bankroll)
    if unit_size > 0:
        settings["unit_size"] = float(unit_size)
    return save_sports_settings(settings)


def add_favorite_league(league: str) -> bool:
    """Add a league to user's favorites."""
    settings = load_sports_settings()
    if league not in settings.get("favorite_leagues", []):
        settings["favorite_leagues"].append(league)
        return save_sports_settings(settings)
    return True


def remove_favorite_league(league: str) -> bool:
    """Remove a league from favorites."""
    settings = load_sports_settings()
    leagues = settings.get("favorite_leagues", [])
    settings["favorite_leagues"] = [l for l in leagues if l != league]
    return save_sports_settings(settings)


# ═══════════════════════════════════════════════════════════════════════════════
# UTILITY FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def normalize_league(league_str: str) -> Optional[str]:
    """
    Normalize a league string to the standard slug.

    Examples:
      "nfl" -> "nfl"
      "football" -> "nfl"
      "NBA" -> "nba"
      "premier league" -> "epl"

    Returns None if no match found.
    """
    normalized = league_str.lower().strip()
    return LEAGUE_ALIASES.get(normalized)


def get_league_info(league_slug: str) -> Optional[Dict[str, Any]]:
    """Get league info by slug."""
    return LEAGUES.get(league_slug.lower())


def get_league_emoji(league_slug: str) -> str:
    """Get the emoji for a league."""
    info = get_league_info(league_slug)
    return info.get("emoji", "🏆") if info else "🏆"

"""
Bet tracking and data persistence for sports plugin.

Bet model:
    {
        "id": "bet_uuid",
        "date": "2024-01-15T14:30:00Z",
        "league": "NFL",
        "game": "Away vs Home",
        "bet_type": "moneyline|spread|over_under|parlay",
        "pick": "Team Name or prediction",
        "odds": -110,  # Negative = favorite, positive = underdog
        "stake": 50.0,  # Wager amount in units or dollars
        "result": "win|loss|push|pending",
        "pnl": 45.45,  # Profit/loss (negative if loss)
        "unit_size": 1.0,  # Unit size used
        "notes": "Optional notes"
    }
"""

import json
import logging
import uuid
from typing import Dict, Any, List, Optional
from datetime import datetime

from plugins.sports.config import BET_HISTORY_FILE

logger = logging.getLogger(__name__)


def get_default_bet() -> Dict[str, Any]:
    """Return a blank bet template."""
    return {
        "id": "",
        "date": "",
        "league": "",
        "game": "",
        "bet_type": "moneyline",
        "pick": "",
        "odds": 0,
        "stake": 0.0,
        "result": "pending",
        "pnl": 0.0,
        "unit_size": 1.0,
        "notes": "",
    }


def load_bet_history() -> List[Dict[str, Any]]:
    """Load all bets from file. Returns empty list if file doesn't exist."""
    if not __import__("os").path.exists(BET_HISTORY_FILE):
        return []

    try:
        with open(BET_HISTORY_FILE, "r") as f:
            bets = json.load(f)
            return bets if isinstance(bets, list) else []
    except Exception as e:
        logger.error(f"Failed to load bet history: {e}")
        return []


def save_bet_history(bets: List[Dict[str, Any]]) -> bool:
    """Save bets to file. Returns True on success."""
    try:
        with open(BET_HISTORY_FILE, "w") as f:
            json.dump(bets, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Failed to save bet history: {e}")
        return False


def add_bet(bet_data: Dict[str, Any]) -> Optional[str]:
    """
    Add a new bet to history.

    Args:
        bet_data: Bet dict (without id; will be generated)

    Returns:
        The bet ID on success, None on failure
    """
    bets = load_bet_history()

    # Create bet with generated ID
    bet = get_default_bet()
    bet.update(bet_data)
    bet["id"] = str(uuid.uuid4())

    # Ensure date is set
    if not bet["date"]:
        bet["date"] = datetime.utcnow().isoformat() + "Z"

    bets.append(bet)
    if save_bet_history(bets):
        return bet["id"]
    return None


def get_bets(
    league: Optional[str] = None,
    result: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """
    Get bets, optionally filtered.

    Args:
        league: Filter by league (e.g., "NFL")
        result: Filter by result ("win", "loss", "push", "pending")
        limit: Max number of bets to return (most recent first)

    Returns:
        List of bet dicts
    """
    bets = load_bet_history()

    # Filter
    if league:
        bets = [b for b in bets if b.get("league") == league]
    if result:
        bets = [b for b in bets if b.get("result") == result]

    # Sort by date (most recent first)
    bets.sort(key=lambda b: b.get("date", ""), reverse=True)

    return bets[:limit]


def update_bet(bet_id: str, updates: Dict[str, Any]) -> bool:
    """
    Update a bet's data.

    Args:
        bet_id: The bet ID to update
        updates: Dict of fields to update

    Returns:
        True on success, False if bet not found or save failed
    """
    bets = load_bet_history()

    for bet in bets:
        if bet.get("id") == bet_id:
            bet.update(updates)
            return save_bet_history(bets)

    logger.warning(f"Bet {bet_id} not found")
    return False


def delete_bet(bet_id: str) -> bool:
    """Delete a bet from history."""
    bets = load_bet_history()
    original_len = len(bets)
    bets = [b for b in bets if b.get("id") != bet_id]

    if len(bets) < original_len:
        return save_bet_history(bets)
    return False


def get_bet_stats(league: Optional[str] = None) -> Dict[str, Any]:
    """
    Calculate betting statistics.

    Args:
        league: Optional league filter

    Returns:
        Dict with win_rate, roi, total_bets, total_pnl, etc.
    """
    bets = get_bets(league=league, limit=1000)

    if not bets:
        return {
            "total_bets": 0,
            "wins": 0,
            "losses": 0,
            "pushes": 0,
            "pending": 0,
            "win_rate": 0.0,
            "total_stake": 0.0,
            "total_pnl": 0.0,
            "roi": 0.0,
        }

    wins = sum(1 for b in bets if b.get("result") == "win")
    losses = sum(1 for b in bets if b.get("result") == "loss")
    pushes = sum(1 for b in bets if b.get("result") == "push")
    pending = sum(1 for b in bets if b.get("result") == "pending")
    total_bets = len(bets)

    total_stake = sum(float(b.get("stake", 0)) for b in bets)
    total_pnl = sum(float(b.get("pnl", 0)) for b in bets)

    win_rate = (wins / (wins + losses)) * 100 if (wins + losses) > 0 else 0
    roi = (total_pnl / total_stake) * 100 if total_stake > 0 else 0

    return {
        "total_bets": total_bets,
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "pending": pending,
        "win_rate": round(win_rate, 2),
        "total_stake": round(total_stake, 2),
        "total_pnl": round(total_pnl, 2),
        "roi": round(roi, 2),
    }


def calculate_parlay_odds(odds_list: List[int]) -> float:
    """
    Calculate parlay odds from individual bet odds.

    Args:
        odds_list: List of odds (American format, e.g., -110, +200)

    Returns:
        Combined parlay odds
    """
    if not odds_list:
        return 0

    decimal_odds = 1.0
    for odds in odds_list:
        if odds < 0:
            # Favorite: decimal = 1 + (100 / |odds|)
            decimal_odds *= 1 + (100 / abs(odds))
        else:
            # Underdog: decimal = 1 + (odds / 100)
            decimal_odds *= 1 + (odds / 100)

    # Convert back to American odds
    if decimal_odds >= 2:
        return (decimal_odds - 1) * 100
    else:
        return -100 / (decimal_odds - 1)


def calculate_kelly_fraction(
    win_probability: float,
    odds: int,
    kelly_fraction: float = 0.25,
) -> float:
    """
    Calculate Kelly Criterion bet size.

    Args:
        win_probability: Probability of winning (0-1)
        odds: American odds
        kelly_fraction: Fraction of full Kelly to bet (typically 0.25)

    Returns:
        Fraction of bankroll to bet
    """
    if odds < 0:
        decimal_odds = 1 + (100 / abs(odds))
    else:
        decimal_odds = 1 + (odds / 100)

    loss_probability = 1 - win_probability
    kelly = (win_probability * (decimal_odds - 1) - loss_probability) / (decimal_odds - 1)
    kelly = max(kelly, 0)  # Don't go negative

    return kelly * kelly_fraction


def american_to_decimal(odds: int) -> float:
    """Convert American odds to decimal odds."""
    if odds < 0:
        return 1 + (100 / abs(odds))
    else:
        return 1 + (odds / 100)


def decimal_to_american(decimal: float) -> int:
    """Convert decimal odds to American odds."""
    if decimal >= 2:
        return int((decimal - 1) * 100)
    else:
        return int(-100 / (decimal - 1))

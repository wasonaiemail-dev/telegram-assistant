"""
Sports betting module for Alfred Sports Pack.

Handles:
- Screenshot-based line comparison (sportsbook odds extraction via GPT-4o Vision)
- Bet sizing calculations (fixed unit, percentage, Kelly Criterion)
- Bet tracking and logging
- Statistics and performance metrics
"""

import logging
import json
import re
from typing import Dict, Any, List, Optional
from datetime import datetime
from decimal import Decimal

from openai import AsyncOpenAI

from core.config import OPENAI_API_KEY
from plugins.sports import data as sports_data
from plugins.sports import config as sports_config

logger = logging.getLogger(__name__)

client = AsyncOpenAI(api_key=OPENAI_API_KEY)

# Supported sportsbooks
SPORTSBOOKS = {
    "draftkings": "DraftKings",
    "fanduel": "FanDuel",
    "betmgm": "BetMGM",
    "caesars": "Caesars",
    "espn": "ESPN Bet",
    "fanatics": "Fanatics",
    "bovada": "Bovada",
    "mybookie": "MyBookie",
}


# ═══════════════════════════════════════════════════════════════════════════════
# SCREENSHOT ANALYSIS — Line Comparison
# ═══════════════════════════════════════════════════════════════════════════════


async def analyze_betting_screenshot(
    photo_bytes: bytes,
    context_text: str = "",
) -> Dict[str, Any]:
    """
    Analyze a screenshot of sportsbook odds using GPT-4o Vision.

    Extracts game info, bet types, and odds from visible sportsbooks.

    Args:
        photo_bytes: Raw image bytes from Telegram photo
        context_text: Optional context text from user caption

    Returns:
        {
            "success": bool,
            "game": str,
            "bet_type": str,
            "books": [
                {
                    "name": "DraftKings",
                    "odds": -110,
                    "implied_prob": 52.38,
                    "display": "-110"
                },
                ...
            ],
            "best_book": {
                "name": "FanDuel",
                "odds": -105,
                "implied_prob": 51.22,
                "edge": "Better odds by 5"
            },
            "error": "optional error message"
        }
    """
    try:
        # Convert to base64 for API
        import base64
        b64_image = base64.b64encode(photo_bytes).decode("utf-8")

        prompt = f"""Analyze this sportsbook odds screenshot and extract the betting lines.

{f'Context: {context_text}' if context_text else ''}

Please identify and extract:
1. The game/matchup being bet on (e.g., "Chiefs vs 49ers", "Chiefs -3")
2. The bet type (moneyline, spread, over/under, prop, parlay, etc.)
3. For each visible sportsbook, list:
   - Sportsbook name (DraftKings, FanDuel, BetMGM, Caesars, ESPN, Fanatics, Bovada, MyBookie, etc.)
   - The odds displayed
   - The pick/selection

Format your response as valid JSON with this structure:
{{
    "game": "the game matchup",
    "bet_type": "moneyline|spread|over_under|prop|parlay",
    "books": [
        {{"name": "DraftKings", "odds": -110, "pick": "Chiefs"}},
        {{"name": "FanDuel", "odds": -105, "pick": "Chiefs"}}
    ],
    "notes": "any relevant observations about the odds"
}}

If you cannot identify betting lines, respond with:
{{"error": "No betting lines found in image"}}
"""

        response = await client.messages.create(
            model="gpt-4o",
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": b64_image,
                            },
                        },
                        {
                            "type": "text",
                            "text": prompt,
                        },
                    ],
                }
            ],
        )

        # Parse response
        text = response.content[0].text
        data = json.loads(text)

        if "error" in data:
            return {
                "success": False,
                "error": data.get("error", "Failed to parse odds"),
            }

        # Calculate implied probabilities and find best book
        books = data.get("books", [])
        for book in books:
            book["implied_prob"] = _implied_probability(book.get("odds", 0))

        # Find best book (highest odds for favorites, lowest for underdogs)
        best_book = None
        if books:
            if books[0].get("odds", 0) < 0:
                # Favorites: highest odds is best
                best_book = max(books, key=lambda b: b.get("odds", -999))
            else:
                # Underdogs: lowest odds is best
                best_book = min(books, key=lambda b: b.get("odds", 999))

            if books[0].get("odds", 0) != best_book.get("odds", 0):
                first_odds = books[0].get("odds", 0)
                best_odds = best_book.get("odds", 0)
                edge = abs(best_odds - first_odds)
                best_book["edge"] = f"Better by {edge} points"

        return {
            "success": True,
            "game": data.get("game", "Unknown game"),
            "bet_type": data.get("bet_type", "unknown"),
            "books": books,
            "best_book": best_book,
            "notes": data.get("notes", ""),
        }

    except json.JSONDecodeError:
        logger.error("Failed to parse GPT response as JSON")
        return {"success": False, "error": "Failed to parse odds data"}
    except Exception as e:
        logger.error(f"Screenshot analysis error: {e}")
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
# BET SIZING CALCULATOR
# ═══════════════════════════════════════════════════════════════════════════════


async def calculate_bet_size(
    odds: int,
    bankroll_or_unit: float,
    method: str = "fixed_unit",
    confidence: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Calculate recommended bet size.

    Args:
        odds: American odds (e.g., -110, +200)
        bankroll_or_unit: Bankroll amount or unit size (depends on method)
        method: "fixed_unit", "percentage", or "kelly"
        confidence: Win probability (0-1), required for kelly method

    Returns:
        {
            "method": "fixed_unit|percentage|kelly",
            "stake": 50.00,
            "units": 5.0,  # if using units
            "percentage": 2.5,  # if using percentage
            "decimal_odds": 1.909,
            "implied_prob": 52.38,
            "recommendation": "Recommended bet size: $50 (5 units)"
        }
    """
    try:
        decimal_odds = sports_data.american_to_decimal(odds)
        implied_prob = _implied_probability(odds)

        result = {
            "method": method,
            "odds": odds,
            "decimal_odds": round(decimal_odds, 3),
            "implied_prob": round(implied_prob, 2),
        }

        if method == "fixed_unit":
            # Multiplier-based sizing (1x, 2x, 3x unit)
            default_multiplier = 1
            stake = bankroll_or_unit * default_multiplier
            result["stake"] = round(stake, 2)
            result["units"] = default_multiplier
            result["recommendation"] = f"Recommended stake: ${stake:.2f} ({default_multiplier} unit)"

        elif method == "percentage":
            # Risk a percentage of bankroll
            default_pct = 2.0  # 2% default
            stake = bankroll_or_unit * (default_pct / 100)
            result["stake"] = round(stake, 2)
            result["percentage"] = default_pct
            result["recommendation"] = (
                f"Recommended stake: ${stake:.2f} "
                f"({default_pct}% of ${bankroll_or_unit:.2f} bankroll)"
            )

        elif method == "kelly":
            # Kelly Criterion
            if not confidence or confidence <= 0 or confidence >= 1:
                return {
                    "success": False,
                    "error": "Kelly method requires confidence probability (0 < p < 1)",
                }

            kelly_fraction = sports_data.calculate_kelly_fraction(
                confidence, odds, kelly_fraction=0.25
            )
            kelly_fraction = max(kelly_fraction, 0)
            stake = bankroll_or_unit * kelly_fraction
            result["stake"] = round(stake, 2)
            result["kelly_fraction"] = round(kelly_fraction, 4)
            result["recommendation"] = (
                f"Kelly Criterion (25%): Stake ${stake:.2f} "
                f"({kelly_fraction*100:.1f}% of bankroll)"
            )

        return {"success": True, **result}

    except Exception as e:
        logger.error(f"Bet size calculation error: {e}")
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
# BET LOGGING
# ═══════════════════════════════════════════════════════════════════════════════


async def log_bet_from_screenshot(
    photo_bytes: bytes,
    user_settings: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Extract bet details from a bet slip screenshot and log the bet.

    Args:
        photo_bytes: Bet slip screenshot
        user_settings: User's sports settings (for unit size, etc.)

    Returns:
        {
            "success": bool,
            "bet_id": "uuid",
            "message": "Bet logged successfully",
            "bet": {...}
        }
    """
    try:
        import base64

        b64_image = base64.b64encode(photo_bytes).decode("utf-8")

        prompt = """Analyze this bet slip screenshot and extract the bet details.

Extract:
1. Sportsbook name
2. Game/matchup (team names or matchup)
3. Bet type (moneyline, spread, over/under, prop)
4. Pick/selection
5. Odds (American format)
6. Stake/wager amount
7. Potential payout

Format as JSON:
{
    "book": "DraftKings",
    "game": "Chiefs vs 49ers",
    "bet_type": "moneyline",
    "pick": "Chiefs",
    "odds": -150,
    "stake": 100.0,
    "potential_payout": 166.67,
    "league": "NFL",
    "notes": "optional observations"
}

If not a bet slip, respond with:
{"error": "Not a valid bet slip"}
"""

        response = await client.messages.create(
            model="gpt-4o",
            max_tokens=512,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": b64_image,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )

        text = response.content[0].text
        data = json.loads(text)

        if "error" in data:
            return {"success": False, "error": data.get("error")}

        # Create bet record
        bet_data = {
            "league": data.get("league", "Unknown"),
            "game": data.get("game", ""),
            "bet_type": data.get("bet_type", "moneyline"),
            "pick": data.get("pick", ""),
            "odds": int(data.get("odds", 0)),
            "stake": float(data.get("stake", 0)),
            "result": "pending",
            "pnl": 0.0,
            "notes": f"Bet slip from {data.get('book', 'Unknown')}. {data.get('notes', '')}",
        }

        bet_id = sports_data.add_bet(bet_data)
        if not bet_id:
            return {"success": False, "error": "Failed to save bet"}

        return {
            "success": True,
            "bet_id": bet_id,
            "message": f"Bet logged: {bet_data['pick']} @ {bet_data['odds']:+d}",
            "bet": bet_data,
        }

    except Exception as e:
        logger.error(f"Bet slip logging error: {e}")
        return {"success": False, "error": str(e)}


async def log_bet_from_text(
    text: str,
    user_settings: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Parse natural language bet description and log it.

    Examples:
      "bet $50 on Chiefs -3 at DraftKings"
      "FanDuel: $100 Over 45 in NFL game"
      "ML on Celtics +200"

    Args:
        text: User's bet description
        user_settings: User settings

    Returns:
        Same as log_bet_from_screenshot
    """
    try:
        prompt = f"""Parse this natural language bet description and extract structured data.

User input: "{text}"

Extract:
1. Sportsbook (if mentioned)
2. League (NFL, NBA, MLB, NHL, etc.)
3. Game/matchup
4. Bet type (moneyline, spread, over_under, prop, parlay)
5. Pick/selection
6. Odds (if provided, American format)
7. Stake amount
8. Any relevant notes

Return JSON:
{{
    "book": "sportsbook name or 'Unknown'",
    "league": "league name",
    "game": "matchup",
    "bet_type": "type",
    "pick": "selection",
    "odds": -110,
    "stake": 50.0,
    "notes": ""
}}

If parsing fails, include "error" field with explanation.
"""

        response = await client.messages.create(
            model="gpt-3.5-turbo",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )

        text_response = response.content[0].text
        data = json.loads(text_response)

        if "error" in data:
            return {"success": False, "error": data.get("error")}

        # Create bet record
        bet_data = {
            "league": data.get("league", "Unknown"),
            "game": data.get("game", ""),
            "bet_type": data.get("bet_type", "moneyline"),
            "pick": data.get("pick", ""),
            "odds": int(data.get("odds", 0)) if data.get("odds") else -110,
            "stake": float(data.get("stake", 0)),
            "result": "pending",
            "pnl": 0.0,
            "notes": f"Logged from text at {data.get('book', 'Unknown')}",
        }

        bet_id = sports_data.add_bet(bet_data)
        if not bet_id:
            return {"success": False, "error": "Failed to save bet"}

        return {
            "success": True,
            "bet_id": bet_id,
            "message": f"Bet logged: {bet_data['pick']} @ {bet_data['odds']:+d}",
            "bet": bet_data,
        }

    except Exception as e:
        logger.error(f"Text bet logging error: {e}")
        return {"success": False, "error": str(e)}


async def resolve_bet(
    bet_id: str,
    result: str,
    pnl: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Mark a bet as won/lost/push and calculate P&L.

    Args:
        bet_id: The bet ID to resolve
        result: "win", "loss", or "push"
        pnl: Optional P&L amount (calculated if not provided)

    Returns:
        {
            "success": bool,
            "bet": {...updated bet...},
            "message": "Bet resolved"
        }
    """
    try:
        bets = sports_data.get_bets(limit=1000)
        bet = next((b for b in bets if b["id"] == bet_id), None)

        if not bet:
            return {"success": False, "error": f"Bet {bet_id} not found"}

        if result not in ["win", "loss", "push"]:
            return {"success": False, "error": "Result must be 'win', 'loss', or 'push'"}

        # Calculate P&L if not provided
        if pnl is None:
            stake = float(bet.get("stake", 0))
            odds = int(bet.get("odds", 0))

            if result == "win":
                pnl = _calculate_payout(stake, odds) - stake
            elif result == "loss":
                pnl = -stake
            else:  # push
                pnl = 0

        updates = {"result": result, "pnl": round(pnl, 2)}

        if sports_data.update_bet(bet_id, updates):
            bet.update(updates)
            return {
                "success": True,
                "bet": bet,
                "message": f"Bet resolved: {result.upper()} | P&L: ${pnl:+.2f}",
            }
        else:
            return {"success": False, "error": "Failed to save bet update"}

    except Exception as e:
        logger.error(f"Bet resolution error: {e}")
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
# STATISTICS
# ═══════════════════════════════════════════════════════════════════════════════


async def calculate_stats(
    bets: Optional[List[Dict[str, Any]]] = None,
    period: Optional[str] = None,
    league: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Calculate comprehensive betting statistics.

    Args:
        bets: Optional list of bets (uses all bets if not provided)
        period: Filter by period (not yet implemented)
        league: Filter by league

    Returns:
        {
            "total_bets": 50,
            "wins": 30,
            "losses": 15,
            "pushes": 5,
            "pending": 0,
            "win_rate": 66.67,
            "total_staked": 2500.0,
            "total_returned": 3000.0,
            "net_pnl": 500.0,
            "roi": 20.0,
            "avg_odds": -110,
            "clv": 1.2,  # Closing Line Value if available
            "by_sport": {...},
            "by_book": {...},
            "by_bet_type": {...},
            "streak": {"current": "W", "count": 3},
            "best_league": "NFL",
            "worst_league": "NBA"
        }
    """
    try:
        if bets is None:
            bets = sports_data.get_bets(league=league, limit=1000)

        if not bets:
            return {
                "total_bets": 0,
                "wins": 0,
                "losses": 0,
                "pushes": 0,
                "pending": 0,
                "win_rate": 0.0,
                "total_staked": 0.0,
                "total_returned": 0.0,
                "net_pnl": 0.0,
                "roi": 0.0,
            }

        # Basic counts
        resolved_bets = [b for b in bets if b.get("result") != "pending"]
        wins = sum(1 for b in resolved_bets if b.get("result") == "win")
        losses = sum(1 for b in resolved_bets if b.get("result") == "loss")
        pushes = sum(1 for b in resolved_bets if b.get("result") == "push")
        pending = sum(1 for b in bets if b.get("result") == "pending")

        # P&L calculations
        total_staked = sum(float(b.get("stake", 0)) for b in bets)
        total_pnl = sum(float(b.get("pnl", 0)) for b in resolved_bets)
        total_returned = total_staked + total_pnl

        # Percentages
        win_rate = (wins / (wins + losses)) * 100 if (wins + losses) > 0 else 0
        roi = (total_pnl / total_staked) * 100 if total_staked > 0 else 0

        # Streak
        streak = _calculate_streak(resolved_bets)

        # Breakdowns
        by_league = _breakdown_by_field(resolved_bets, "league")
        by_bet_type = _breakdown_by_field(resolved_bets, "bet_type")

        stats = {
            "total_bets": len(bets),
            "wins": wins,
            "losses": losses,
            "pushes": pushes,
            "pending": pending,
            "win_rate": round(win_rate, 2),
            "total_staked": round(total_staked, 2),
            "total_returned": round(total_returned, 2),
            "net_pnl": round(total_pnl, 2),
            "roi": round(roi, 2),
            "by_league": by_league,
            "by_bet_type": by_bet_type,
            "streak": streak,
        }

        # Best/worst leagues
        if by_league:
            best = max(by_league.items(), key=lambda x: x[1].get("win_rate", 0))
            worst = min(by_league.items(), key=lambda x: x[1].get("win_rate", 100))
            stats["best_league"] = best[0]
            stats["worst_league"] = worst[0]

        return stats

    except Exception as e:
        logger.error(f"Stats calculation error: {e}")
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════


def _implied_probability(american_odds: int) -> float:
    """Calculate implied probability from American odds."""
    if american_odds < 0:
        return abs(american_odds) / (abs(american_odds) + 100) * 100
    else:
        return 100 / (american_odds + 100) * 100


def _calculate_payout(stake: float, american_odds: int) -> float:
    """Calculate payout from stake and odds."""
    if american_odds < 0:
        return stake * (100 / abs(american_odds))
    else:
        return stake * (american_odds / 100)


def _calculate_streak(bets: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Calculate current win/loss streak.

    Args:
        bets: List of resolved bets (sorted by date, most recent first)

    Returns:
        {"current": "W" or "L", "count": 3}
    """
    if not bets:
        return {"current": None, "count": 0}

    # Sort by date descending (most recent first)
    sorted_bets = sorted(bets, key=lambda b: b.get("date", ""), reverse=True)

    if not sorted_bets:
        return {"current": None, "count": 0}

    current_result = sorted_bets[0].get("result")
    if current_result == "push":
        # Skip pushes and find first win/loss
        for bet in sorted_bets:
            if bet.get("result") in ["win", "loss"]:
                current_result = bet.get("result")
                break

    if not current_result:
        return {"current": None, "count": 0}

    current_char = "W" if current_result == "win" else "L"
    count = 0

    for bet in sorted_bets:
        result = bet.get("result")
        if result == "push":
            continue
        if (result == "win" and current_char == "W") or (
            result == "loss" and current_char == "L"
        ):
            count += 1
        else:
            break

    return {"current": current_char, "count": count}


def _breakdown_by_field(
    bets: List[Dict[str, Any]],
    field: str,
) -> Dict[str, Dict[str, Any]]:
    """
    Break down stats by a field (league, bet_type, etc.).

    Returns:
        {
            "NFL": {"wins": 10, "losses": 5, "win_rate": 66.67, "roi": 15.0},
            "NBA": {"wins": 5, "losses": 10, "win_rate": 33.33, "roi": -20.0}
        }
    """
    breakdown = {}

    for bet in bets:
        key = bet.get(field, "Unknown")
        if key not in breakdown:
            breakdown[key] = {
                "wins": 0,
                "losses": 0,
                "pushes": 0,
                "total": 0,
                "staked": 0.0,
                "pnl": 0.0,
            }

        breakdown[key]["total"] += 1
        breakdown[key]["staked"] += float(bet.get("stake", 0))
        breakdown[key]["pnl"] += float(bet.get("pnl", 0))

        result = bet.get("result")
        if result == "win":
            breakdown[key]["wins"] += 1
        elif result == "loss":
            breakdown[key]["losses"] += 1
        elif result == "push":
            breakdown[key]["pushes"] += 1

    # Calculate percentages
    for key, stats in breakdown.items():
        total_resolved = stats["wins"] + stats["losses"]
        if total_resolved > 0:
            stats["win_rate"] = round((stats["wins"] / total_resolved) * 100, 2)
        else:
            stats["win_rate"] = 0.0

        if stats["staked"] > 0:
            stats["roi"] = round((stats["pnl"] / stats["staked"]) * 100, 2)
        else:
            stats["roi"] = 0.0

        stats["staked"] = round(stats["staked"], 2)
        stats["pnl"] = round(stats["pnl"], 2)

    return breakdown

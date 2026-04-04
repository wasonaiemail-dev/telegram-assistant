"""
Layer 1 keyword rules for sports plugin.

Fast regex matching for common sports queries.
Fires before GPT intent classification for instant results.

IMPORTANT: Handler functions must match the core signature:
    handler(match_object, text) -> IntentResult
They must be synchronous (not async) because _keyword_classify is sync.
"""

import re
import logging
from typing import List, Tuple, Callable

from core.intent import IntentResult

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# HANDLER FACTORIES — each returns a sync handler(match, text) -> IntentResult
# ═══════════════════════════════════════════════════════════════════════════════

def _make_scores_handler(league: str, team: str = "") -> Callable:
    """Create a scores keyword handler for a specific league."""
    def handler(m, t):
        entities = {"league": league}
        if team:
            entities["team"] = team
        return IntentResult(
            intent="sports_scores",
            entities=entities,
            confidence="keyword",
            raw=t,
        )
    return handler


def _make_standings_handler(league: str) -> Callable:
    """Create a standings keyword handler for a specific league."""
    def handler(m, t):
        return IntentResult(
            intent="sports_standings",
            entities={"league": league},
            confidence="keyword",
            raw=t,
        )
    return handler


def _make_schedule_handler(league: str, team: str = "") -> Callable:
    """Create a schedule keyword handler for a specific league."""
    def handler(m, t):
        entities = {"league": league}
        if team:
            entities["team"] = team
        return IntentResult(
            intent="sports_schedule",
            entities=entities,
            confidence="keyword",
            raw=t,
        )
    return handler


# ═══════════════════════════════════════════════════════════════════════════════
# GENERIC HANDLERS — sync, signature (match, text) -> IntentResult
# ═══════════════════════════════════════════════════════════════════════════════

def _scores_generic(m, t):
    """Generic scores handler (no league specified)."""
    return IntentResult(
        intent="sports_scores",
        entities={},
        confidence="keyword",
        raw=t,
    )


def _standings_generic(m, t):
    """Generic standings handler."""
    return IntentResult(
        intent="sports_standings",
        entities={},
        confidence="keyword",
        raw=t,
    )


def _schedule_generic(m, t):
    """Generic schedule handler."""
    return IntentResult(
        intent="sports_schedule",
        entities={},
        confidence="keyword",
        raw=t,
    )


def _bet_handler(m, t):
    """Betting-related query handler — infers sub-intent from text."""
    tl = t.lower()
    if "add" in tl or "log" in tl or "record" in tl:
        return IntentResult(
            intent="sports_bet_add",
            entities={},
            confidence="keyword",
            raw=t,
        )
    elif "calculate" in tl or "kelly" in tl or "parlay" in tl or "size" in tl:
        return IntentResult(
            intent="sports_bet_calculate",
            entities={},
            confidence="keyword",
            raw=t,
        )
    elif "compare" in tl or "best line" in tl or "best odds" in tl:
        return IntentResult(
            intent="sports_bet_compare",
            entities={},
            confidence="keyword",
            raw=t,
        )
    elif "stats" in tl or "roi" in tl or "p&l" in tl or "profit" in tl:
        return IntentResult(
            intent="sports_bet_view",
            entities={"view": "stats"},
            confidence="keyword",
            raw=t,
        )
    else:
        return IntentResult(
            intent="sports_bet_view",
            entities={},
            confidence="keyword",
            raw=t,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# RULE BUILDER — called by plugin_loader.get_plugin_keyword_rules()
# ═══════════════════════════════════════════════════════════════════════════════

def build_rules() -> List[Tuple[object, Callable]]:
    """
    Build Layer 1 keyword rules for sports.

    Returns a list of (compiled_regex, handler_fn) tuples.
    Each handler_fn has signature: handler(match_object, text) -> IntentResult
    These are checked before GPT classification for speed.
    """
    rules = []

    # ── SCORES ────────────────────────────────────────────────────────────

    # Generic score queries
    rules.append((
        re.compile(r"\b(?:what|show|get|what's|whats)\s+(?:are\s+)?the\s+scores?", re.I),
        _scores_generic,
    ))
    rules.append((
        re.compile(r"\b(?:who|how)\s+(?:won|scored|did\s+\w+\s+(?:do|play))", re.I),
        _scores_generic,
    ))
    rules.append((
        re.compile(r"\b(?:latest|recent|current|live)\s+scores?", re.I),
        _scores_generic,
    ))

    # League-specific scores
    rules.append((
        re.compile(r"\b(?:nfl|football)\s+scores?", re.I),
        _make_scores_handler("nfl"),
    ))
    rules.append((
        re.compile(r"\b(?:nba|basketball)\s+scores?", re.I),
        _make_scores_handler("nba"),
    ))
    rules.append((
        re.compile(r"\b(?:mlb|baseball)\s+scores?", re.I),
        _make_scores_handler("mlb"),
    ))
    rules.append((
        re.compile(r"\b(?:nhl|hockey)\s+scores?", re.I),
        _make_scores_handler("nhl"),
    ))
    rules.append((
        re.compile(r"\b(?:soccer|epl|premier\s+league|mls|bundesliga|la\s+liga)\s+scores?", re.I),
        _scores_generic,  # let the dispatch figure out which soccer league
    ))
    rules.append((
        re.compile(r"\bcollege\s+(?:football|basketball)\s+scores?", re.I),
        _scores_generic,
    ))

    # ── STANDINGS ─────────────────────────────────────────────────────────

    rules.append((
        re.compile(r"\b(?:nfl|football)\s+(?:standings|rankings|table)", re.I),
        _make_standings_handler("nfl"),
    ))
    rules.append((
        re.compile(r"\b(?:nba|basketball)\s+(?:standings|rankings|table)", re.I),
        _make_standings_handler("nba"),
    ))
    rules.append((
        re.compile(r"\b(?:mlb|baseball)\s+(?:standings|rankings|table)", re.I),
        _make_standings_handler("mlb"),
    ))
    rules.append((
        re.compile(r"\b(?:nhl|hockey)\s+(?:standings|rankings|table)", re.I),
        _make_standings_handler("nhl"),
    ))
    rules.append((
        re.compile(r"\b(?:epl|premier\s+league)\s+(?:standings|table|rankings)", re.I),
        _make_standings_handler("epl"),
    ))
    rules.append((
        re.compile(r"\b(?:standings|rankings|league\s+table)", re.I),
        _standings_generic,
    ))

    # ── SCHEDULE / UPCOMING GAMES ─────────────────────────────────────────

    rules.append((
        re.compile(r"\b(?:who's|whos|who\s+is)\s+playing\b", re.I),
        _schedule_generic,
    ))
    rules.append((
        re.compile(r"\b(?:upcoming|next|today's?|tonight's?)\s+games?\b", re.I),
        _schedule_generic,
    ))
    rules.append((
        re.compile(r"\b(?:games?|matchups?)\s+(?:today|tonight|tomorrow)", re.I),
        _schedule_generic,
    ))
    rules.append((
        re.compile(r"\b(?:nfl|football)\s+(?:schedule|games|upcoming)", re.I),
        _make_schedule_handler("nfl"),
    ))
    rules.append((
        re.compile(r"\b(?:nba|basketball)\s+(?:schedule|games|upcoming)", re.I),
        _make_schedule_handler("nba"),
    ))
    rules.append((
        re.compile(r"\b(?:mlb|baseball)\s+(?:schedule|games|upcoming)", re.I),
        _make_schedule_handler("mlb"),
    ))
    rules.append((
        re.compile(r"\b(?:nhl|hockey)\s+(?:schedule|games|upcoming)", re.I),
        _make_schedule_handler("nhl"),
    ))

    # ── BETTING ───────────────────────────────────────────────────────────

    rules.append((
        re.compile(r"\b(?:log|add|record|track)\s+(?:a\s+)?(?:bet|wager)\b", re.I),
        _bet_handler,
    ))
    rules.append((
        re.compile(r"\b(?:my|show|view)\s+bets?\b", re.I),
        _bet_handler,
    ))
    rules.append((
        re.compile(r"\b(?:bet|betting)\s+(?:stats|history|record|tracker)\b", re.I),
        _bet_handler,
    ))
    rules.append((
        re.compile(r"\b(?:kelly|parlay)\s+(?:calculator|calc)\b", re.I),
        _bet_handler,
    ))
    rules.append((
        re.compile(r"\b(?:compare|best)\s+(?:odds|lines|books?)\b", re.I),
        _bet_handler,
    ))
    rules.append((
        re.compile(r"\b(?:betting|bet)\s+(?:roi|p&l|profit|loss|pnl)\b", re.I),
        _bet_handler,
    ))

    return rules

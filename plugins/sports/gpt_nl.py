"""
plugins/sports/gpt_nl.py
========================
GPT function-calling dispatcher for sports natural-language queries.

Phase 2 of Sports Pack redesign — replaces brittle keyword regex routing
with GPT function-calling that understands the full variety of sports queries.

HOW IT WORKS
────────────
1. User sends a NL sports query (e.g. "who leads the NBA in blocks")
2. keywords.py broad catch-all routes it to `sports_nl_query` intent
3. dispatch.py calls `gpt_sports_dispatch(query, update, context)`
4. GPT receives the query + 8 function schemas and picks the right one
5. We map the function call to an IntentResult and pass it to handle_sports_intent
6. If GPT calls `not_sports()`, we return False and the caller falls back to /ask

COST
────
Uses GPT_CHAT_MODEL (default: gpt-4o-mini).
~500 input tokens + ~50 output tokens ≈ $0.00008 per query.
At 100 queries/day ≈ $0.24/month.
"""

import json
import logging
from datetime import date

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# FUNCTION SCHEMAS
# ═══════════════════════════════════════════════════════════════════════════════

_SPORTS_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_scores",
            "description": "Get recent game scores or results for a sports league",
            "parameters": {
                "type": "object",
                "properties": {
                    "league": {
                        "type": "string",
                        "enum": ["nba", "nfl", "mlb", "nhl", "epl", "mls", "bundesliga", "laliga"],
                        "description": "Sports league abbreviation",
                    },
                    "team": {
                        "type": "string",
                        "description": "Optional team name to filter results",
                    },
                },
                "required": ["league"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_standings",
            "description": "Get current league standings, rankings, or league table",
            "parameters": {
                "type": "object",
                "properties": {
                    "league": {
                        "type": "string",
                        "enum": ["nba", "nfl", "mlb", "nhl", "epl", "mls", "bundesliga", "laliga"],
                        "description": "Sports league abbreviation",
                    },
                },
                "required": ["league"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_schedule",
            "description": "Get upcoming games or schedule for a league",
            "parameters": {
                "type": "object",
                "properties": {
                    "league": {
                        "type": "string",
                        "enum": ["nba", "nfl", "mlb", "nhl", "epl", "mls", "bundesliga", "laliga"],
                        "description": "Sports league abbreviation",
                    },
                    "team": {
                        "type": "string",
                        "description": "Optional team name to filter",
                    },
                },
                "required": ["league"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_leaders",
            "description": (
                "Get statistical leaders for a league "
                "(top scorers, assists leaders, blocks leaders, etc.)"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "league": {
                        "type": "string",
                        "enum": ["nba", "nfl", "mlb", "nhl", "epl", "mls"],
                        "description": "Sports league abbreviation",
                    },
                    "stat": {
                        "type": "string",
                        "description": (
                            "Specific stat category to filter by. "
                            "Examples: points, assists, rebounds, blocks, steals, goals, "
                            "touchdowns, home runs, era, batting average, saves, plus/minus"
                        ),
                    },
                },
                "required": ["league"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_player_stats",
            "description": "Get current season stats or averages for a specific player",
            "parameters": {
                "type": "object",
                "properties": {
                    "player_name": {
                        "type": "string",
                        "description": (
                            "Player name — nicknames and misspellings are OK "
                            "(e.g. 'KD', 'Joker', 'Mahommes', 'Bron')"
                        ),
                    },
                },
                "required": ["player_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_player_gamelog",
            "description": "Get a player's recent game-by-game performance log or last N games",
            "parameters": {
                "type": "object",
                "properties": {
                    "player_name": {
                        "type": "string",
                        "description": "Player name",
                    },
                },
                "required": ["player_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "not_sports",
            "description": (
                "This message is NOT a sports data question and cannot be answered "
                "with sports APIs. Use when the message is conversational, general "
                "knowledge, or about something unrelated to sports stats/scores."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
]

_SYSTEM_PROMPT = """You are a sports data assistant for Alfred, a personal Telegram bot.
Today's date is {today}.

The user sent a message that may be a sports question. Use the provided tools to decide what sports data action to take. Pick the MOST SPECIFIC function that matches.

Examples:
- "who leads the nba in blocks" → get_leaders(league="nba", stat="blocks")
- "who leads the nba in assists" → get_leaders(league="nba", stat="assists")
- "nba scoring leaders" → get_leaders(league="nba", stat="points")
- "nba mvp race" → get_leaders(league="nba", stat="points")
- "how many ppg is jokic averaging" → get_player_stats(player_name="Nikola Jokic")
- "show me mahomes stats" → get_player_stats(player_name="Patrick Mahomes")
- "who won last night" → get_scores(league="nba")
- "nba scores" → get_scores(league="nba")
- "nba standings" → get_standings(league="nba")
- "who's in first in the nba" → get_standings(league="nba")
- "celtics upcoming games" → get_schedule(league="nba", team="Celtics")
- "lebron last 5 games" → get_player_gamelog(player_name="LeBron James")
- "i love basketball" → not_sports()
- "what time is it" → not_sports()

Always expand nicknames/abbreviations for player_name:
- "KD" → "Kevin Durant"
- "Joker" → "Nikola Jokic"
- "Bron" or "LBJ" → "LeBron James"
- "Mahommes" → "Patrick Mahomes" (fix misspellings)

If the message is NOT asking for sports data, use not_sports()."""


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN DISPATCHER
# ═══════════════════════════════════════════════════════════════════════════════

async def gpt_sports_dispatch(query: str, update, context) -> bool:
    """
    Use GPT function-calling to determine which sports action to take, then execute it.

    Args:
        query:   The original user message text.
        update:  Telegram Update object.
        context: Telegram ContextTypes.DEFAULT_TYPE.

    Returns:
        True  — the query was handled as a sports query.
        False — GPT determined this is not a sports query (caller should fall back to /ask).
    """
    from openai import AsyncOpenAI
    from core.config import OPENAI_API_KEY, GPT_CHAT_MODEL
    from core.intent import IntentResult
    from plugins.sports.dispatch import handle_sports_intent

    today = date.today().strftime("%B %d, %Y")
    system = _SYSTEM_PROMPT.format(today=today)

    client = AsyncOpenAI(api_key=OPENAI_API_KEY)

    try:
        resp = await client.chat.completions.create(
            model=GPT_CHAT_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": query},
            ],
            tools=_SPORTS_TOOLS,
            tool_choice="required",  # GPT must call one of the provided functions
            temperature=0,
        )

        msg = resp.choices[0].message

        if not msg.tool_calls:
            logger.warning(f"gpt_nl: no tool call returned for query: {query!r}")
            return False

        tool_call = msg.tool_calls[0]
        fn_name = tool_call.function.name

        try:
            args = json.loads(tool_call.function.arguments)
        except (json.JSONDecodeError, AttributeError):
            args = {}

        logger.info(f"gpt_nl: GPT selected {fn_name}({args}) for: {query!r}")

        # ── Escape hatch ─────────────────────────────────────────────────────
        if fn_name == "not_sports":
            logger.debug(f"gpt_nl: not_sports for query: {query!r}")
            return False

        # ── Map function call → IntentResult → existing dispatch handlers ────
        if fn_name == "get_scores":
            intent_result = IntentResult(
                intent="sports_scores",
                entities={
                    "league": args.get("league", ""),
                    "team": args.get("team", ""),
                },
                confidence="gpt_function",
                raw=query,
            )

        elif fn_name == "get_standings":
            intent_result = IntentResult(
                intent="sports_standings",
                entities={"league": args.get("league", "")},
                confidence="gpt_function",
                raw=query,
            )

        elif fn_name == "get_schedule":
            intent_result = IntentResult(
                intent="sports_schedule",
                entities={
                    "league": args.get("league", ""),
                    "team": args.get("team", ""),
                },
                confidence="gpt_function",
                raw=query,
            )

        elif fn_name == "get_leaders":
            intent_result = IntentResult(
                intent="sports_leaders",
                entities={
                    "query": query,
                    "league": args.get("league", ""),
                    "stat_category": args.get("stat", ""),
                },
                confidence="gpt_function",
                raw=query,
            )

        elif fn_name == "get_player_stats":
            intent_result = IntentResult(
                intent="sports_player_stats",
                entities={"query": args.get("player_name", query)},
                confidence="gpt_function",
                raw=query,
            )

        elif fn_name == "get_player_gamelog":
            intent_result = IntentResult(
                intent="sports_player_gamelog",
                entities={"query": args.get("player_name", query)},
                confidence="gpt_function",
                raw=query,
            )

        else:
            logger.warning(f"gpt_nl: unknown function '{fn_name}' for: {query!r}")
            return False

        await handle_sports_intent(intent_result, update, context)
        return True

    except Exception as e:
        logger.error(f"gpt_nl: error dispatching query {query!r}: {e}", exc_info=True)
        return False

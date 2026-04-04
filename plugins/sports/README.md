# Sports Pack Plugin for Alfred

A comprehensive sports plugin providing live scores, standings, schedules, and sports betting tracking for the Alfred Telegram bot.

## Overview

The Sports Pack integrates with ESPN's free public API to deliver real-time sports data across 10 major leagues:
- **NFL**, **NBA**, **MLB**, **NHL** (US Professional)
- **NCAAF**, **NCAAB** (US College)
- **EPL**, **MLS**, **Bundesliga**, **La Liga** (International Soccer)

## Features

### Live Scores (`/scores`)
- Get current and recent game scores
- Filter by league or team
- Shows game status: Live 🔴 | Final ✓ | Scheduled ⏱

### League Standings (`/standings`)
- View rankings with W-L records
- Win percentage and games behind
- Division-based grouping

### Game Schedule (`/schedule`)
- Upcoming games for next 7 days
- Team-specific schedules
- Venue and date/time information

### Settings & Alerts (`/sports`)
- Add favorite teams for monitoring
- Enable/disable game day alerts
- Set betting bankroll and unit size
- Toggle Kelly Criterion fraction

### Betting Tracker (`/bets`)
- Log bets with odds and stake
- Track results: win/loss/push/pending
- Calculate P&L automatically
- View betting statistics: win rate, ROI, total profit/loss
- Parlay odds calculator
- Kelly Criterion bet sizing

## Architecture

```
plugins/sports/
├── __init__.py          # Plugin metadata (PLUGIN_META)
├── config.py            # League definitions, settings, file paths
├── espn_api.py          # ESPN API client (async, error-tolerant)
├── formatting.py        # Telegram HTML formatting
├── data.py              # Bet tracking and persistence
├── commands.py          # Command handlers (/scores, /standings, etc)
├── dispatch.py          # Intent router
├── keywords.py          # Layer 1 regex rules
├── callbacks.py         # Interactive UI button handlers
├── jobs.py              # Background tasks (score updates, alerts)
└── README.md            # This file
```

## File Descriptions

### `__init__.py`
- Defines `PLUGIN_META` dict for plugin loader
- 5 Telegram commands, 9 intents, 2 background jobs, 1 callback pattern
- Registers with Alfred's plugin auto-discovery system

### `config.py`
- League slugs and ESPN API URL builders
- Settings management: favorite teams, alerts, bankroll
- Data file paths in `/data/sports_plugin/`
- Helper: `normalize_league()`, `get_league_info()`, etc

### `espn_api.py`
- Async aiohttp client for ESPN's free public API
- Functions: `get_scores()`, `get_standings()`, `get_schedule()`, `get_teams()`, `get_team_info()`
- Robust error handling: returns `None` on any failure, never crashes
- 10-second timeout per request

### `formatting.py`
- Telegram HTML message formatting
- Functions: `format_scoreboard()`, `format_standings()`, `format_schedule()`, `format_game_preview()`
- Emoji-enhanced, readable output

### `data.py`
- Bet history persistence (JSON file)
- CRUD operations: `add_bet()`, `get_bets()`, `update_bet()`, `delete_bet()`
- Statistics: `get_bet_stats()` (ROI, win rate, P&L)
- Utilities: `calculate_kelly_fraction()`, `calculate_parlay_odds()`, odds conversion

### `commands.py`
- `/scores` — Get live scores
- `/standings` — View league standings
- `/schedule` — Upcoming games
- `/sports` — Setup favorite teams and alerts
- `/bets` — Manage betting records
- All use ESPN API, format with Telegram HTML, send responses

### `dispatch.py`
- Main intent router: `handle_sports_intent()`
- Maps all 9 intents to appropriate command handlers
- Called by plugin_loader when Layer 1/2 intent detection finds a sports intent

### `keywords.py`
- Layer 1 regex rules (fast, no GPT needed)
- ~15 patterns: "what's the score", "standings", "who's playing", "bet", etc
- Returns `IntentResult` with intent and entities
- Confidence: "keyword"

### `callbacks.py`
- Interactive inline button handlers
- League selection, setup flows, stats, refresh buttons
- Pattern: `sports_*` (registered in PLUGIN_META)

### `jobs.py`
- `job_score_updates()` — Every 30 minutes
  - Checks favorite teams for score updates
  - Sends notification when game finishes
- `job_game_alerts()` — Daily at 9 AM
  - Alerts about upcoming games (next 48 hours)
  - Respects `alerts_enabled` setting

## Data Persistence

All data stored in `/data/sports_plugin/` (Railway persistent volume):

- **settings.json** — User preferences
  ```json
  {
    "favorite_teams": [
      {"league": "NFL", "team_id": "1", "team_name": "Kansas City Chiefs"}
    ],
    "favorite_leagues": ["NFL", "NBA"],
    "alerts_enabled": true,
    "bankroll": 1000.0,
    "unit_size": 50.0,
    "kelly_fraction": 0.25
  }
  ```

- **bets.json** — Bet history
  ```json
  {
    "id": "uuid",
    "date": "2024-01-15T14:30:00Z",
    "league": "NFL",
    "game": "Chiefs vs Dolphins",
    "bet_type": "moneyline",
    "pick": "Kansas City Chiefs",
    "odds": -110,
    "stake": 100.0,
    "result": "win",
    "pnl": 90.91,
    "unit_size": 1.0,
    "notes": "Super Bowl prediction"
  }
  ```

## Usage Examples

### Via Commands

```
/scores NFL
/standings NBA
/schedule EPL Tottenham
/sports setup
/bets view
```

### Via Natural Language (Intent Detection)

```
"What's the score in the NBA tonight?"
→ Matches Layer 1 keyword rule → sports_scores intent

"Show me the NFL standings"
→ Matches Layer 1 keyword rule → sports_standings intent

"Who's playing tomorrow?"
→ Matches Layer 1 keyword rule → sports_schedule intent

"Log a new bet: Chiefs -110 $100"
→ GPT Layer 2 → sports_bet_add intent
```

## ESPN API Endpoints

The plugin uses ESPN's free public API:

- Scoreboard: `https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard`
- Standings: `https://site.api.espn.com/apis/v2/sports/{sport}/{league}/standings`
- Schedule: Same as scoreboard with optional `dates` parameter
- Teams: `https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/teams`

League slugs:
- NFL: `football/nfl`
- NBA: `basketball/nba`
- MLB: `baseball/mlb`
- NHL: `hockey/nhl`
- NCAAF: `football/college-football`
- NCAAB: `basketball/mens-college-basketball`
- EPL: `soccer/eng.1`
- MLS: `soccer/usa.1`
- Bundesliga: `soccer/ger.1`
- La Liga: `soccer/esp.1`

No authentication required. Rate limits are generous.

## Integration with Alfred

The plugin is auto-discovered by Alfred's plugin loader (`core/plugin_loader.py`):

1. Bot starts → loader scans `plugins/` directory
2. Finds `plugins/sports/__init__.py` with `PLUGIN_META`
3. Registers commands, intents, keyword rules, jobs, callbacks
4. At runtime:
   - Commands trigger via `/scores`, `/standings`, etc
   - Intents detected by Layer 1 (keywords) or Layer 2 (GPT)
   - Background jobs run on schedule
   - Inline button presses dispatch to callbacks

## Error Handling

- All ESPN API calls return `None` on failure (network, timeout, parse error)
- Commands gracefully degrade: "Could not fetch data from ESPN"
- Logging throughout for debugging (`logger.error()`, `logger.debug()`)
- Never crashes the bot, always sends a response to user

## Future Enhancements

- [ ] Team injury reports
- [ ] Playoff brackets and tournament tracking
- [ ] Expert picks and consensus predictions
- [ ] Streaming links for games
- [ ] Live-game alert notifications
- [ ] Betting line comparisons (DraftKings, FanDuel, etc)
- [ ] Fantasy sports tracking
- [ ] Player stats and career history

## Author

Alfred Sports Pack v1.0.0

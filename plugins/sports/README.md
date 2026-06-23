# Sports Pack Plugin for Marvin

A comprehensive sports plugin providing live scores, standings, schedules, player/team stats, league leaders, and betting tracking — with full natural-language query support via GPT function-calling.

## Overview

The Sports Pack uses two data sources:
- **ESPN public API** (free, no key) — scores, standings, schedules, box scores across 10 leagues
- **API-Sports** (free 100 req/day, `API_SPORTS_KEY` required) — player/team stats, league leaders

Supported leagues: **NFL, NBA, MLB, NHL, NCAAF, NCAAB, EPL, MLS, Bundesliga, La Liga**

## Features

### Live Scores (`/scores`)
- Yesterday's results by default (avoids showing today's empty early schedule)
- Filter by league or team
- Shows game status: Live 🔴 | Final ✓ | Scheduled ⏱

### League Standings (`/standings`)
- View rankings with W-L records, sorted by wins descending
- Division-based grouping

### Game Schedule (`/schedule`)
- Upcoming games for next 7 days
- Team-specific schedules with venue and time

### Player & Team Stats (`/stats`)
- `/stats player [name]` — Season averages and totals
- `/stats team [league] [team]` — Team-level statistics
- `/stats gamelog [name]` — Recent game-by-game log
- `/stats roster [league] [team]` — Current roster
- ESPN-first → API-Sports fallback; GPT fuzzy name resolution (handles nicknames/misspellings)

### League Leaders (`/leaders`)
- Top performers by stat category across a league
- Filter by specific stat (e.g. "who leads the NBA in blocks")

### Settings & Alerts (`/sports`)
- Add favorite teams for monitoring
- Enable/disable game day alerts
- Set betting bankroll and unit size
- **📊 Briefing Settings** — in-app toggle menu for Reddit highlights, YouTube top plays, player tracking
- `/sports addplayer <name>` — add a player to your morning briefing tracker
- `/sports removeplayer <name>` — remove a tracked player

### Betting Tracker (`/bets`)
- Log bets with odds and stake
- Track results: win/loss/push/pending
- P&L, ROI, win rate statistics
- Parlay odds calculator and Kelly Criterion bet sizing

### Morning Briefing Sports Section (`/briefing`) — Phase 3
Injected automatically into the daily briefing if the buyer has favorite teams/leagues configured.

- **Yesterday's results** for all favorite leagues — every game, not just favorites
- **Top 3 performers per game** — ranked by PTS + REB×0.5 + AST×0.5 composite from ESPN box score API
  - Core stats always shown: pts, reb, ast
  - **3PT:** shown as `X/Y 3PT` if ≥4 attempts + ≥35% efficiency + ≥2 made (e.g. `5/11 3PT`)
  - **STL / BLK:** shown if ≥2 (1 is routine; 2+ is a standout defensive night)
- **Favorite team games** highlighted with ⭐
- **Reddit highlights** (default ON) — top Highlight-flair posts per league from `r/<sub>/top.json` (free, no key, rate-limited ~60 req/min). Filters to video posts (Streamable, v.redd.it, YouTube, etc.)
- **YouTube top plays** (default OFF) — if `YOUTUBE_API_KEY` is set, fetches the actual top-play video from the official league channel. Without the key, generates a YouTube search URL (no API cost, always works)
- **Tracked player stat lines** (default OFF) — add players with `/sports addplayer <name>`. Stats pulled from already-fetched box scores — zero extra API calls. Shows "did not play yesterday" if player wasn't in any box score.

**Configuring via Telegram:**
- `/sports` → tap **📊 Briefing Settings** to toggle Reddit/YouTube/player tracking on/off
- `/sports addplayer LeBron James` — add a tracked player
- `/sports removeplayer LeBron James` — remove a tracked player
- Turning player tracking ON shows a one-time API quota warning popup

**API cost summary:**
| Source | Cost | Notes |
|---|---|---|
| ESPN scoreboard + box score | Free, no key | ~2 calls/league/day |
| Reddit highlights | Free, no key | ~1 call/subreddit/day |
| YouTube (no key) | Free | Search URL, no API call |
| YouTube (with key) | Free tier: 10K units/day | ~2 units per query |
| Player tracking | Free | Scanned from box scores already fetched |

Section silently skipped if no favorite teams/leagues are set.

**Buyer settings (in `settings.json`):**
```
briefing_reddit_highlights   bool   default True   — Reddit highlight posts
briefing_youtube_top_plays   bool   default False  — YouTube top plays links
briefing_track_fav_players   bool   default False  — Favorite player stat lines
briefing_favorite_players    list   default []     — Player display names to track
```

### Natural Language Sports Queries (Phase 2)
Any sports-related message that doesn't match a specific command is routed through GPT function-calling. GPT picks the correct function and parameters.

Supported NL patterns:
```
"NBA scores" / "who won last night"     → get_scores
"show me NBA standings"                  → get_standings
"who's playing this weekend"             → get_schedule
"who leads the league in blocks"         → get_leaders
"how many ppg is Jokic averaging"        → get_player_stats
"show me Jokic's last 5 games"           → get_player_gamelog
"what's the weather like" (non-sports)   → falls back to /ask
```

## Architecture

```
plugins/sports/
├── __init__.py          # Plugin metadata (PLUGIN_META) — commands, intents, jobs
├── config.py            # League definitions, ESPN API URL builders, settings
├── espn_api.py          # Async ESPN public API client (scores, standings, schedule)
├── api_sports.py        # Async API-Sports client (player/team stats, leaders, search)
├── stats_api.py         # Unified stats layer: ESPN-first → API-Sports fallback
├── gpt_nl.py            # Phase 2: GPT function-calling dispatcher for NL sports queries
├── briefing.py          # Phase 3: Morning briefing section (scores + top performers + Reddit/YouTube)
├── commands.py          # Command handlers: /scores, /standings, /schedule, /sports, /bets, /stats, /leaders
├── dispatch.py          # Intent → command routing, stat category filtering
├── keywords.py          # Layer 1 regex rules (fast-path); NL catch-all routes to gpt_nl.py
├── formatting.py        # Telegram HTML message formatters
├── data.py              # Bet tracking and persistence
├── callbacks.py         # Inline keyboard button handlers
├── jobs.py              # Background tasks (score updates, game alerts)
├── betting.py           # Screenshot analysis, line comparison, bet calculator
├── charts.py            # matplotlib chart generation (P&L, ROI, win rate)
└── photo_handler.py     # Sportsbook screenshot detection
```

## Intent Routing

Two-layer system:

**Layer 1 — Keyword regex (fast, no GPT cost)**
- ~15 patterns for obvious queries: "score", "standings", "who's playing", "bet", "who leads", etc.
- Returns `IntentResult` with `confidence="keyword"`
- Broad NL catch-all fires last: routes unmatched sports-ish messages to `sports_nl_query`

**Layer 2 — GPT classification (fallback)**
- Fires only when Layer 1 has no match
- GPT classifies against registered intent list from `gpt_intent_block` in PLUGIN_META

**Phase 2 — GPT function-calling (for NL queries)**
- `sports_nl_query` intent → `gpt_nl.gpt_sports_dispatch()`
- GPT selects from 7 function schemas and extracts parameters
- Maps result back to existing dispatch handlers — no duplicate logic

## Data Persistence

All data stored in `/data/sports_plugin/` (Railway persistent volume):

- **settings.json** — User preferences (favorite teams, alerts, bankroll, unit size, kelly fraction)
- **bets.json** — Bet history

## Usage Examples

### Via Commands

```
/scores NFL
/standings NBA
/schedule EPL Tottenham
/stats player Nikola Jokic
/stats gamelog Patrick Mahomes
/leaders NBA
/sports setup
/bets view
```

### Via Natural Language

```
"NBA scores"                         → /scores NBA
"who leads the league in blocks"     → /leaders (blocks filter)
"how many ppg is Jokic averaging"    → /stats player Nikola Jokic
"show me last night's results"       → /scores (yesterday)
"Jokic's last 5 games"               → /stats gamelog Nikola Jokic
```

## ESPN API Endpoints

| Endpoint | Used For |
|---|---|
| `site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard` | Scores |
| `site.api.espn.com/apis/v2/sports/{sport}/{league}/standings` | Standings |
| `site.api.espn.com/apis/site/v2/sports/{sport}/{league}/teams/{id}/schedule` | Schedule |
| `site.web.api.espn.com/apis/common/v3/sports/{sport}/{league}/athletes/{id}/stats` | Player stats |
| `site.web.api.espn.com/apis/common/v3/sports/{sport}/{league}/athletes/{id}/gamelog` | Game log |
| `site.api.espn.com/apis/common/v3/search?query={name}&type=player` | Player search |

No authentication required.

## Error Handling

- All ESPN API calls return `None` on failure — commands degrade gracefully
- `API_SPORTS_KEY` missing: `api_sports.is_available()` returns False; stats silently return nothing (no user-facing error — known limitation)
- GPT function-calling has `not_sports` escape hatch: non-sports NL queries fall back to `/ask`
- Never crashes the bot; always sends a response to the user

*Last updated: April 6, 2026 (Session 13 — Phase 3 fully complete + deployed)*

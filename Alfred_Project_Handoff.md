# Alfred — Personal Assistant Bot
## Project Handoff & Status Doc

---

## What Alfred Is

Alfred has **two simultaneous goals:**

1. **Your personal daily assistant** — a private Telegram bot that connects to Google Calendar, Google Tasks, and OpenAI. You talk to it in plain English (or by voice) and it handles the rest.
2. **A sellable template product** — packaged so that any non-technical buyer can deploy their own Alfred using an LLM (Claude or ChatGPT) as their installer. No coding required.

**Bot username:** @wasonassistant
**Your name for it:** Alfred

---

## Business Model

**Pricing:**
- Base template (Alfred): **$1**
- Add-on packs: **$1 each**

**Why $1?** Low price = low friction = volume. The goal is not to maximize per-sale revenue but to get Alfred into as many hands as possible. Power users who buy the base will buy add-ons.

**Planned add-on packs:**
- 🏈 **Sports Pack** — ESPN scores, standings, team alerts, game previews
- 📈 **Finance/Crypto Pack** — portfolio tracking, price alerts, P&L tracking
- Future: Discord adapter, WhatsApp adapter

**Sales channel:** TBD — Gumroad or Lemon Squeezy

**The key differentiator:** The `setup/SETUP_COMPANION.md` is an LLM-powered installer. Buyer pastes it into Claude or ChatGPT and the AI walks them through the entire setup — BotFather, Google Cloud, Railway, all variables — outputting a single copy-paste block for Railway. Nobody else is packaging their bot template this way.

**Add-on architecture:** Each add-on is a self-contained Python file dropped into `alfred/plugins/`. No changes to core code required.

---

## Current Status: 🔨 IN PROGRESS — Phase 4A (Cross-Platform Architecture) — April 6, 2026

- Core bot: Deployed and running on Railway, all 20+ commands working
- Sports Pack: **Phases 1, 1.5, 2, and 3 complete. Full regression tested April 6, 2026.**
  - Working (confirmed via Telegram): `/scores` (yesterday's results), `/standings` (sorted by wins), `/schedule`, `/sports`, `/bets`, `/stats player`, `/stats team`, `/stats gamelog`, `/stats roster`, `/leaders`
  - Working (confirmed): GPT date awareness, GPT fuzzy player name resolution (nicknames/misspellings → full names)
  - Working (confirmed): NL sports queries via GPT function-calling — "who leads the NBA in blocks", "how many ppg is Jokic averaging", "NBA scores", "show me Jokic stats", "NBA standings", etc.
  - **Removed:** Player compare (`/compare`) — feature was unreliable across sports due to cross-sport API incompatibilities. Removed entirely April 6, 2026.
  - Rate limit concern: Multi-league soccer fallback can burn ~10-20 API-Sports requests per failed player lookup (100/day free tier)
- Sports Morning Briefing: **Phase 3 fully complete + deployed April 6, 2026.**
  - `plugins/sports/briefing.py` — daily recap in `/briefing`: yesterday's results for favorite leagues, top 3 performers per game (PTS + REB×0.5 + AST×0.5), ⭐ favorite team callout, 3PT% shown as X/Y if ≥4 attempts + ≥35%, STL/BLK shown if ≥2
  - `/sports → 📊 Briefing Settings` — in-app toggle menu for Reddit highlights, YouTube top plays, player tracking on/off; add/clear tracked players
  - `/sports addplayer <name>` / `/sports removeplayer <name>` — manage tracked players
  - Tracked player stat lines appear in briefing pulled from already-fetched box scores (zero extra API calls)
  - Configurable via setup wizard; section silently skipped if no favorite teams/leagues set

---

## Where Everything Lives

| Thing | Location |
|---|---|
| Code | GitHub → `wasonaiemail-dev/telegram-assistant` |
| Hosting | Railway → project `alluring-learning` → service `worker` |
| Bot | Telegram → @wasonassistant |
| Persistent data | Railway `/data` volume (reminders, memory, habits, etc.) |

---

## Tech Stack

- **Python 3.10** running on Railway
- **python-telegram-bot 22.6** — bot framework
- **OpenAI API** — intent classification, AI responses, voice transcription, GPT function-calling for sports NL (GPT-4o-mini / GPT-4o / Whisper)
- **Google Calendar & Tasks API** — calendar and task management
- **Open-Meteo** — free weather (no key needed)
- **Serper.dev** — optional live web search in /ask
- **ESPN public API** — scores, standings, schedules (free, no key, fallback source)
- **API-Sports** — detailed player/team stats, leaders (free 100 req/day)
- **The-Odds-API** *(adding next)* — betting odds, spreads, props, futures (free 500 credits/mo)
- **Railway** — hosting with persistent /data volume

---

## Environment Variables (set in Railway → Variables)

All 22 variables are configured in Railway. They are:

`TELEGRAM_TOKEN`, `ALLOWED_USER_ID`, `BOT_NAME`, `BOT_USERNAME`, `OPENAI_API_KEY`, `GOOGLE_CREDENTIALS`, `SERPER_API_KEY`, `TIMEZONE`, `WEATHER_LAT`, `WEATHER_LON`, `HOME_CITY`, `QUOTE_TYPE`, `BRIEFING_HOUR`, `BRIEFING_MINUTE`, `HABIT_NUDGE_HOUR`, `HABIT_NUDGE_MINUTE`, `TRAVEL_WEATHER_HOUR`, `TRAVEL_WEATHER_MINUTE`, `WEEKLY_SUMMARY_HOUR`, `WEEKLY_SUMMARY_MINUTE`, `WEEKLY_SUMMARY_WEEKDAY`, `API_SPORTS_KEY`

**Critical env vars (bot won't start without these):**
- `TELEGRAM_TOKEN` — from BotFather
- `ALLOWED_USER_ID` — your Telegram user ID
- `OPENAI_API_KEY` — OpenAI API key
- `GOOGLE_CREDENTIALS` — full JSON from Google Cloud credentials

**Sports plugin variables (optional — bot works without them, ESPN is free fallback):**
- `API_SPORTS_KEY` — Get from https://dashboard.api-football.com/register (free, 100 req/day per sport). Value: `4326891bc76a7ead7932910d21c771f6`. **CONFIRMED SET in Railway as of April 6, 2026.** Without this key, all API-Sports calls silently return None (the `is_available()` function returns False), making soccer compare and any non-ESPN stats source completely non-functional with no visible error to the user.

---

## Features Built

| Feature | Command | Status |
|---|---|---|
| Morning Briefing | `/briefing` | ✅ Tested |
| Calendar | `/calendar` | ✅ Tested |
| Todos | `/todos` | ✅ Tested |
| Shopping Lists | `/shopping` | ✅ Tested |
| Notes | `/notes` | ✅ Tested |
| Reminders | `/reminders` | ✅ Tested (bug fixed) |
| Habits | `/habits` | ✅ Tested |
| Memory | `/memory` | ✅ Tested |
| AI Chat | `/ask` | ✅ Tested |
| Gifts | `/gifts` | ✅ Tested |
| Contacts | `/contacts` | ✅ Tested |
| Weekly Summary | auto Monday | ✅ |
| Event Prep | auto nightly | ✅ |
| Travel Weather | auto daily | ✅ |
| Meal Planning | `/meals` | ✅ Tested |
| Workout Tracking | `/workout` | ✅ Tested |
| Journal | `/journal` | ✅ Tested |
| Mood Tracker | `/mood` | ✅ Tested (bug fixed) |
| Read Later / Links | `/readlater` | ✅ Tested |
| Reply Assist | natural language | ✅ |
| Data Export | `/export` | ✅ Tested (sends .xlsx) |
| Setup Wizard | `/setup` | ✅ |
| Sports Scores | `/scores` | ✅ Tested |
| Sports Standings | `/standings` | ✅ Tested |
| Sports Schedule | `/schedule` | ✅ Tested |
| Sports Config | `/sports` | ✅ Tested |
| Bet Tracker | `/bets` | ✅ Tested |
| Player/Team Stats | `/stats` | ✅ Tested (ESPN + API-Sports fallback) |
| Leaders | `/leaders` | ✅ Tested |
| Sports NL queries | natural language | ✅ Phase 2 complete — GPT function-calling dispatches all NL sports queries |
| Sports Morning Briefing | via `/briefing` | ✅ Phase 3 complete — scores, top 3 performers (3PT%/STL/BLK thresholds), Reddit highlights, YouTube, player tracking |
| Sports Briefing Settings | `/sports` → 📊 | ✅ In-app toggle menu for Reddit/YouTube/player tracking; addplayer/removeplayer commands |

---

## Bugs Fixed (All Sessions)

### Session 1 — Reminders type error
**File:** `features/reminders.py`
**Error:** `job_reminders error: can only concatenate str (not "int") to str`
**Root cause:** Two issues — (1) `_next_id()` failed when IDs were strings; (2) `due` date field stored as int, crashing `due[:10]` slicing.
**Fix:** Added `int()` cast in `_next_id()` and `str()` casts in due-date helpers.
**Commit:** `Fix reminders type error: cast due date to str`

### Session 2 — `/briefing` crash (UUID reminder IDs)
**File:** `core/data.py`
**Error:** `ValueError: invalid literal for int() with base 10: '07b2f52d'`
**Root cause:** `_next_id()` called `int()` on UUID hex strings (e.g. `'07b2f52d'`) generated by an earlier bot version.
**Fix:** Wrapped `int(raw)` in try/except to silently skip any non-numeric IDs.
**Commit:** `Fix _next_id: handle UUID/non-numeric reminder IDs gracefully`

### Session 2 — `add todo` natural language broken
**Files:** `features/todos.py`, `core/intent.py`
**Root cause 1:** `todos.py` read `entities.get("task")` but both the keyword rule and GPT classifier output the key `"text"` — task was always empty, triggering the "What should I add?" fallback even on valid inputs.
**Fix:** Changed to `(entities.get("task") or entities.get("text") or "").strip()`
**Root cause 2:** Keyword rule only matched `"add X to my todo list"`, not the bot's own suggested format `"add todo X"`.
**Fix:** Updated regex to `^(?:add\s+(?:todo|task)\s+(.+)|add\s+(.+?)\s+to\s+(?:my\s+)?(?:todo|task)s?(?:\s+list)?)$`
**Commits:**
- `Fix todo add: read "text" entity key as fallback to "task"`
- `Fix intent: add "add todo X" keyword pattern for TODO_ADD`

---

## Known Issues

### `/mood` state drop — ✅ Fixed (Session 3)
After `/mood` prompts "How are you feeling today? (1–10)?", sending a bare number like `7` was intercepted by the general intent classifier instead of the mood handler.
**Fix:** Added `_awaiting_rating` state flag in `features/mood.py`. When `/mood` is called, the flag is set. `bot.py` now checks `is_mood_awaiting()` before intent classification and routes typed numbers (1-10, with optional note) directly to `handle_mood_text_reply()`. Flag clears on button press or text reply.

### `/checkauth` false-positive warning — ✅ Fixed (Session 3)
When the Google access token had < 2 hours remaining, `/checkauth` showed "One or more services failed" even though APIs worked fine.
**Fix (two parts):**
1. `get_creds()` in `core/google_auth.py` now proactively refreshes the token when < 5 minutes remain (not just when already expired), preventing edge-case API failures.
2. `/checkauth` display updated — access tokens expire hourly which is normal, so the warning threshold was removed. Now shows "✅ Access token valid (X min remaining, auto-refreshes)" instead of a misleading ⚠️.

### Google Tasks API 403 — ✅ Fixed (Session 4)
All Tasks-based features (todos, notes, shopping, gifts) were silently failing — returning empty lists instead of errors. `/checkauth` correctly flagged "One or more services failed" but features appeared to work because the adapter (`adapters/google_tasks.py`) catches API exceptions gracefully and returns `[]` / `None`.
**Root cause:** The Google Tasks API was never enabled in Google Cloud Console (console.cloud.google.com → APIs & Services → Library). Calendar API was enabled, Tasks was not.
**Fix:** Enabled "Google Tasks API" in Cloud Console + ran `/auth` to re-authorize with fresh tokens.
**Lesson learned:** When `/checkauth` shows a service failure, it's real — don't assume features are working just because they return "Nothing here" instead of an error. The adapters silently swallow API failures.

### API-Sports calls silently fail when key is missing — ⚠️ By Design but Dangerous
`api_sports.py` line 138: if `API_SPORTS_KEY` is empty, `_api_fetch()` returns `None` with only a debug-level log. This means every feature that depends on API-Sports (non-ESPN stats, leaders) silently returns nothing to the user. There is NO user-facing error message. This is a design choice for graceful degradation but it makes debugging extremely difficult.
**Recommendation:** Consider adding a user-facing warning when `is_available()` returns False and a command specifically needs API-Sports data.

### Multi-league soccer fallback rate limit risk — ⚠️ Open
In `stats_api.py`, when a soccer player's league can't be resolved, the code cycles through up to 5 leagues (epl, mls, laliga, bundesliga, plus the original). Each attempt = search + stats = 2 API-Sports requests. With previous-season fallback doubling attempts, worst case is ~20 requests for a single failed player lookup against a 100/day free tier. Heavy soccer usage could exhaust the daily limit quickly.

### ESPN has no stats for some sports/players — ⚠️ Known Limitation
ESPN's `/athletes/{id}/stats` endpoint returns empty for some sports (notably NFL). Patrick Mahomes name resolution works (via GPT fuzzy match) but stats come back empty. This is an ESPN API limitation, not a bug.

---

## What Still Needs to Be Done

**Completed (previous sessions):**
- ~~Run `/auth` in Telegram~~ ✅
- ~~Fix `/mood` conversation state~~ ✅
- ~~Fix `/checkauth` false-positive~~ ✅
- ~~Enable Google Tasks API~~ ✅
- ~~Build Sports Pack add-on~~ ✅ (Session 5)
- ~~Add `aiohttp` to requirements.txt~~ ✅

**Immediate (critical):**
1. **Add payment method to Railway** — trial may be expired or close to it. Go to railway.com → account settings → billing.

**🏗️ MAJOR: Sports Plugin Architecture Redesign (Session 9+) — DECISIONS FINALIZED**

The current ESPN scraping + keyword regex approach has been identified as fragile and limited. Rebuilding with proper APIs and GPT function-calling.

**The Problem:**
- ESPN APIs are undocumented, inconsistent between v2/v3, and break unpredictably
- Keyword regex + stop words NL intent system can't handle the variety of sports queries (leaders, comparisons, betting, trivia, history)
- Stop words are incomplete — words like "career", "many", "goals", "points", "averaging", "per" pollute player name searches
- NL intent misroutes queries (e.g., "who won DPOY last year" triggers scores because keyword "NBA" matches)

**✅ FINAL ARCHITECTURE (all decisions confirmed April 5, 2026):**

1. **API-Sports** (primary stats/scores API) — Free tier: 100 requests/day per sport, permanent, no credit card. Paid: $19/mo for higher limits. All endpoints and all competitions included at every tier. Covers basketball, football, baseball, hockey, soccer, and more.
   - Docs: https://api-sports.io/
   - Free tier is sufficient for a personal bot answering on-demand queries
   - Each buyer sets up their own API key (template model — no commercial license issue)

2. **ESPN** (free fallback — KEEP existing code) — No API key needed, covers 10+ leagues. Used for scores, standings, schedules (proven working endpoints from sessions 5-8). Serves as first-try source for basic queries.
   - **Failover pattern:** ESPN first → API-Sports fallback. If ESPN dies permanently, API-Sports becomes primary with zero code changes (just remove the ESPN call).
   - No coding issue with dual-source — it's a clean try/except failover.

3. **The-Odds-API** (betting odds — SEPARATE PLUGIN) — Free: 500 credits/mo. Paid: $30/mo for 20K credits. Aggregates ~40 bookmakers.
   - Betting features are a **separate plugin** (`plugins/betting/`), NOT bundled with sports stats
   - Each buyer sets up their own Odds API key

4. **GPT function-calling** (replaces keyword regex + stop words) — Uses existing OpenAI key already in Railway. All NL sports messages go to GPT, GPT decides which API tool to call. Eliminates stop word/routing issues entirely.

5. **Shared player/team search module** (`plugins/shared/player_search.py`) — Both sports and betting plugins import from here. Resolves "Jokic" → Nikola Jokic, Denver Nuggets, NBA. Single source of truth for lookups, bugs fixed once.

**✅ KEY DESIGN DECISIONS:**
- **Template model:** Bot ships without API keys. Each buyer configures their own API-Sports key, Odds API key, etc. This means MySportsFeeds (free for personal, paid for commercial) IS viable since each user is "personal use." But we're going with API-Sports for its simpler free tier.
- **Selling BOTH:** The whole bot as a template ($1) AND individual plugin packs as add-ons ($1 each)
- **OpenAI key:** Reuse the existing key in Railway for GPT function-calling
- **ESPN kept:** No downside to keeping ESPN for scores/standings/schedule — those v2 endpoints are stable. Only problem areas (detailed stats, leaders, comparisons) get replaced by API-Sports.
- **Multi-sport:** NBA, NFL, MLB, NHL, soccer/World Cup — all covered by API-Sports
- **Multiple sessions:** Build this right, don't rush. Test thoroughly before moving on.

**🔨 BUILD PLAN (Session 9+):**

**Phase 1 — API-Sports Integration (Sessions 9-10) — COMPLETE**
- [x] Sign up for API-Sports free tier, get API key
- [x] Add `API_SPORTS_KEY` to Railway env vars (confirmed set April 6, 2026)
- [x] Create `plugins/sports/api_sports.py` — async client for API-Sports endpoints (1060+ lines)
- [x] Implement: player stats, team stats, league leaders, player comparisons
- [x] Wire up ESPN-first → API-Sports-fallback pattern (in `stats_api.py`)
- [x] Dynamic season computation (replaces hardcoded "2024")
- [x] Previous-season fallback for all sports (current season → previous season retry)
- [x] Multi-league soccer fallback (tries epl, mls, laliga, bundesliga if league unknown)
- [x] **TESTED**: "who leads the nba in blocks" — working via Phase 2 GPT function-calling
- [x] **TESTED**: Previous-season fallback — working
- [ ] ~~Soccer compare~~ — feature removed April 6, 2026 (unreliable cross-sport API incompatibilities)

**Phase 1.5 — NL Routing & Name Resolution Fixes (Session 10) — COMPLETE**
- [x] GPT fuzzy player name resolution (`gpt_resolve_player_name()` in `player_search.py`)
- [x] `search_with_fuzzy_fallback()` — tries ESPN search first, falls back to GPT name resolution
- [x] Added "who leads" keyword regex to `keywords.py` (was missing, caused NL queries to go to GPT fallback)
- [x] Fixed GPT date awareness — injected `{today}` into system prompts so GPT knows current date
- [x] Fixed `/scores` to show yesterday's results by default (not today's empty schedule)
- [x] Fixed standings sort order (by wins descending)
- [x] Added `_extract_stat_category()` and `_filter_leaders_category()` to filter leaders by specific stat
- [x] ~~STILL MISSING: Many NL query patterns fall to GPT Layer 2~~ — **FIXED by Phase 2**

**Phase 2 — GPT Function-Calling NL (April 6, 2026) — ✅ COMPLETE**
- [x] Created `plugins/sports/gpt_nl.py` — GPT function-calling dispatcher
- [x] Function schemas: get_scores, get_standings, get_schedule, get_leaders, get_player_stats, get_player_gamelog, not_sports (escape hatch)
- [x] Broad NL catch-all keyword rule in keywords.py routes unmatched sports queries to `sports_nl_query` intent → gpt_nl.py
- [x] Layer 1 keyword rules kept as fast-path; GPT only fires for unmatched NL queries
- [x] Regression tested: all 8 NL query types passing
- [x] Removed player compare feature (unreliable cross-sport API mismatch)

**Phase 3 — Sports Morning Briefing (April 6, 2026) — ✅ COMPLETE**
- [x] Created `plugins/sports/briefing.py` — async sports section builder
- [x] Per-game top 3 performers (PTS + REB×0.5 + AST×0.5 composite) via ESPN box score API
- [x] Favorite team games highlighted with ⭐
- [x] Optional Reddit highlights (top Highlight-flair posts via `r/<league>/top.json`, default ON)
- [x] Optional YouTube top plays link (API key → direct video; no key → search URL fallback, default OFF)
- [x] 4 new briefing settings added to `plugins/sports/config.py` defaults
- [x] Hooked into `features/briefing.py` `_SECTION_BUILDERS["sports"]`
- [x] Added `"sports"` to `_BRIEFING_DEFAULT_ORDER` and `_BRIEFING_ALL_SECTIONS` in `core/data.py`
- [x] Added `sports` to setup wizard prompt with cost warnings in `features/setup.py`
- [x] 3PT displayed as `X/Y 3PT` format — threshold ≥4 attempts + ≥35% efficiency + ≥2 made
- [x] STL/BLK threshold raised to ≥2 (filters routine single-steal/block noise)
- [x] `/sports → 📊 Briefing Settings` in-app toggle menu — reddit/youtube/player tracking on/off, add/clear players; cost warning popup on player tracking enable
- [x] `/sports addplayer <name>` and `/sports removeplayer <name>` text commands
- [x] Tracked player stat lines — scanned from already-fetched box scores (zero extra API calls); shows "did not play yesterday" if not found
- [x] Deployed April 6, 2026 — fully confirmed live

**Phase 4 — Cross-Platform Adapters (🔨 IN PROGRESS — Phase 4A complete April 6, 2026)**
Goal: Support Discord (and optionally WhatsApp) as entirely separate platform alternatives to Telegram. Same bot, same plugins, buyer chooses platform. Betting plugin will be built cross-platform from day 1.

**ARCHITECTURE DECISION (April 6, 2026):**
Platform adapters live in `core/` and `adapters/`. The key abstraction is `AlfredContext` — a thin wrapper passed to all feature handlers instead of Telegram's (Update, context). Both Telegram and Discord build an AlfredContext from their platform-specific event objects, then route through the same `alfred_dispatch()`.

**New files (Phase 4A):**
- `core/alfred_context.py` — AlfredContext dataclass: `reply()`, `reply_html()`, `reply_menu()`, `reply_document()`, `send_typing()`, `args`, `user_id`, `chat_id`, `platform`
- `core/html_utils.py` — `html_to_discord()` converter (Telegram HTML → Discord Markdown)
- `core/alfred_dispatch.py` — platform-agnostic intent dispatcher (called by both bot.py and discord_bot.py)
- `adapters/telegram_adapter.py` — `make_context(update, context)` → AlfredContext
- `adapters/discord_adapter.py` — `make_context(message)` → AlfredContext (auto-splits 2000-char Discord limit)
- `discord_bot.py` — full Discord entry point: listens for messages, classifies intent, dispatches to alfred_dispatch; direct command routing for !scores, !standings, !schedule, !stats, !leaders, !ask, !help

**Phase 4A Checklist:**
- [x] AlfredContext abstraction layer built
- [x] HTML → Discord Markdown converter
- [x] Telegram adapter (backward compat — wraps existing Telegram update)
- [x] Discord adapter (auto message splitting, numbered menus for Phase 4 MVP)
- [x] `core/alfred_dispatch.py` — shared dispatcher for all platforms
- [x] bot.py updated to build AlfredContext and use alfred_dispatch (fully backward compatible)
- [x] discord_bot.py — Discord entry point with sports commands + NL routing
- [x] requirements.txt updated (discord.py commented — uncomment for Discord service)
- [x] Procfile comment added for running both Telegram + Discord services on Railway

**Phase 4B — Feature Handler Migration (Next):**
The platform abstraction is built. Each feature handler currently uses (update, context) Telegram types. On Discord, unmigrated features return "coming soon." Migrate in this order (most impactful first):
- [ ] `features/ask.py` → `handle_ask(text, ctx)` — NL chat on Discord
- [ ] `features/todos.py` → `handle_todo_intent(intent, ents, ctx)`
- [ ] `features/reminders.py` → `handle_reminder_intent(intent, ents, ctx)`
- [ ] `features/notes.py` → `handle_note_intent(intent, ents, ctx)`
- [ ] `features/briefing.py` → `send_briefing(ctx)` — full briefing on Discord
- [ ] `plugins/sports/commands.py` → `cmd_scores(ctx)`, `cmd_standings(ctx)`, etc. — use AlfredContext directly
- [ ] All remaining features
- [ ] Discord button menus (discord.ui.View) — replace numbered text menus
- [ ] WhatsApp adapter (Twilio or Meta Cloud API)

**Migration pattern for each handler:**
```python
# OLD (Telegram-only):
async def handle_todo_intent(intent, ents, update: Update, context):
    await update.message.reply_text(text, parse_mode="HTML")

# NEW (any platform):
async def handle_todo_intent(intent, ents, ctx: AlfredContext):
    await ctx.reply_html(text)
```

**Discord setup for buyers:**
1. discord.com/developers → New Application → Bot → copy token
2. Add DISCORD_TOKEN + DISCORD_ALLOWED_USER_ID to Railway env vars
3. Enable "Message Content Intent" in Bot settings
4. Add `discord.py>=2.3.2` to requirements.txt (uncomment the line)
5. Create a second Railway service running `python discord_bot.py`
6. Invite bot to server with OAuth2 "bot" scope + "Send Messages" permission

**Discord vs Telegram differences (documented):**
- Discord: `!command` or `/command` prefix (configurable via DISCORD_COMMAND_PREFIX)
- Discord: no HTML — auto-converted to Markdown by html_to_discord()
- Discord: no inline keyboards (Phase 4 MVP shows numbered text menus)
- Discord: 2000-char message limit (auto-split by adapter)
- Discord: voice transcription not supported (Phase 5 roadmap)

**Phase 4B — WhatsApp adapter (TBD)**
- Twilio or Meta Cloud API — to be decided
- [ ] WhatsApp adapter (platform TBD)

**Phase 5 — Betting Plugin (After Cross-Platform)**
- [ ] Sign up for The-Odds-API free tier, get API key
- [ ] Create `plugins/betting/` as a separate plugin with its own PLUGIN_META
- [ ] Import from `plugins/shared/player_search.py` for lookups
- [ ] Implement: game odds (spreads, moneylines), player props, futures
- [ ] Move existing bet tracker/screenshot features from `plugins/sports/betting.py` to new plugin
- [ ] Built cross-platform from day 1 (uses Phase 4 adapter layer)
- [ ] Test: "what are the odds on the Nuggets game?", "show me Jokic rebound props", "World Cup futures"

**Phase 6 — Polish & Sell-Ready**
- [ ] Add API key setup instructions to SETUP_COMPANION.md
- [ ] Audit all files for hardcoded personal data
- [ ] Error handling: graceful messages when API keys are missing or rate-limited
- [ ] Number selection handler (reply "1" to pick from search results)
- [ ] Final regression test of entire bot

**Setup / workflow:**
- **Set up GitHub Desktop** — File → Add Local Repository → point to your alfred folder.

**Product / business (future):**
- **Build Finance/Crypto Pack add-on** — portfolio tracking, price alerts, P&L.
- **Choose sales channel** — Gumroad or Lemon Squeezy.
- **Review SETUP_COMPANION.md** — ensure it covers all features and is fully generalized.
- **Generalize all features** — audit feature files for hardcoded personal data before packaging.

---

## AI Failures & Lessons (Session 10)

This section documents specific failures made by the AI assistant during session 10. These are recorded so the next session (or a different AI) does not repeat them.

**Failure 1: Repeatedly tried to use Terminal despite being told not to**
The user explicitly stated multiple times not to use Terminal/bash for git operations, preferring Finder and GitHub Desktop. The AI repeatedly attempted `rm` bash commands to delete git lock files, was rejected, and kept trying different bash variations instead of immediately switching to Finder. This happened at least 3 times before the AI finally used Finder.
**Lesson:** When the user says don't use a tool, switch to the alternative IMMEDIATELY. Don't try the same approach with slight variations.

**Failure 2: Failed to identify API_SPORTS_KEY as already set in Railway**
During the audit, the AI claimed `API_SPORTS_KEY` was "NOT in your Railway variables" based on looking at an alphabetically-sorted list and not scrolling to the bottom. The variable was there — it was just below the visible area. The AI then confidently told the user the key was missing when it wasn't. The user had already added it earlier (the "Variable overwrite detected" dialog proved it existed).
**Lesson:** Don't make confident claims about what's NOT on a page if you can't see the full page. Say "I can't see the full list" instead of "it's not there."

**Failure 3: Told the user to add API_SPORTS_KEY as if it were a new task, when it was already documented**
The handoff document already listed `API_SPORTS_KEY` as a required variable (line 79 and line 224 checklist item). The AI treated this as a new discovery during the audit rather than checking the existing documentation first. This made the user feel like the AI wasn't reading its own project docs.
**Lesson:** Always check existing documentation before presenting "findings." Cross-reference against what's already written.

**Failure 4: Recklessly tried to delete git lock files without auditing first**
When git commits failed due to lock files, the AI immediately tried to force-delete them. The user correctly pushed back: "why are you trying to delete the lock file? shouldn't that tell you there is something important in that file? I want you to do a full audit before moving forward." The lock files turned out to be safe to delete (0 bytes, stale), but the AI should have verified that BEFORE attempting deletion.
**Lesson:** When something unexpected blocks you, investigate first, act second. Don't just force through blockers.

**Failure 5: Git push from sandbox failed silently**
The AI tried `git push origin main` from the sandbox which returned HTTP 403 from the proxy. Instead of recognizing that the sandbox doesn't have git push permissions, it kept trying.
**Lesson:** The sandbox environment cannot push to GitHub. Always use GitHub Desktop for push operations.

**General pattern:** The AI was too eager to act and not careful enough to verify. It rushed through fixes, made confident assertions about things it hadn't fully checked, and ignored the user's preferred workflow. Slow down, verify, then act.

---

## Troubleshooting Guide

### `/checkauth` shows "One or more services failed"
This means a real API call to Calendar or Tasks returned an error. Don't ignore it — even if features seem to work, they may be silently returning empty results.

**Steps:**
1. Run `/calendar` — does it return events? If not, Calendar API is broken.
2. Run `add todo test item` — does it confirm "✓ Added"? If it says "Sorry, I couldn't add that", Tasks API is broken.
3. If Calendar fails: run `/auth` to re-authorize.
4. If Tasks fails: check that **Google Tasks API** is enabled in Google Cloud Console (console.cloud.google.com → APIs & Services → Library → search "Tasks API"). If the button says "Enable", click it. Then run `/auth`.
5. If both fail: token may be fully expired. Run `/disconnect` then `/auth` for a clean re-authorization.

### Token keeps expiring / needing reauth
Access tokens expire every ~1 hour — this is normal. Alfred auto-refreshes them using the refresh token (proactive refresh at <5 min remaining). If you're seeing frequent auth failures, the refresh token itself may have been revoked (e.g., you changed your Google password, or revoked access in Google Account settings). Fix: run `/auth` again.

### Features return empty results but no error
The `adapters/google_tasks.py` module catches all API exceptions and returns empty lists (`[]`) or `None` instead of raising errors. This is by design for graceful UX, but it means a broken API looks like "no data" rather than an error. Always verify with `/checkauth` if results seem wrong.

### Railway deploy not picking up changes
Railway auto-deploys on push to `main`. If a push doesn't seem to take effect: wait 60-90 seconds (build + deploy), then send any command to Alfred. If still old behavior, check Railway dashboard for build errors.

### API-Sports features return nothing
If `/stats`, `/leaders`, or NL player queries return empty/no data:
1. Check Railway → Variables → confirm `API_SPORTS_KEY` exists and has value `4326891bc76a7ead7932910d21c771f6`
2. `API_SPORTS_KEY` is loaded at module import time (`os.environ.get`). If you add/change it, Railway must redeploy for it to take effect.
3. Check API-Sports daily quota: the free tier is 100 requests/day per sport. If exhausted, all calls return errors until midnight UTC.
4. The `is_available()` function in `api_sports.py` returns `bool(API_SPORTS_KEY)` — if the key is empty string, everything silently fails with no user-facing error.

### Git lock files blocking commits
If GitHub Desktop shows errors about lock files (HEAD.lock, index.lock, etc.):
1. Navigate to the `.git/` folder in Finder (you may need to show hidden files: Cmd+Shift+.)
2. Check if the lock files are 0 bytes — if so, they're stale from a failed operation and safe to delete
3. If they have content, a git process may be running — check Activity Monitor for git processes first
4. Delete the 0-byte lock files via Finder (select → Cmd+Delete)
5. Do NOT use the sandbox/AI terminal to delete these — it doesn't have proper git permissions

### Sandbox limitations
The AI coding sandbox (Claude/Cowork) has specific limitations:
- Cannot `git push` — always use GitHub Desktop for pushing
- Cannot interact with Chrome browser (read-only tier) — use Chrome MCP extension tools or do it manually
- Git operations in the sandbox can leave stale lock files — always clean up via Finder if commits fail
- The sandbox filesystem is separate from your Mac — file paths in the sandbox don't exist on your computer

---

## How Deployment Works

Every time code is pushed to the `main` branch on GitHub, Railway automatically detects it, rebuilds, and redeploys Alfred within ~60 seconds. No manual steps needed.

---

## Project File Structure

```
telegram-assistant/
├── bot.py                  # Main entry point, handlers, scheduler, plugin loader integration
├── core/
│   ├── config.py           # All settings and environment variables
│   ├── data.py             # JSON state management (_next_id bug fixed here)
│   ├── intent.py           # Two-layer intent classifier (keyword + GPT) + plugin hooks
│   ├── google_auth.py      # Google OAuth setup
│   └── plugin_loader.py    # ★ Auto-discovery plugin system (Session 5)
├── adapters/
│   ├── google_calendar.py  # Calendar read/write
│   └── google_tasks.py     # Tasks read/write
├── features/               # One file per feature (22 features)
│   └── todos.py            # entity key bug fixed here
├── plugins/                # ★ Auto-discovered plugin directory (Session 5)
│   ├── shared/             # ★ Shared modules used by multiple plugins
│   │   ├── __init__.py
│   │   └── player_search.py # Central player search + league resolution + GPT fuzzy matching
│   └── sports/             # ★ Sports Pack plugin (Session 5, expanded Sessions 9-10)
│       ├── __init__.py     # PLUGIN_META — auto-registered by plugin_loader
│       ├── config.py       # League definitions, ESPN API URLs, settings
│       ├── espn_api.py     # Async ESPN public API client (10 leagues), /scores defaults to yesterday
│       ├── api_sports.py   # ★ Async API-Sports client (1060+ lines) — player/team stats, search, seasons
│       ├── stats_api.py    # ★ Unified stats layer — ESPN-first → API-Sports fallback, multi-league soccer
│       ├── commands.py     # /scores, /standings, /schedule, /sports, /bets, /stats, /leaders
│       ├── dispatch.py     # Intent → command routing, stat category filtering, fuzzy name fallback
│       ├── gpt_nl.py       # ★ Phase 2: GPT function-calling dispatcher for NL sports queries
│       ├── briefing.py     # ★ Phase 3: Morning briefing section (scores + top performers + Reddit/YouTube)
│       ├── keywords.py     # Layer 1 fast regex rules for sports queries (includes NL catch-all)
│       ├── formatting.py   # Telegram HTML message formatters
│       ├── data.py         # Bet tracking, settings persistence
│       ├── jobs.py         # Game alerts, score update notifications
│       ├── callbacks.py    # Inline keyboard button handlers
│       ├── betting.py      # Screenshot analysis, line comparison, bet calculator
│       ├── charts.py       # matplotlib chart generation (P&L, ROI, win rate)
│       └── photo_handler.py # Sportsbook screenshot detection
├── railway.json            # Railway deployment config
├── Procfile                # Process definition
└── requirements.txt        # Python dependencies
```

---

## Quick Reference — Key Commands in Telegram

```
/start      — welcome message
/setup      — run onboarding wizard (do this first)
/auth       — connect Google account
/briefing   — morning digest
/ask        — AI chat with web search
/help       — full command list
```

---

*Last updated: April 6, 2026 (Session 14 — Phase 4A complete. Cross-platform adapter layer built. Discord bot entry point live. Phase 4B: migrate feature handlers to AlfredContext)*

---

## Session History (newest first)

**Session 14 — Phase 4A: Cross-Platform Architecture (April 6, 2026)**

Built the full platform abstraction layer so Alfred can run on Discord (or any future platform) with the same codebase.

*New files:*
- `core/alfred_context.py` — AlfredContext: platform-agnostic message/reply wrapper
- `core/html_utils.py` — html_to_discord() converts Telegram HTML → Discord Markdown
- `core/alfred_dispatch.py` — platform-agnostic dispatcher (replaces bot.py's _dispatch)
- `adapters/telegram_adapter.py` — builds AlfredContext from Telegram (update, context)
- `adapters/discord_adapter.py` — builds AlfredContext from Discord message (auto-splits 2000 chars)
- `discord_bot.py` — full Discord entry point: on_message → classify → alfred_dispatch; direct command routing for !scores, !standings, !schedule, !stats, !leaders, !ask, !help

*Modified files:*
- `bot.py` — added AlfredContext build + alfred_dispatch (2 lines; fully backward compatible)
- `requirements.txt` — added discord.py comment (uncomment to enable)
- `Procfile` — added comment for running Telegram + Discord as separate Railway services

*Architecture notes:*
- Discord bot is a SEPARATE platform alternative, not a plugin
- Unmigrated features on Discord return "coming soon" — migrate one by one in Phase 4B
- Migration pattern: change handler signature from `(intent, ents, update, context)` to `(intent, ents, ctx: AlfredContext)` and replace `update.message.reply_text(...)` with `await ctx.reply_html(...)`
- Telegram continues working 100% unchanged via ctx._update pass-through

**Session 13 — Phase 3: Sports Morning Briefing — fully complete (April 6, 2026)**

*Part 1 — Core briefing section:*
Built `plugins/sports/briefing.py` (~330 lines): async sports section hooked into daily `/briefing`. Fetches yesterday's scoreboard per favorite league, then concurrently hits ESPN box score API for every game. Top 3 performers ranked by PTS + REB×0.5 + AST×0.5. Favorite team games get ⭐. Optional Reddit highlights (Highlight-flair posts from league subreddits, default ON). Optional YouTube top plays — direct video via YouTube Data API v3 if `YOUTUBE_API_KEY` set, otherwise YouTube search URL at no cost (default OFF). Section silently skipped if no favorite teams/leagues configured.

Modified: `plugins/sports/config.py` (+4 briefing setting defaults), `features/briefing.py` (`_SECTION_BUILDERS["sports"]`), `core/data.py` (`"sports"` added to both default order lists), `features/setup.py` (`sports` in `_ALL_BRIEFING_SECTIONS` + cost-warning prompt text).

*Part 2 — Stat thresholds refinement:*
3PT display changed from "N made" to "X/Y 3PT" format. Threshold: ≥4 attempts + ≥35% efficiency + ≥2 made (filters small-sample noise). STL/BLK raised to ≥2. ESPN box score 3PT parsed as made/attempted from "5-12" style strings.

*Part 3 — Briefing Settings UI + player tracking:*
Added `📊 Briefing Settings` button to `/sports` menu showing current on/off state for all 3 settings. Full in-app toggle menu in `callbacks.py` — one tap flips reddit/youtube/player tracking; turning player tracking ON shows API quota cost warning popup. Added `/sports addplayer <name>` and `/sports removeplayer <name>` text commands. Tracked player stat lines appended to briefing by scanning box scores already in memory — zero extra API calls.

Modified: `commands.py` (menu status display + addplayer/removeplayer subcommands), `callbacks.py` (`sports_briefing_*` handlers + full menu), `briefing.py` (`all_players_seen` dict + tracked players section).

Build order confirmed: Phase 4 = Cross-platform adapters (Discord first) → Phase 5 = Betting plugin cross-platform from day 1.

**Session 12 — Remove Player Compare Feature (April 6, 2026)**
Removed the `/compare` player comparison feature entirely. Cross-sport API incompatibility (ESPN returns different stat shapes for NBA vs soccer) made it unreliable. Removed from 6 files: keywords.py (handler + 3 rules), gpt_nl.py (function schema + elif), dispatch.py (sports_compare + sports_compare_nl handlers), commands.py (cmd_compare function), `__init__.py` (command registration + intent list), formatting.py (format_player_comparison + _flatten_stats). Net: -405 lines.

**Session 11 — Phase 2: GPT Function-Calling NL Sports Queries (April 6, 2026)**
Built `plugins/sports/gpt_nl.py`: GPT function-calling dispatcher that receives any NL sports query, calls GPT-4o-mini with 7 function schemas (get_scores, get_standings, get_schedule, get_leaders, get_player_stats, get_player_gamelog, not_sports), maps result to IntentResult, and calls existing dispatch handlers. Added broad NL catch-all keyword rule in keywords.py so unmatched sports messages route to `sports_nl_query` → gpt_nl.py. Registered `sports_nl_query` intent in `__init__.py`. Full regression: all 8 NL query types passing (scores, standings, schedule, leaders, player stats, gamelog, NL stats query, NL scores query). Railway deployed and confirmed live.

**Session 10 — Phase B Bug Fixes, Audit Failures, Handoff (April 6, 2026)**
Continued from session 9. Fixed 7 bugs identified during testing, but the session was plagued by repeated AI mistakes (see "AI Failures & Lessons" below). The user lost confidence and requested a full handoff document.

**Bugs targeted (7 total):**
1. `/scores` showing today's empty schedule instead of yesterday's results — **FIXED, TESTED** (espn_api.py `yesterday=True` default)
2. "who leads the league in blocks" returning all stats instead of just blocks — **FIXED in code** (`_extract_stat_category()` + `_filter_leaders_category()` in dispatch.py), but NL routing bypasses it (see #7)
3. Standings out of order — **FIXED, TESTED** (espn_api.py sorts by wins descending)
4. `/compare` not working for soccer players — **FIXED in code** (multi-league fallback in stats_api.py + previous-season fallback in api_sports.py), root cause was missing API_SPORTS_KEY env var. Feature later removed entirely in session 12.
5. GPT fallback thinks it's 2023 — **FIXED, TESTED** (`{today}` injected into system prompts via config.py and features/ask.py)
6. Single-name player lookups and misspellings — **FIXED, TESTED** (GPT fuzzy resolution in player_search.py, confirmed "Mahommes" → "Patrick Mahomes")
7. NL queries not routing to commands — **PARTIALLY FIXED** (added `\bwho\s+leads\b` regex to keywords.py, but many other patterns still fall to GPT Layer 2 which often misclassifies)

**Code changes committed and deployed:**
- `plugins/sports/api_sports.py` — Dynamic season computation + previous-season fallback (`_prev_season()`, `seasons_to_try` loops in `search_player()` and `get_player_stats()`)
- `plugins/sports/keywords.py` — Added `\bwho\s+leads\b` regex pattern for leaders intent routing
- `plugins/sports/espn_api.py` — `/scores` defaults to yesterday, standings sorted by wins
- `plugins/sports/stats_api.py` — Multi-league soccer fallback
- `plugins/sports/commands.py` — `/stats` uses `search_with_fuzzy_fallback`
- `plugins/sports/dispatch.py` — `_extract_stat_category()`, `_filter_leaders_category()`, fuzzy fallback
- `plugins/shared/player_search.py` — `gpt_resolve_player_name()`, `search_with_fuzzy_fallback()`, expanded stop words
- `core/config.py` — `{today}` placeholder in MEMORY_SYSTEM_PREFIX
- `features/ask.py` — Injects today's date into GPT system prompts

**What still needs testing after this deploy:**
- "who leads the nba in blocks" (keyword regex now in place) — ✅ Resolved by Phase 2 GPT function-calling (session 11)
- Previous-season fallback for any sport where current season returns empty

**Session 9 — Phase A: API-Sports Client Build (April 5-6, 2026)**
Built the full `api_sports.py` client (1060+ lines): player search, player stats, team stats for NBA/NFL/MLB/NHL/Soccer across API-Sports endpoints. Created `stats_api.py` unified layer with ESPN-first → API-Sports fallback pattern. Created `plugins/shared/player_search.py` for centralized player/league resolution. Initially used hardcoded "2024" season which was wrong — replaced with dynamic `_current_season()` computation in session 10.

**Session 8 — Architecture Planning & All Decisions Finalized (April 5, 2026)**
Continued from session 7. Completed testing of team stats and gamelog (both working after fixes). Discovered fundamental limitations of ESPN scraping + keyword NL approach. Researched 5 sports data APIs: API-Sports, BALLDONTLIE, MySportsFeeds, SportsDataIO, TheSportsDB. **All architecture decisions finalized:**
- **API-Sports** selected as primary stats API (free 100 req/day, $19/mo paid)
- **ESPN kept** as free fallback for scores/standings/schedule (failover pattern: ESPN first → API-Sports)
- **The-Odds-API** for betting (separate plugin)
- **GPT function-calling** replaces keyword regex NL (uses existing OpenAI key)
- **Shared player search module** (`plugins/shared/`) for both plugins
- **Template model confirmed** — bot ships without API keys, each buyer sets up their own
- **Selling both** whole bot template + individual plugin add-ons
- 4-phase build plan documented (API-Sports → GPT NL → Betting plugin → Polish)
**Key lesson:** use Chrome MCP to inspect API response formats BEFORE coding parsers — saves hours vs. deploy-debug cycles.

**Session 7 — Stats Command Debugging & ESPN API Integration**
ESPN search API returns empty `team`, `sport`, `league` fields for many players — fixed with sport-based fallback logic. Discovered v2 athlete endpoints return non-200. Only working stats endpoint: `site.web.api.espn.com/apis/common/v3/sports/{sport}/{league}/athletes/{id}/stats`. v3 format: `{filters, teams, categories, glossary}` — NO `athlete` key. Categories use `statistics` (2D array) and `totals` (flat array), NOT `stats`. Fixed Python operator precedence bug with inline ternary. Added `player_name` parameter passthrough. Team stats fixed: `results.stats` is a dict with `categories`, not a flat list — parser was wrapping it wrong. Gamelog rewritten for v3 format (labels + events dict + seasonTypes join by eventId). Files: `stats_api.py`, `commands.py`, `dispatch.py`, `formatting.py`.

**Session 6 — Live Testing of Sports Pack**
Found and fixed 4 bugs: (1) NL dispatch crash — dispatch.py tried to set read-only `update.message.text` in PTB v22. (2) Standings empty — ESPN uses `children[]→standings.entries[]` format. (3) Scores raw status codes. (4) Schedule empty — naive vs aware datetime comparison. All 5 commands tested and passing.

**Session 5 — Plugin Architecture + Sports Pack Build**
NL audit (13→22 keyword intents). Built plugin loader (auto-discovery via PLUGIN_META). Built Sports Pack: 4,000+ lines, 13 files, 10 leagues, ESPN API. Built betting module: screenshot analysis (GPT-4o Vision), bet calculator, tracker, charts.

**Sessions 1-4 — Core Bot Build**
Fixed /briefing crash, "add todo" NL, /mood state drop, /checkauth display, Google Tasks API 403. Full 20-command test: 18/20 passing → all fixed.

---

## ESPN API Reference (for existing code)

These are the ESPN endpoints currently in use. Documented here because they're undocumented publicly and were discovered through trial and error:

| Endpoint | Works For | Does NOT Work For |
|---|---|---|
| `site.api.espn.com/apis/site/v2/sports/{sport}/{league}/teams/{id}/statistics` | Team stats (full categories) | — |
| `site.api.espn.com/apis/site/v2/sports/{sport}/{league}/teams/{id}` | Team info (record, roster) | Detailed stats |
| `site.web.api.espn.com/apis/common/v3/sports/{sport}/{league}/athletes/{id}/stats` | Player stats (averages, totals) | Team stats |
| `site.web.api.espn.com/apis/common/v3/sports/{sport}/{league}/athletes/{id}/gamelog` | Player game log | — |
| `site.api.espn.com/apis/common/v3/search?query={name}&type=player` | Player search | — |
| `site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard` | Live scores | — |
| `site.api.espn.com/apis/site/v2/sports/{sport}/{league}/standings` | Standings | — |
| `site.api.espn.com/apis/site/v2/sports/{sport}/{league}/teams/{id}/schedule` | Team schedule | — |

**Key gotchas:**
- v3 athlete endpoints do NOT include athlete name — must get from search results
- v3 does NOT work for team stats (returns empty) — use v2 only
- v2 does NOT work for individual athlete stats/gamelog — use v3 only
- `results.stats` in v2 team stats is a dict `{id, name, abbreviation, categories: [...]}`, NOT a list
- Gamelog v3 splits data: `seasonTypes[].categories[].events[]` has stats, `events{}` dict has game info, joined by eventId

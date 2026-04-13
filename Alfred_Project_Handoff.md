# Alfred — Project Handoff (Session Log)
*Quick-read status doc. Updated every session. For full vision and roadmap, see Alfred_Master_Plan.md.*
*Last updated: April 12, 2026*

---

## Current Status: ✅ LIVE

- Telegram bot: @wasonassistant — fully live
- Discord bot: live, running as parallel Railway process
- Railway project: `alluring-learning` → service `worker`
- GitHub: `wasonaiemail-dev/telegram-assistant`

---

## What's Next (Priority Order)

### 🏗️ Active Track — Quick Wins (Customizability, in progress)
*Low-lift buyer-facing improvements. Knocking these out before returning to core build priorities.*

- ✅ **CW1 — Scheduled times in setup wizard** — done, live
- ✅ **CW2 — Briefing on/off toggle** — done, live
- ✅ **CW3 — Journal toggle + prompt customization in setup wizard** — done, live
- ✅ **CW4 — Sports recap: favorite teams setup step + on/off toggle** — done, live
- ✅ **CW6 — Reply Assist signature** — done, live
- ✅ **CW7 — Shopping: default list + 50 pre-populated common items** — done, live
- ✅ **CW8 — Todo: list naming + due-date display preference** — done, live
- ✅ **HP1 — Recurring Reminders** — done, live ("remind me every Monday at 9am")
- ✅ **HP2 — Snooze Duration Setting** — done, live (configurable in setup)
- ✅ **HP3 — Weekly Summary Section Toggles** — done, live
- ✅ **CW5 — Event Prep toggle** — done, push pending via GitHub Desktop

### 🔴 Immediate Blocker
- **Reddit OAuth setup** — Top Plays code is deployed but returns empty because Railway's IP is hard-blocked (HTTP 403). Need Tyler to: create Reddit app at `reddit.com/prefs/apps` (type: script), then add `REDDIT_CLIENT_ID` + `REDDIT_CLIENT_SECRET` to Railway. No code changes needed — already built. Run `!topplaysdebug` after deploy to confirm.

### 🔴 Core Build Priorities (after quick wins)
1. ✅ **Google Tasks Two-Way Sync** — done April 12. `/synctasks` command + `auto_sync_tasks` job at 7:05am. Inherently two-way since Alfred writes directly to Google Tasks.
2. **Reddit OAuth Setup** — see Immediate Blocker above. One-time config, no code needed.
3. ✅ **Discord Phase 4C** — done April 12. Discord now at full feature parity.
4. ✅ **Expense Tracking** — done April 12. `features/expenses.py`. NL bypass, `/expenses`, briefing section (yesterday's spending), weekly summary integration.
5. ✅ **Sleep Tracking** — done April 12. `features/sleep.py`. NL bypass, `/sleep [hrs]`, weekly summary integration.

---

## Session Log

### Sessions 1–4 (March 2026)
- Fixed reminders type error (UUID IDs crashing `_next_id()`)
- Fixed `/briefing` crash (UUID reminder IDs in `core/data.py`)
- Fixed `add todo` natural language (entity key mismatch + regex too narrow)
- Fixed `/mood` conversation state drop (added awaiting flag in `bot.py`)
- Fixed `/checkauth` false-positive warning (access token refresh timing)
- Fixed Google Tasks API 403 (was not enabled in Google Cloud Console)
- Full 20-command test: 18/20 passing, 2 bugs found and fixed same session

### Session 5 (April 4, 2026)
- NL audit: analyzed 74 intents, added 9 new keyword patterns, Layer 1 coverage 13→22 intents
- Built plugin loader architecture (`core/plugin_loader.py`) — auto-discovery, zero core changes needed to add plugins
- Built Sports Pack plugin — 4,000+ lines, 13 files, 10 leagues (NFL, NBA, MLB, NHL, NCAAF, NCAAB, EPL, MLS, Bundesliga, La Liga)
- Commands: `/scores`, `/standings`, `/schedule`, `/sports`, `/bets`
- Built Sports Betting module — GPT-4o Vision sportsbook screenshot analysis, bet tracker, P&L charts

### Sessions 6–8 (April 2026)
- **Phase 2 (GPT NL):** Built `plugins/sports/gpt_nl.py` — GPT function-calling engine. NL sports queries now work ("who leads the nba in blocks", "how did the Celtics do")
- **Removed `/compare`:** Player comparison feature removed — ESPN API returns incompatible stat shapes across sports. Decided it was a gimmick.
- **Phase 3A:** Built `plugins/sports/briefing.py` — morning sports briefing with yesterday's results, top 3 performers per game (composite score), favorite team ⭐ highlighting
- **Phase 3B:** Built Briefing Settings UI — toggle Reddit/YouTube/player tracking, addplayer/removeplayer commands
- **Phase 3C:** Built Reddit Top Plays pipeline — `_build_top_plays()`, `_fetch_reddit_top_plays_sub()`. Fetches Highlight-flair clips from league subreddits + r/sports catch-all. Deduplicates, sorts YouTube-first for Discord embed.
- **Phase 4A:** Built platform abstraction — `core/alfred_context.py`, `core/html_utils.py`, `core/alfred_dispatch.py`, `adapters/discord_adapter.py`, `adapters/telegram_adapter.py`, `discord_bot.py`
- **Phase 4B:** Migrated features to AlfredContext: ask, todos, reminders, notes, shopping, calendar, habits, gifts, contacts, mood, links, export_data
- Fixed `tzdata` missing from requirements.txt (Railway timezone crash)
- Fixed shopping classifier routing bug ("add milk to shopping list" was showing list instead of adding)
- Fixed HTML escaping throughout sports briefing (raw tags showing in Telegram)
- Fixed `_send_long` fallback (was showing raw `<b>tags</b>` instead of stripping)
- Fixed `discord_bot.py` `!briefing` — was a stub showing "coming soon", now calls `send_briefing_ctx(ctx)` directly
- Fixed git lock files — created `fix_git_locks.command` script for GitHub Desktop
- Fixed YouTube hardcoded off: `youtube_enabled = False` in `plugins/sports/briefing.py`
- Fixed `briefing_top_plays` settings key (was using old `briefing_reddit_highlights` key)
- **Known open bug:** Reddit Top Plays flair filter misses r/baseball and r/hockey — fix is widening filter to also match "video"

### Session 9 (April 8, 2026)
- Full folder audit: found 3 copies of Alfred codebase (AI/telegram-assistant = live, Projects/alfred = old snapshot, iCloud folder = old snapshot)
- Read all historical docs: wasonassistant_handoff.pdf, alfred_rebuild_plan.docx v1+v2, bot-9.py, test results
- Recovered missing feature context: expense tracking, sleep tracking, brain dump, undo, note aging, photo pipeline, Alfred persona/context injection, proactive layer
- Created `alfred_feature_backlog.md` — full recovered context from all historical documents
- Created `Alfred_Master_Plan.md` — comprehensive vision, architecture, roadmap, product plan
- Restructured docs: Handoff = session log (this file), Master Plan = full vision, Feature Backlog = detailed backlog
- Saved open questions to auto-memory (8 unresolved decisions)
- Full feature-by-feature customizability audit — 22 features reviewed, decisions documented in Master Plan Section 9B
- Reviewed plugin architecture for sale-readiness — confirmed solid, added plugin dev standards + 3 pre-sale fixes to backlog
- Added plugin upsell notification feature to backlog (BA13)
- **Built + deployed CW1:** Briefing time, habit nudge time, travel weather time now configurable in `/setup` (no Railway env var change needed). `get_schedule_settings()` in `core/data.py`. `reschedule_job()` helper in `bot.py`. Jobs reschedule live without restart.
- **Built + deployed CW2:** Briefing on/off toggle in `/setup`. Buyer can disable scheduled briefing; manual `/briefing` still works. Guard added to `_job_briefing` so toggle takes effect immediately.

### Session 10 (April 11, 2026)
- Fixed Discord/Telegram platform language in Master Plan — neither is primary/secondary, both are equal buyer options
- Added setup wizard update rule to Master Plan Section 4 (always update `/setup` when adding configurable features)
- Full feature-by-feature customizability audit — 22 features reviewed, all decisions documented in Master Plan Section 9B
- Reviewed plugin architecture for sale-readiness — architecture is solid, identified 3 pre-sale fixes needed
- Added Plugin Development Standards to Master Plan Section 2 (6 rules every plugin must follow)
- Added pre-sale fixes to feature backlog: season auto-detection, README standardization, `api_keys_required` + `purchase_url` in PLUGIN_META
- Added BA13 (plugin upsell notification) to feature backlog
- **Built + deployed CW3:** Journal on/off toggle + prompt customization in `/setup`. Toggle blocks both reminders and `/journal` command when disabled (with helpful message). Prompt customization exposes `prompts_by_day` through setup wizard — up to 5 custom questions, applied every day. Guards in `_job_journal_reminder`, `_job_journal_followup`, `send_journal_reminder`, and `cmd_journal`.
- **Built + deployed CW4:** Base sports recap in `/setup` — buyer types favorite teams per league (NFL/NBA/MLB/NHL). `get_base_sports_settings()` in `core/data.py`. `_build_base_sports_recap()` in `features/briefing.py` fetches ESPN scoreboard for yesterday per team. `_section_sports` now splits `ImportError` (plugin not installed → use base recap) from other exceptions (plugin crashed → return ""). Sports Pack plugin still overrides base recap when installed.

### Session 11 (April 11, 2026) — Top Plays Pipeline Rebuild + Reddit OAuth
- **Root cause diagnosed:** Reddit Top Plays never worked on Railway because Railway's cloud IP is hard-blocked by Reddit's Cloudflare (HTTP 403 on every subreddit, confirmed via `!topplaysdebug`). Anonymous `www.reddit.com` and `old.reddit.com` both return 403.
- **Full pipeline rebuild** in `plugins/sports/briefing.py`:
  - Removed flair filtering entirely — proven unreliable (`flair=None` on most posts, including r/nba video posts). Replaced with domain filtering (`v.redd.it`, `streamable.com`, `youtube.com`, `youtu.be`, `clips.twitch.tv`)
  - Added title-based scoring (`_score_title`) — play words → 1.5× boost, controversy words → 0.25× penalty, noise words (interviews, press conferences, ceremonies, compilations) → 0.0 (dropped entirely)
  - Added `SUBREDDIT_MIN_SCORE` — per-subreddit upvote floors (r/nba: 2000, r/nfl: 1500, r/baseball + r/hockey: 500, r/MLS: 150, etc.) to balance community size vs. noise
  - Added v.redd.it → vxreddit.com URL conversion for Discord inline video embedding
  - Added 72-hour fallback (`t=week`) when fewer than 5 clips pass daily filters (covers All-Star breaks, bye weeks)
  - Added `r/soccer` and `r/Champions_League` to `LEAGUE_SUBREDDITS`
  - Increased timeout 10s → 20s, added `ssl=False`, upgraded to browser-style User-Agent headers
- **Reddit OAuth built** — `_get_reddit_oauth_token()` in `briefing.py`. Module-level token cache, refreshes every ~1 hour. Requests route through `oauth.reddit.com` which bypasses the cloud IP block. Falls back to `www.reddit.com` → `old.reddit.com` if OAuth not configured.
  - Reads `REDDIT_CLIENT_ID` + `REDDIT_CLIENT_SECRET` env vars (not yet set in Railway — Tyler action required)
- **`!topplays` command** added to `discord_bot.py` — fetches top 10 clips for user's configured leagues, posts with vxreddit URLs
- **`!topplaysdebug` command** added — shows OAuth token status + HTTP status + per-filter clip counts per subreddit. Used to confirm Railway IP block diagnosis.
- **⚠️ Pending:** Tyler needs to create Reddit app + add env vars to Railway before `!topplays` works. See Immediate Blocker above.

### Session 12 (April 12, 2026) — CW5 + Google Tasks Sync
- **Built CW5:** Event Prep on/off toggle. `get_event_prep_settings()` and setup wizard step were already implemented in `core/data.py` and `features/setup.py`. Only missing piece was the runtime guard in `bot.py`'s `_job_event_prep`. Three-line addition: load data, check `enabled` flag, return early if disabled. Push pending via GitHub Desktop.
- **Architecture note confirmed:** Rebuilt Alfred stores everything directly in Google Tasks (primary data store). Two-way sync is inherently there — every Alfred write goes to Google Tasks immediately, every Alfred read comes from Google Tasks live. No traditional sync process needed.
- **Built Google Tasks Sync — `features/sync_tasks.py`:**
  - `/synctasks` command — reads all Alfred Google Tasks lists and returns a consolidated summary: todos (total, overdue, high-priority), each shopping list (count + first 5 items), gift ideas count. Useful after adding items on phone to confirm Alfred sees them.
  - `auto_sync_tasks()` scheduled job — fires 5 minutes after the morning briefing (floats with briefing time, so always 5 min after even if Tyler changes his briefing time in `/setup`). Sends the same list summary automatically each morning.
  - `_job_auto_sync_tasks` wrapper added to `bot.py`. Scheduled in `_schedule_jobs` using `_briefing_h` and `_briefing_m + 5` (with hour rollover). `/synctasks` command handler added and registered.

### Session 13 (April 12, 2026) — Expense Tracking + Sleep Tracking

- **Built Expense Tracking — `features/expenses.py`:**
  - `EXPENSE_ADD`, `EXPENSE_VIEW`, `EXPENSE_DELETE` intents added to `core/intent.py`
  - Layer 1 keyword bypass: `"$45 groceries"`, `"spent $12 on coffee"`, `"show my expenses"` all caught without GPT
  - Categories: groceries, dining, transport, health, entertainment, shopping, household, subscriptions, other
  - `/expenses [today|week|month]` — Telegram command with period arg
  - `!expenses [today|week]` — Discord command
  - NL intent dispatch: `handle_expense_intent()` in `alfred_dispatch.py`
  - Storage: `userdata.json["expenses"]` list of `{id, amount, category, note, date}`
  - Briefing integration: `_section_expenses()` shows yesterday's spending in morning briefing (appears when data exists)
  - Weekly summary: `get_expense_weekly_section()` — passed to GPT as context AND appended as HTML block

- **Built Sleep Tracking — `features/sleep.py`:**
  - `SLEEP_LOG`, `SLEEP_VIEW` intents added to `core/intent.py`
  - Layer 1 keyword bypass: `"slept 7 hours"`, `"got 6.5 hours of sleep"`, `"show my sleep"` all caught
  - `/sleep` — view 7-day history. `/sleep 7.5` — log hours. `/sleep 7.5 3` — log hours + quality (1–5)
  - `!sleep [hrs]` — Discord command
  - NL intent dispatch: `handle_sleep_intent()` in `alfred_dispatch.py`
  - Storage: `userdata.json["sleep_log"]` (already existed with `{hours, quality, date, note}` schema)
  - Visual progress bar: `████████░░` showing hours vs 8-hr target
  - Overwrites same-day entry if re-logged
  - Weekly summary: `get_sleep_weekly_section()` — avg, low, high, nights logged; passed to GPT + appended as HTML block

- **`core/alfred_dispatch.py`** updated — `EXPENSE_*` and `SLEEP_*` intents added to imports, dispatch blocks, and `_build_core_intents()` set
- **`core/data.py`** updated — `"expenses": []` added to `load_data()` migration defaults and `_empty_data()`
- **Discord `!help`** updated — expenses and sleep listed under Health & Fitness

### Session 12 (cont.) — Discord Phase 4C Complete
- **Diagnosed Phase 4C gap:** All feature files (meals, workout, journal, reply_assist, summary) already use `ctx: AlfredContext` pattern with zero Telegram-specific code. NL dispatch in `alfred_dispatch.py` already routed all these intents on Discord. The ONLY missing piece was the `!command` fast-path routing in `discord_bot.py`.
- **Added to `_handle_discord_command`:** `!meals`, `!workout`, `!journal`, `!reply [message]`, `!weekly` (also `!weeklysummary`, `!summary`), `!synctasks` — all with proper error handling.
- **Rewrote `!help`** to list all commands in categorized sections: Sports, Daily Assistant, Health & Fitness, Lists & Tasks, Settings, Natural Language. Removed stale "coming soon" lines.
- **Updated `alfred_dispatch.py`** comment checkboxes from `[ ]` to `[x]` for all features — they were already dispatching correctly, just needed a doc update.
- **Discord is now at full feature parity with Telegram.** Every command and NL intent works on both platforms.

---

## File Structure (Reference Docs — Projects/alfred/)

| File | Purpose |
|---|---|
| `Alfred_Project_Handoff.md` | This file — session log, current status, what's next |
| `Alfred_Master_Plan.md` | Full vision, architecture, roadmap, product plan, build order |
| `alfred_feature_backlog.md` | All missing features with full context, recovered from historical docs |
| `CLAUDE.md` | Claude behavior rules for this project |
| `setup/SETUP_COMPANION.md` | Buyer installer document (needs update for Sessions 5+) |

---

## Key Technical Notes (Quick Reference)

- **Git:** GitHub Desktop only. No bash git commands. Never amend — always new commits.
- **Deploy:** Push to main → Railway auto-deploys in ~60 seconds
- **Settings:** Sports plugin settings live in Railway `/data/sports_plugin/settings.json`
- **Schedule settings:** `get_schedule_settings(data)` in `core/data.py` — reads from `userdata.json["settings"]["schedule"]`, falls back to env vars. Keys: `briefing_enabled`, `briefing_hour/minute`, `habit_nudge_hour/minute`, `travel_weather_hour/minute`
- **Rescheduling jobs live:** `reschedule_job(job_queue, name, handler, hour, minute)` in `bot.py` — cancels existing named job and re-adds at new time. No Railway restart needed.
- **Calendar auth health check:** ✅ Live — `job_google_health_check` in `bot.py`, scheduled 10 min before briefing time automatically. No 6:50am hardcode — it floats with the briefing time setting.
- **Context injection:** ⚠️ Partial — `ask.py` injects memory facts by keyword relevance ✅. But todos/mood/habits/reminders/calendar are NOT injected into every GPT response ❌. Alfred doesn't know "you have 3 high-priority todos" when chatting. This is the missing piece of the proactive vision.
- **Reddit Top Plays:** Uses `briefing_top_plays` key (default True). YouTube hardcoded off. Requires `REDDIT_CLIENT_ID` + `REDDIT_CLIENT_SECRET` Railway env vars — Railway cloud IP is hard-blocked (HTTP 403) on anonymous Reddit requests. OAuth routes through `oauth.reddit.com` which is not blocked.
- **Top Plays filtering:** Domain-based (not flair). `VIDEO_DOMAINS` = v.redd.it, streamable.com, youtube.com, youtu.be, clips.twitch.tv. Title scoring via `_score_title()` — play words 1.5×, controversy 0.25×, noise words drop to 0. Per-sub score floors in `SUBREDDIT_MIN_SCORE`. 72hr fallback if < 5 daily clips.
- **vxreddit:** v.redd.it posts are converted to `vxreddit.com{permalink}` for Discord inline embedding. Reddit's native v.redd.it uses DASH streaming (separate audio/video streams) that Discord can't play inline.
- **`!topplaysdebug`:** Diagnostic command — shows OAuth status + HTTP code + filter stage counts per subreddit from Railway. Run this first if top plays returns empty.
- **Platform detection:** `getattr(ctx, "platform", "telegram")` — "telegram" or "discord"
- **HTML escaping:** Always `_html_escape.escape()` on dynamic content in HTML strings
- **Procfile:** `worker: sh start.sh` — runs both Telegram and Discord bots simultaneously
- **Plugin standards:** Own `/data/[plugin]/` dir, core imports only, `PLUGIN_META` with `api_keys_required` + `purchase_url`, single README, no hardcoded years — see Master Plan Section 2

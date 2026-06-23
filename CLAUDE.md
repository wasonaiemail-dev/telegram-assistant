# Marvin — Claude Reference Rules
*For Claude to reference when working on the Marvin Telegram bot project.*
*Last updated: April 20, 2026*

---

## ⚠️ END OF SESSION CHECKLIST

**Tyler will say this to trigger the update pass:**

> "Do a full end-of-session doc update. Check and update ALL of these: Marvin_Master_Plan.md, Marvin_Project_Handoff.md (add a session log entry), marvin_feature_backlog.md, the auto-memory pickup file, SETUP_COMPANION.md (if buyer-facing changes), and README.md (if new features). Tell me what you updated in each one and what you skipped and why."

**Every session that ships code MUST update all of the following. No exceptions.**

| File | What to update |
|---|---|
| `Marvin_Master_Plan.md` | Header date, Section 7 env vars, Section 8 features table, Section 11 pre-launch checklist |
| `Marvin_Project_Handoff.md` | Header date, "What's Next" section, new Session Log entry, file reference table if versions changed |
| `marvin_feature_backlog.md` | Mark completed items ✅ Done [date], update packaging/product steps |
| `auto-memory pickup file` | What shipped, what broke, what was fixed, what's next, Tyler action items, update MEMORY.md index pointer |
| `SETUP_COMPANION.md` | New setup steps, new env vars in FINAL OUTPUT, new appendix commands, bump version footer |
| `README.md` | Feature table row for any new features |

**Rule:** If a feature shipped, it appears in all 6. Not 4 of 6. All 6.

---

## Who Tyler Is

Tyler is **non-technical** — he does not write code. Claude writes all the code. When making any change:
- Lead with a plain-English explanation of what broke and why before showing code
- Don't use technical jargon without defining it
- Tyler uses **GitHub Desktop** (GUI) to push changes — not the terminal
- **Railway auto-deploys** within ~60 seconds of a push to `main` — no manual deploy steps needed
- Tyler tests everything by talking to the bot in Telegram directly

---

## Project Overview

Marvin is a Python Telegram bot with two purposes:
1. Tyler's personal daily assistant (calendar, tasks, reminders, habits, etc.)
2. A sellable $1 template product that anyone can deploy

**Keep features generalized** — no hardcoded personal data before packaging for sale.

| Thing | Location |
|---|---|
| Code | GitHub → `wasonaiemail-dev/telegram-assistant` |
| Hosting | Railway → project `alluring-learning` → service `worker` |
| Bot | Telegram → @wasonassistant |
| Persistent data | Railway `/data` volume |

---

## File Structure Rules

```
bot.py              — Main entry point. All command/handler registration lives here.
core/
  config.py         — ALL settings and env vars. If it's configurable, it goes here.
  data.py           — ALL JSON read/write. Use load_data() / save_data() everywhere.
  intent.py         — Two-layer intent classifier (Layer 1: regex, Layer 2: GPT)
  google_auth.py    — Google OAuth. Don't touch auth logic in feature files.
  plugin_loader.py  — Auto-discovers plugins/ directory on startup
features/           — One file per feature. Keep features self-contained.
adapters/           — Google API wrappers only. No business logic here.
plugins/            — Self-contained add-on packs (each has __init__.py with PLUGIN_META)
```

**Rule:** Never put settings or config values directly in feature files. They go in `core/config.py` and get imported.

---

## Bug Patterns to Avoid

These are bugs that have already crashed Marvin. Don't repeat them.

---

### 1. Type Casting IDs — Always Use a Fallback

**What went wrong:** Old reminder records had UUID string IDs like `"07b2f52d"`. Code called `int(id)` on them, which crashed.

**The rule:** Never assume an ID from `userdata.json` is a clean integer. Always guard it:

```python
# BAD — crashes on UUID/string IDs
max(int(r.get("id")) for r in reminders)

# GOOD — wraps in try/except, silently skips bad IDs
max((int(r.get("id")) for r in reminders if str(r.get("id", "")).isdigit()), default=0)

# Also fine — the simple version in reminders.py
max(int(r.get("id") or 0) for r in reminders)  # only if IDs are already clean
```

**Also applies to:** Any field that comes from stored JSON (due dates, ratings, numbers) — always cast defensively and catch exceptions.

---

### 2. Entity Key Mismatches — Always Use Fallback Keys

**What went wrong:** The intent classifier outputs `"text"` as the entity key. The `todos.py` handler was reading `"task"`. Task was always empty, so it would ask "What should I add?" even when the user had clearly said what they wanted.

**The rule:** When reading entities from the intent classifier, always chain fallback keys:

```python
# BAD — breaks if classifier uses "text" instead of "task"
task_text = entities.get("task", "").strip()

# GOOD — handles both key names
task_text = (entities.get("task") or entities.get("text") or "").strip()
```

**When adding a new feature:** Check `core/intent.py` to see exactly what entity keys the classifier outputs for that intent. Match them precisely, and always add a fallback.

---

### 3. Conversation State — Check Awaiting Flags Before the Intent Classifier

**What went wrong:** After `/mood` asked "How are you feeling? (1–10)", sending a bare number like `7` was intercepted by the general intent classifier, which had no idea what to do with it.

**The rule:** When a feature prompts the user for a follow-up response, it must set an "awaiting" state flag. `bot.py` must check that flag *before* routing to the intent classifier.

**Pattern to follow** (already implemented in `features/mood.py`):
1. Feature sets `_awaiting_rating = True` in `userdata.json["settings"]`
2. `bot.py` calls `is_mood_awaiting()` at the top of the message handler
3. If True, route directly to `handle_mood_text_reply()` — skip the classifier
4. The handler clears the flag when it processes the reply

**Apply this pattern any time a feature needs a free-text follow-up reply.**

---

### 4. Silent Google API Failures — "No Data" Doesn't Mean It Worked

**What went wrong:** The Google Tasks API was returning 403 errors (not enabled in Cloud Console), but `adapters/google_tasks.py` catches all exceptions and returns `[]`. Features looked like they were working — they just always showed "Nothing here."

**The rule:** When Google-backed features return empty results unexpectedly, **don't assume the code is wrong**. Run `/checkauth` first.

- `/checkauth` makes real API calls and reports ✅ or ❌ per service
- If Tasks shows ❌, check Google Cloud Console → APIs & Services → Library → "Tasks API" — make sure it's enabled
- If Calendar shows ❌, run `/auth` to re-authorize

**Key insight:** The adapters are designed to fail gracefully (return `[]` or `None` instead of crashing). This is intentional for UX. It means broken APIs look like empty data, not errors. Always verify with `/checkauth` before debugging code.

---

### 5. Due Date Type Inconsistency — Always str() Before Slicing

**What went wrong:** Some old reminder records stored `due` as an integer (Unix timestamp). Code called `due[:10]` to slice the date string, which crashed on an integer.

**The rule:** Before doing any string operation on a date field from JSON (slicing, checking for "T", etc.), always cast it to a string first:

```python
# BAD — crashes if due is stored as int
date_part = reminder["due"][:10]

# GOOD — safe regardless of storage type
date_part = str(reminder.get("due") or "")[:10]
```

---

### 6. Intent Regex Patterns — Always Test Multiple Phrasings

**What went wrong:** The keyword rule for adding todos only matched `"add X to my todo list"`, not the bot's own suggested format `"add todo X"`. Users following Marvin's own suggestions got the GPT fallback (slower and less reliable).

**The rule:** When writing a keyword regex for an intent, always think of at least 3 natural ways someone would say it and make sure they all match:

```python
# BAD — too narrow
r'^add\s+(.+?)\s+to\s+my\s+todo\s+list$'

# GOOD — covers multiple natural phrasings
r'^(?:add\s+(?:todo|task)\s+(.+)|add\s+(.+?)\s+to\s+(?:my\s+)?(?:todo|task)s?(?:\s+list)?)$'
```

**Test phrases to try before shipping:** "add todo X", "add task X", "add X to my todo list", "add X to tasks"

---

### 7. Google Auth — Access Tokens vs. Refresh Tokens

**What went wrong:** `/checkauth` was showing "One or more services failed" when the access token had under 2 hours remaining. That's normal — access tokens expire every hour and auto-refresh.

**The rule:** These are two different things:
- **Access token** — expires every ~1 hour. Auto-refreshes itself. Normal. Don't alarm Tyler about this.
- **Refresh token** — lasts ~7 days. If this expires, `/auth` must be run again.

The current `get_creds()` in `google_auth.py` proactively refreshes at <5 minutes remaining. This is correct behavior. Don't change that logic.

---

## Coding Conventions

### Data Storage
- **All JSON data** goes through `core/data.py` — use `load_data()` and `save_data()`
- **Main store:** `userdata.json` — reminders, habits, mood, meals, workouts, etc.
- **Separate files:** `marvin_memory.json`, `ask_history.json`, `contacts.json`, `conversation.json`
- When adding a new data key, add a `.setdefault()` line in the migration block of `load_data()` so existing users' files upgrade safely

### Telegram Handlers
- All command handlers are `async def` and take `(update, context)` parameters
- Reply with `update.message.reply_text("...", parse_mode="Markdown")` or `parse_mode="HTML"`
- **Note:** The codebase uses both Markdown and HTML — check what the surrounding code uses and be consistent within a file
- Guard all handlers against non-allowed users: `if update.effective_user.id != ALLOWED_USER_ID: return`

### Google API Calls
- Always go through the adapter (`adapters/google_tasks.py`, `adapters/google_calendar.py`)
- Never call `googleapiclient` directly from feature files
- Adapters return `None` or `[]` on failure — callers should check the return value

### Adding a New Feature
1. Create `features/your_feature.py` with its own command handler and intent handler
2. Add intent constants to `core/intent.py`
3. Add keyword regex rules to Layer 1 in `core/intent.py`
4. Add GPT examples to Layer 2 system prompt in `core/intent.py`
5. Register the command and intent handler in `bot.py`
6. Add any new data keys to the migration block in `core/data.py`

### Adding a New Plugin
1. Create `plugins/your_plugin/` directory
2. Add `__init__.py` with `PLUGIN_META` dict (name, version, commands, intents, jobs, callbacks, keyword_rules)
3. The plugin loader auto-discovers and registers everything — no changes to core code needed

---

## Deployment Checklist (Before Pushing)

- [ ] Tested the command in Telegram directly
- [ ] Ran `/checkauth` to confirm Google APIs are healthy
- [ ] No hardcoded personal data (names, locations, IDs) if this goes into the template
- [ ] New data keys have a `.setdefault()` migration line in `core/data.py`
- [ ] New intents have both a keyword rule (Layer 1) AND a GPT example (Layer 2) in `core/intent.py`

---

## Quick Troubleshooting

| Symptom | First thing to check |
|---|---|
| Feature returns empty but no error | Run `/checkauth` — API may be failing silently |
| Natural language command not recognized | Check Layer 1 keyword rules in `core/intent.py` |
| Feature asks for info the user already gave | Entity key mismatch — check what key the classifier actually outputs |
| Crash with "invalid literal for int()" | ID or date field being cast without a fallback |
| Follow-up reply goes to wrong handler | Missing awaiting-state flag in `bot.py` routing |
| Railway not picking up changes | Wait 60–90 seconds; check Railway dashboard for build errors |

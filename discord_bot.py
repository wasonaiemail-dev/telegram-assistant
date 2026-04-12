"""
alfred/discord_bot.py
======================
Discord entry point for Alfred.

Alfred on Discord is a SEPARATE ALTERNATIVE to the Telegram bot — not a
plugin. The buyer chooses one platform (or both). All the same core features
and plugins are available on both.

HOW IT WORKS
------------
1. A Discord bot token is configured (DISCORD_TOKEN env var).
2. Alfred listens for messages in any channel/DM it can see.
3. Messages starting with "!" (or "/" — configurable) are treated as commands.
4. All other messages go through the same intent classifier as Telegram.
5. Responses are sent back to the same channel.

COMMANDS (same as Telegram, use "!" prefix on Discord)
-------------------------------------------------------
  !briefing   — morning briefing
  !scores     — sports scores (Sports Pack)
  !standings  — sports standings
  !schedule   — upcoming games
  !stats      — player/team stats
  !leaders    — league leaders
  !todos      — todo list
  !notes      — notes
  !reminders  — reminders
  !ask        — AI chat
  !help       — command list
  (and all other Alfred commands)

NATURAL LANGUAGE
----------------
Any message in a channel Alfred monitors (no prefix needed) is classified
by the intent engine — same as Telegram. "What are the NBA scores?" works.

SETUP FOR BUYERS
-----------------
1. Create a Discord Application at https://discord.com/developers/applications
2. Create a Bot user and copy the token
3. Add DISCORD_TOKEN to Railway environment variables
4. Enable "Message Content Intent" in the Bot settings (Discord Developer Portal)
5. Invite the bot to your server using OAuth2 URL with "bot" scope + "Send Messages" permission
6. Run discord_bot.py as the startup process (or alongside bot.py — they're independent)

RUNNING BOTH TELEGRAM AND DISCORD
-----------------------------------
Telegram and Discord run as separate processes. In Railway, add a second
service that runs `python discord_bot.py` with the same environment variables.
Both bots share the same data storage (/data volume) so notes, todos, etc.
are synchronized between platforms.

Procfile example for running both:
    telegram: python bot.py
    discord:  python discord_bot.py

PLATFORM DIFFERENCES
--------------------
- Discord does not support Telegram's InlineKeyboardMarkup.
  Menus are rendered as numbered text options (Phase 4 MVP).
  Full Discord button (discord.ui.View) support is planned for Phase 6.
- Discord messages have a 2000-character limit (auto-split by adapter).
- HTML formatting is converted to Discord Markdown automatically.
- Voice transcription is not yet supported on Discord (Phase 5 roadmap).
"""

import asyncio
import logging
import os
import sys

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

DISCORD_TOKEN       = os.environ.get("DISCORD_TOKEN", "")
DISCORD_ALLOWED_ID  = int(os.environ.get("DISCORD_ALLOWED_USER_ID", "0"))
DISCORD_PREFIX      = os.environ.get("DISCORD_COMMAND_PREFIX", "!")

# If True, Alfred only responds in DMs and channels where it is explicitly
# mentioned or the message uses the command prefix. If False (default),
# Alfred classifies ALL messages in channels it can see.
DISCORD_PREFIX_ONLY = os.environ.get("DISCORD_PREFIX_ONLY", "false").lower() == "true"


def _check_config() -> bool:
    """Return True if Discord is configured, log a clear error if not."""
    if not DISCORD_TOKEN:
        logger.error(
            "DISCORD_TOKEN is not set. "
            "Add it to your Railway environment variables to enable Discord."
        )
        return False
    return True


# ─────────────────────────────────────────────────────────────────────────────
# BOT SETUP
# ─────────────────────────────────────────────────────────────────────────────

def _create_discord_client():
    """Create and configure the discord.py client."""
    try:
        import discord
    except ImportError:
        logger.error(
            "discord.py is not installed. "
            "Run: pip install discord.py  (or add 'discord.py>=2.3.2' to requirements.txt)"
        )
        return None

    intents = discord.Intents.default()
    intents.message_content = True   # Required to read message text
    intents.members = False          # We don't need member list

    client = discord.Client(intents=intents)
    return client, discord


def main() -> None:
    """Start the Alfred Discord bot."""
    print("[discord_bot] main() called", flush=True)
    logging.basicConfig(
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        level=logging.INFO,
        stream=sys.stdout,   # Explicitly write to stdout so Railway captures it
    )
    logging.getLogger("discord").setLevel(logging.WARNING)

    if not _check_config():
        print("[discord_bot] DISCORD_TOKEN missing — exiting", flush=True)
        sys.exit(1)

    result = _create_discord_client()
    if result is None:
        sys.exit(1)

    client, discord = result

    # ─────────────────────────────────────────────────────────────────────────
    # PLUGIN DISCOVERY
    # ─────────────────────────────────────────────────────────────────────────
    from core.plugin_loader import discover_plugins, get_plugin_keyword_rules, get_plugin_gpt_block, get_all_plugin_intents
    from core.data import load_memory, get_active_categories
    from core.intent import classify, refresh_intent_prompt

    loaded_plugins = discover_plugins()
    logger.info(
        f"Discord: loaded {len(loaded_plugins)} plugin(s): "
        f"{', '.join(p.name for p in loaded_plugins)}"
    )

    # Refresh intent classifier with memory + plugin context
    try:
        mem        = load_memory()
        categories = get_active_categories(mem)
        plugin_gpt = get_plugin_gpt_block(loaded_plugins)
        refresh_intent_prompt(categories, plugin_gpt_block=plugin_gpt)

        from core.intent import add_plugin_keyword_rules, register_plugin_intents
        plugin_kw_rules = get_plugin_keyword_rules(loaded_plugins)
        if plugin_kw_rules:
            add_plugin_keyword_rules(plugin_kw_rules)
        plugin_intents = get_all_plugin_intents(loaded_plugins)
        if plugin_intents:
            register_plugin_intents(plugin_intents)

        logger.info("Discord: intent classifier ready.")
    except Exception as e:
        logger.warning(f"Discord: intent setup failed: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # RATE LIMITER
    # ─────────────────────────────────────────────────────────────────────────
    import time as _time_module
    _rate_window_start: list = [0.0]
    _rate_count: list = [0]
    RATE_LIMIT_COUNT  = 10
    RATE_LIMIT_WINDOW = 60

    def _check_rate_limit() -> bool:
        now = _time_module.monotonic()
        if now - _rate_window_start[0] > RATE_LIMIT_WINDOW:
            _rate_window_start[0] = now
            _rate_count[0] = 0
        _rate_count[0] += 1
        return _rate_count[0] <= RATE_LIMIT_COUNT

    # ─────────────────────────────────────────────────────────────────────────
    # EVENT HANDLERS
    # ─────────────────────────────────────────────────────────────────────────

    @client.event
    async def on_ready():
        logger.info(
            f"Alfred Discord bot ready. "
            f"Logged in as {client.user} (ID: {client.user.id})"
        )
        logger.info(
            f"Prefix: '{DISCORD_PREFIX}' | "
            f"Allowed user ID: {DISCORD_ALLOWED_ID or 'ANY (not set)'} | "
            f"Prefix-only mode: {DISCORD_PREFIX_ONLY}"
        )

    @client.event
    async def on_message(message):
        # Ignore messages from the bot itself
        if message.author == client.user:
            return

        # Auth guard — if DISCORD_ALLOWED_USER_ID is set, restrict to that user
        if DISCORD_ALLOWED_ID and message.author.id != DISCORD_ALLOWED_ID:
            return

        # Ignore empty messages
        text = (message.content or "").strip()
        if not text:
            return

        # In prefix-only mode, only respond to messages starting with the prefix
        has_prefix = text.startswith(DISCORD_PREFIX) or text.startswith("/")
        if DISCORD_PREFIX_ONLY and not has_prefix:
            return

        # Rate limit
        if not _check_rate_limit():
            await message.channel.send(
                "You're sending messages very quickly — slow down a little."
            )
            return

        # Normalize prefix: replace "!" with "/" so intent classifier recognises commands
        if text.startswith(DISCORD_PREFIX) and DISCORD_PREFIX != "/":
            text = "/" + text[len(DISCORD_PREFIX):]

        # Build platform context
        from adapters.discord_adapter import make_context
        ctx = make_context(message)
        # Override text with normalised version
        ctx = _rebuild_ctx_with_text(ctx, text)

        # Route commands directly to avoid classification overhead
        if has_prefix:
            handled = await _handle_discord_command(ctx, message, loaded_plugins)
            if handled:
                return

        # If a setup wizard is active, intercept text before the intent classifier
        try:
            from features.setup import is_setup_active, handle_setup_message_discord
            if is_setup_active() and not has_prefix:
                await handle_setup_message_discord(ctx, text)
                return
        except Exception as _setup_err:
            logger.warning(f"Discord: setup intercept error: {_setup_err}")

        # Natural language — classify and dispatch
        try:
            await ctx.send_typing()
            intent_result = await classify(text)
            from core.alfred_dispatch import alfred_dispatch
            await alfred_dispatch(intent_result, ctx, loaded_plugins)
        except Exception as e:
            logger.error(f"Discord: dispatch error: {e}", exc_info=True)
            await message.channel.send(
                "Something went wrong. Try again or use a command like `!scores nba`."
            )

    # ─────────────────────────────────────────────────────────────────────────
    # START POLLING
    # ─────────────────────────────────────────────────────────────────────────
    logger.info("Starting Discord bot...")
    client.run(DISCORD_TOKEN)


# ─────────────────────────────────────────────────────────────────────────────
# DIRECT COMMAND ROUTING
# Handles commands without going through the intent classifier.
# Fast-path for explicit /command or !command messages.
# ─────────────────────────────────────────────────────────────────────────────

async def _handle_discord_command(ctx, message, loaded_plugins) -> bool:
    """
    Route a Discord command directly to the appropriate handler.

    Returns True if the command was handled, False if it should fall through
    to the intent classifier.
    """
    text_lower = (ctx.text or "").lower().lstrip("/!").strip()
    cmd = text_lower.split()[0] if text_lower else ""
    args_str = " ".join(ctx.args)

    # ── Sports commands (Sports Pack) ────────────────────────────────────────
    if cmd == "scores":
        await _discord_scores(ctx, args_str, loaded_plugins)
        return True

    if cmd == "standings":
        await _discord_standings(ctx, args_str, loaded_plugins)
        return True

    if cmd == "schedule":
        await _discord_schedule(ctx, args_str, loaded_plugins)
        return True

    if cmd in ("stats", "leaders"):
        await _discord_stats(ctx, cmd, args_str, loaded_plugins)
        return True

    # ── General commands ─────────────────────────────────────────────────────
    if cmd == "briefing":
        await _discord_briefing(ctx)
        return True

    if cmd == "topplays":
        await _discord_topplays(ctx)
        return True

    if cmd == "help":
        await _discord_help(ctx, loaded_plugins)
        return True

    if cmd == "ask":
        # Pass through to intent classifier for /ask with text
        if args_str:
            from core.intent import classify
            from core.alfred_dispatch import alfred_dispatch
            intent_result = await classify(f"ask {args_str}")
            await alfred_dispatch(intent_result, ctx, loaded_plugins)
            return True
        else:
            await ctx.reply("What would you like to know? Type your question after `!ask`.")
            return True

    if cmd == "setup":
        await _discord_setup(ctx)
        return True

    # Unknown command — fall through to intent classifier
    return False


# ─────────────────────────────────────────────────────────────────────────────
# DISCORD SETUP HANDLER
# ─────────────────────────────────────────────────────────────────────────────

async def _discord_setup(ctx) -> None:
    """
    Handle !setup (and !setup cancel / !setup memory) on Discord.

    !setup         — starts the 14-step preferences wizard
    !setup cancel  — cancels an in-progress wizard session
    !setup memory  — friendly note (full memory wizard is Telegram-only for now)
    """
    from features.setup import (
        start_prefs_flow_discord,
        _clear_state,          # noqa: F401  (private but safe to import directly)
        is_setup_active,
    )

    sub = (ctx.args[0].lower() if ctx.args else "")

    if sub == "cancel":
        _clear_state()
        await ctx.reply(
            "Setup cancelled. Your settings are unchanged.\n"
            "Run `!setup` anytime to restart."
        )
        return

    if sub == "memory":
        await ctx.reply(
            "Full memory setup is best done via the Telegram bot (it uses guided buttons).\n"
            "On Discord you can still add facts directly: `!memory add [category] [fact]`"
        )
        return

    # Default — launch 14-step preferences wizard
    await start_prefs_flow_discord(ctx)


# ─────────────────────────────────────────────────────────────────────────────
# DISCORD COMMAND IMPLEMENTATIONS
# Each function fetches data using the existing plugin API functions and
# sends the result via ctx.reply_html().
# ─────────────────────────────────────────────────────────────────────────────

async def _discord_scores(ctx, args_str: str, loaded_plugins) -> None:
    """!scores [league] — get yesterday's scores."""
    try:
        from plugins.sports import espn_api, formatting, config as sports_config

        if not args_str:
            # No league specified — show available leagues
            await ctx.reply_html(
                "<b>Usage:</b> <code>!scores [league]</code>\n\n"
                "Available: nba, nfl, mlb, nhl, ncaaf, ncaab, epl, mls, bundesliga, laliga\n\n"
                "Example: <code>!scores nba</code>"
            )
            return

        league_input = args_str.split()[0].lower()
        league_slug  = sports_config.normalize_league(league_input)

        if not league_slug:
            await ctx.reply_html(
                f"❌ Unknown league: <b>{league_input}</b>\n\n"
                "Use: nba, nfl, mlb, nhl, ncaaf, ncaab, epl, mls, bundesliga, laliga"
            )
            return

        await ctx.send_typing()
        scores = await espn_api.get_scores(league_slug)

        if not scores:
            league_info = sports_config.get_league_info(league_slug)
            await ctx.reply_html(
                formatting.format_error("Could not fetch scores", league_info["name"])
            )
            return

        # Filter by team if provided
        games = scores.get("games", [])
        if len(args_str.split()) > 1:
            team_filter = " ".join(args_str.split()[1:]).lower()
            games = [
                g for g in games
                if team_filter in g["home_team"].lower() or team_filter in g["away_team"].lower()
            ]

        league_meta  = scores.get("league", {})
        league_name  = league_meta.get("name", league_slug.upper()) if isinstance(league_meta, dict) else str(league_meta)
        league_emoji = league_meta.get("emoji", "🏆") if isinstance(league_meta, dict) else "🏆"
        formatted = formatting.format_scoreboard(games, league_name, league_emoji)
        await ctx.reply_html(formatted)

    except Exception as e:
        logger.error(f"discord !scores error: {e}", exc_info=True)
        await ctx.reply("❌ Could not fetch scores right now. Try again in a moment.")


async def _discord_standings(ctx, args_str: str, loaded_plugins) -> None:
    """!standings [league] — get standings."""
    try:
        from plugins.sports import espn_api, formatting, config as sports_config

        if not args_str:
            await ctx.reply_html(
                "<b>Usage:</b> <code>!standings [league]</code>\n\n"
                "Example: <code>!standings nba</code>"
            )
            return

        league_input = args_str.split()[0].lower()
        league_slug  = sports_config.normalize_league(league_input)

        if not league_slug:
            await ctx.reply_html(f"❌ Unknown league: <b>{league_input}</b>")
            return

        await ctx.send_typing()
        standings = await espn_api.get_standings(league_slug)

        if not standings:
            league_info = sports_config.get_league_info(league_slug)
            await ctx.reply_html(
                formatting.format_error("Could not fetch standings", league_info["name"])
            )
            return

        standings_list = standings.get("standings", [])
        league_name    = standings.get("league", league_slug.upper())
        league_info_d  = sports_config.get_league_info(league_slug)
        league_emoji   = league_info_d.get("emoji", "🏆") if league_info_d else "🏆"
        formatted = formatting.format_standings(standings_list, league_name, league_emoji)
        await ctx.reply_html(formatted)

    except Exception as e:
        logger.error(f"discord !standings error: {e}", exc_info=True)
        await ctx.reply("❌ Could not fetch standings right now.")


async def _discord_schedule(ctx, args_str: str, loaded_plugins) -> None:
    """!schedule [league] — get upcoming games."""
    try:
        from plugins.sports import espn_api, formatting, config as sports_config

        if not args_str:
            await ctx.reply_html(
                "<b>Usage:</b> <code>!schedule [league]</code>\n\n"
                "Example: <code>!schedule nba</code>"
            )
            return

        league_input = args_str.split()[0].lower()
        league_slug  = sports_config.normalize_league(league_input)

        if not league_slug:
            await ctx.reply_html(f"❌ Unknown league: <b>{league_input}</b>")
            return

        await ctx.send_typing()
        schedule = await espn_api.get_schedule(league_slug)

        if not schedule:
            league_info = sports_config.get_league_info(league_slug)
            await ctx.reply_html(
                formatting.format_error("Could not fetch schedule", league_info["name"])
            )
            return

        games_list   = schedule.get("games", [])
        league_name  = schedule.get("league", league_slug.upper())
        league_info_d = sports_config.get_league_info(league_slug)
        league_emoji  = league_info_d.get("emoji", "🏆") if league_info_d else "🏆"
        team_filter_out = schedule.get("team", "")
        formatted = formatting.format_schedule(games_list, league_name, league_emoji, team_filter_out)
        await ctx.reply_html(formatted)

    except Exception as e:
        logger.error(f"discord !schedule error: {e}", exc_info=True)
        await ctx.reply("❌ Could not fetch schedule right now.")


async def _discord_stats(ctx, cmd: str, args_str: str, loaded_plugins) -> None:
    """!stats [player/team name] / !leaders [league] [stat]"""
    try:
        from plugins.sports.commands import cmd_stats, cmd_leaders

        # Build a mock that routes back to the sports commands.
        # For Phase 4 these still use the Telegram handler logic with
        # ctx._update=None — so we build the intent and dispatch it.
        if not args_str:
            if cmd == "stats":
                await ctx.reply_html(
                    "<b>Usage:</b> <code>!stats [player or team name]</code>\n\n"
                    "Examples:\n"
                    "• <code>!stats nikola jokic</code>\n"
                    "• <code>!stats denver nuggets</code>"
                )
            else:
                await ctx.reply_html(
                    "<b>Usage:</b> <code>!leaders [league] [stat]</code>\n\n"
                    "Example: <code>!leaders nba points</code>"
                )
            return

        # Route through intent classifier for now
        await ctx.send_typing()
        from core.intent import classify
        from core.alfred_dispatch import alfred_dispatch
        query = f"{cmd} {args_str}"
        intent_result = await classify(query)
        await alfred_dispatch(intent_result, ctx, loaded_plugins)

    except Exception as e:
        logger.error(f"discord !{cmd} error: {e}", exc_info=True)
        await ctx.reply(f"❌ Could not fetch {cmd} right now.")


async def _discord_briefing(ctx) -> None:
    """!briefing — trigger morning briefing via AlfredContext (Discord-aware)."""
    try:
        from features.briefing import send_briefing_ctx
        await send_briefing_ctx(ctx)
    except Exception as e:
        logger.error(f"discord !briefing error: {e}", exc_info=True)
        await ctx.reply("❌ Could not generate briefing right now.")


async def _discord_topplays(ctx) -> None:
    """!topplays — fetch Reddit top plays for user's configured leagues (Discord inline-only)."""
    try:
        from plugins.sports.briefing import (
            _build_top_plays, _DISCORD_INLINE_DOMAINS, LEAGUE_SUBREDDITS,
        )
        from core.userdata import load_user_data

        uid      = str(ctx.user_id)
        udata    = load_user_data()
        settings = udata.get(uid, {}).get("settings", {})

        # Resolve leagues — same logic as briefing
        fav_leagues = settings.get("favorite_leagues", [])
        all_league_slugs = list(LEAGUE_SUBREDDITS.keys())
        leagues_to_show = fav_leagues if fav_leagues else all_league_slugs

        await ctx.reply_html("🎬 <b>Fetching top plays…</b>")

        clips = await _build_top_plays(leagues_to_show, total=25)
        inline_clips = [c for c in clips if c["domain"] in _DISCORD_INLINE_DOMAINS][:10]

        if not inline_clips:
            await ctx.reply_html("😔 No inline-playable clips found right now. Try again later.")
            return

        lines = ["🎬 **Top Plays**"]
        for i, clip in enumerate(inline_clips, 1):
            title = clip["title"]
            if len(title) > 80:
                title = title[:77] + "…"
            lines.append(f"{i}. {title}")
            lines.append(clip["url"])

        await ctx.reply_html("\n".join(lines))
    except Exception as e:
        logger.error(f"discord !topplays error: {e}", exc_info=True)
        await ctx.reply("❌ Could not fetch top plays right now.")


async def _discord_help(ctx, loaded_plugins) -> None:
    """!help — show available commands."""
    plugin_cmds = ""
    for plugin in loaded_plugins:
        cmds = " ".join(f"`!{c['command']}`" for c in plugin.commands)
        if cmds:
            plugin_cmds += f"\n**{plugin.name}:** {cmds}"

    await ctx.reply_html(
        "<b>Alfred — Discord Commands</b>\n\n"
        "<b>Sports (Sports Pack)</b>\n"
        "  !scores [league]       — yesterday's scores\n"
        "  !standings [league]    — current standings\n"
        "  !schedule [league]     — upcoming games\n"
        "  !stats [player/team]   — stats lookup\n"
        "  !leaders [league]      — league leaders\n\n"
        "<b>Assistant</b>\n"
        "  !ask [question]        — ask me anything\n"
        "  !briefing              — morning briefing\n"
        "  !topplays              — Reddit top plays (inline video)\n\n"
        "<b>Lists & Tasks</b>\n"
        "  !todos / !notes / !reminders — coming soon\n\n"
        "<b>Natural Language</b>\n"
        "  Just type naturally — \"who leads the NBA in points?\" works.\n\n"
        "Use <code>!</code> or <code>/</code> prefix for commands."
    )


# ─────────────────────────────────────────────────────────────────────────────
# UTILITY
# ─────────────────────────────────────────────────────────────────────────────

def _rebuild_ctx_with_text(ctx, new_text: str):
    """Return a copy of ctx with text replaced (for prefix normalisation)."""
    from adapters.discord_adapter import make_context

    # We need the original message object — it's stored in the closures
    # inside ctx._reply_fn etc. We can't easily reconstruct from scratch.
    # Instead, mutate the text and args in-place (safe since ctx is fresh).
    ctx.text = new_text
    parts = new_text.split()
    if parts and (parts[0].startswith("/") or parts[0].startswith("!")):
        ctx.args = parts[1:]
    else:
        ctx.args = parts
    return ctx


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    main()

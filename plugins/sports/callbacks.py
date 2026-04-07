"""
Callback query handlers for sports plugin interactive UI.

Handles button presses from inline keyboards in sports commands.
Callback patterns: sports_*, sports_league_*, sports_team_*, etc.
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from core.config import ALLOWED_USER_ID
from plugins.sports import config as sports_config
from plugins.sports import espn_api
from plugins.sports import formatting
from plugins.sports import data as sports_data

logger = logging.getLogger(__name__)


async def handle_sports_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """
    Main callback handler for sports plugin.

    Handles button presses from /scores, /standings, /schedule, /sports, /bets.
    Callback data format: "sports_<action>_<param>"
    """
    if update.callback_query.from_user.id != ALLOWED_USER_ID:
        await update.callback_query.answer("Not authorized", show_alert=True)
        return

    query = update.callback_query
    data = query.data

    logger.debug(f"Sports callback: {data}")

    try:
        await query.answer()  # Acknowledge immediately

        # Parse callback data
        parts = data.split("_")
        if len(parts) < 2:
            return

        action = parts[1]

        # ─────────────────────────────────────────────────────────────────
        # SCORES CALLBACKS
        # ─────────────────────────────────────────────────────────────────
        if action == "scores" and len(parts) >= 3:
            league_slug = parts[2]
            await _handle_scores_callback(query, league_slug)

        # ─────────────────────────────────────────────────────────────────
        # STANDINGS CALLBACKS
        # ─────────────────────────────────────────────────────────────────
        elif action == "standings" and len(parts) >= 3:
            league_slug = parts[2]
            await _handle_standings_callback(query, league_slug)

        # ─────────────────────────────────────────────────────────────────
        # SCHEDULE CALLBACKS
        # ─────────────────────────────────────────────────────────────────
        elif action == "schedule" and len(parts) >= 3:
            league_slug = parts[2]
            await _handle_schedule_callback(query, league_slug)

        # ─────────────────────────────────────────────────────────────────
        # SETUP CALLBACKS
        # ─────────────────────────────────────────────────────────────────
        elif action == "setup":
            subaction = parts[2] if len(parts) > 2 else "menu"
            if subaction == "add_team":
                await _handle_setup_add_team(query)
            elif subaction == "view_teams":
                await _handle_setup_view_teams(query)
            elif subaction == "bankroll":
                await _handle_setup_bankroll(query)

        # ─────────────────────────────────────────────────────────────────
        # ALERT CALLBACKS
        # ─────────────────────────────────────────────────────────────────
        elif action == "alert_toggle":
            await _handle_alert_toggle(query)

        # ─────────────────────────────────────────────────────────────────
        # BRIEFING SETTINGS CALLBACKS
        # ─────────────────────────────────────────────────────────────────
        elif action == "briefing":
            subaction = parts[2] if len(parts) > 2 else "menu"
            if subaction == "menu":
                await _handle_briefing_menu(query)
            elif subaction == "toggle":
                setting_key = parts[3] if len(parts) > 3 else ""
                await _handle_briefing_toggle(query, setting_key)
            elif subaction == "clear_players":
                await _handle_briefing_clear_players(query)
            elif subaction == "add_player":
                await _handle_briefing_add_player_prompt(query)

        # ─────────────────────────────────────────────────────────────────
        # BET CALLBACKS
        # ─────────────────────────────────────────────────────────────────
        elif action == "bet":
            subaction = parts[2] if len(parts) > 2 else "view"
            if subaction == "add":
                await _handle_bet_add(query)
            elif subaction == "stats":
                await _handle_bet_stats(query)

    except Exception as e:
        logger.error(f"Callback error: {e}")
        await query.edit_message_text("❌ An error occurred. Try again with /sports.")


# ═══════════════════════════════════════════════════════════════════════════════
# SCORES CALLBACK
# ═══════════════════════════════════════════════════════════════════════════════

async def _handle_scores_callback(query, league_slug: str) -> None:
    """Handle league selection for scores."""
    league_info = sports_config.get_league_info(league_slug)
    if not league_info:
        await query.edit_message_text("❌ Unknown league")
        return

    emoji = league_info.get("emoji", "🏆")

    # Fetch scores
    scores = await espn_api.get_scores(league_slug)
    if not scores:
        await query.edit_message_text(
            formatting.format_error("Could not fetch scores", league_info["name"]),
            parse_mode="HTML"
        )
        return

    message = formatting.format_scoreboard(
        scores.get("games", []),
        league_info["name"],
        emoji
    )

    # Add refresh button
    keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data=f"sports_scores_{league_slug}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(message, reply_markup=reply_markup, parse_mode="HTML")


# ═══════════════════════════════════════════════════════════════════════════════
# STANDINGS CALLBACK
# ═══════════════════════════════════════════════════════════════════════════════

async def _handle_standings_callback(query, league_slug: str) -> None:
    """Handle league selection for standings."""
    league_info = sports_config.get_league_info(league_slug)
    if not league_info:
        await query.edit_message_text("❌ Unknown league")
        return

    emoji = league_info.get("emoji", "🏆")

    standings = await espn_api.get_standings(league_slug)
    if not standings:
        await query.edit_message_text(
            formatting.format_error("Could not fetch standings", league_info["name"]),
            parse_mode="HTML"
        )
        return

    message = formatting.format_standings(
        standings.get("standings", []),
        league_info["name"],
        emoji
    )

    keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data=f"sports_standings_{league_slug}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(message, reply_markup=reply_markup, parse_mode="HTML")


# ═══════════════════════════════════════════════════════════════════════════════
# SCHEDULE CALLBACK
# ═══════════════════════════════════════════════════════════════════════════════

async def _handle_schedule_callback(query, league_slug: str) -> None:
    """Handle league selection for schedule."""
    league_info = sports_config.get_league_info(league_slug)
    if not league_info:
        await query.edit_message_text("❌ Unknown league")
        return

    emoji = league_info.get("emoji", "🏆")

    schedule = await espn_api.get_schedule(league_slug)
    if not schedule:
        await query.edit_message_text(
            formatting.format_error("Could not fetch schedule", league_info["name"]),
            parse_mode="HTML"
        )
        return

    message = formatting.format_schedule(
        schedule.get("games", []),
        league_info["name"],
        emoji
    )

    keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data=f"sports_schedule_{league_slug}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(message, reply_markup=reply_markup, parse_mode="HTML")


# ═══════════════════════════════════════════════════════════════════════════════
# SETUP CALLBACKS
# ═══════════════════════════════════════════════════════════════════════════════

async def _handle_setup_add_team(query) -> None:
    """Prompt user to add favorite team."""
    message = (
        "<b>Add Favorite Team</b>\n\n"
        "Reply with: <code>&lt;league&gt; &lt;team_name&gt;</code>\n\n"
        "Example: <code>NFL Chiefs</code>\n"
        "or: <code>NBA Lakers</code>"
    )
    await query.edit_message_text(message, parse_mode="HTML")


async def _handle_setup_view_teams(query) -> None:
    """Show list of favorite teams."""
    teams = sports_config.get_favorite_teams()

    if not teams:
        await query.edit_message_text("No favorite teams added yet.")
        return

    message = "<b>Favorite Teams</b>\n\n"
    for team in teams:
        league = team.get("league", "")
        name = team.get("team_name", "")
        message += f"• {league}: {name}\n"

    await query.edit_message_text(message, parse_mode="HTML")


async def _handle_setup_bankroll(query) -> None:
    """Prompt user to set bankroll."""
    message = (
        "<b>Set Bankroll</b>\n\n"
        "Reply with your betting bankroll amount:\n"
        "<code>1000</code> (for $1,000)"
    )
    await query.edit_message_text(message, parse_mode="HTML")


# ═══════════════════════════════════════════════════════════════════════════════
# ALERT CALLBACK
# ═══════════════════════════════════════════════════════════════════════════════

async def _handle_alert_toggle(query) -> None:
    """Toggle game alerts on/off."""
    settings = sports_config.load_sports_settings()
    current = settings.get("alerts_enabled", True)
    new_state = not current

    sports_config.set_alerts_enabled(new_state)

    status = "✓ Enabled" if new_state else "✗ Disabled"
    await query.edit_message_text(f"Game Alerts: {status}")


# ═══════════════════════════════════════════════════════════════════════════════
# BET CALLBACKS
# ═══════════════════════════════════════════════════════════════════════════════

async def _handle_bet_add(query) -> None:
    """Prompt user to add a bet."""
    message = (
        "<b>📊 Log a New Bet</b>\n\n"
        "Format: <code>&lt;league&gt; &lt;pick&gt; &lt;odds&gt; &lt;stake&gt;</code>\n\n"
        "Example:\n"
        "<code>NFL Chiefs -110 50</code>\n"
        "<code>NBA Lakers+5.5 +110 25</code>"
    )
    await query.edit_message_text(message, parse_mode="HTML")


# ═══════════════════════════════════════════════════════════════════════════════
# BRIEFING SETTINGS CALLBACKS
# ═══════════════════════════════════════════════════════════════════════════════

def _briefing_menu_text(settings: dict) -> str:
    """Build the briefing settings status message."""
    reddit  = settings.get("briefing_reddit_highlights", True)
    youtube = settings.get("briefing_youtube_top_plays", False)
    players = settings.get("briefing_track_fav_players", False)
    fav     = settings.get("briefing_favorite_players", [])

    msg  = "<b>📊 Briefing Settings</b>\n\n"
    msg += f"Reddit Highlights: {'✅ On' if reddit else '❌ Off'}\n"
    msg += f"  Top Highlight posts per league, free, no API key.\n\n"
    msg += f"YouTube Top Plays: {'✅ On' if youtube else '❌ Off'}\n"
    msg += f"  Search URL (free) or direct video with YOUTUBE_API_KEY.\n\n"
    msg += f"Player Tracking: {'✅ On' if players else '❌ Off'}\n"
    if players:
        if fav:
            msg += f"  Tracking: {', '.join(fav)}\n"
        else:
            msg += f"  No players added yet — use /sports addplayer &lt;name&gt;\n"
    else:
        msg += (
            "  ⚠️ Uses API-Sports (~3-5 calls/player/day).\n"
            "  Free tier = 100 req/day total across all sports features.\n"
            "  2+ players may exhaust quota before afternoon.\n"
            "  Upgrade at api-sports.io ($10/mo+) for higher limits.\n"
        )
    return msg


def _briefing_menu_keyboard(settings: dict) -> InlineKeyboardMarkup:
    """Build the briefing settings inline keyboard."""
    reddit  = settings.get("briefing_reddit_highlights", True)
    youtube = settings.get("briefing_youtube_top_plays", False)
    players = settings.get("briefing_track_fav_players", False)
    fav     = settings.get("briefing_favorite_players", [])

    keyboard = [
        [InlineKeyboardButton(
            f"{'🔴 Turn Off' if reddit else '🟢 Turn On'} Reddit Highlights",
            callback_data="sports_briefing_toggle_reddit"
        )],
        [InlineKeyboardButton(
            f"{'🔴 Turn Off' if youtube else '🟢 Turn On'} YouTube Top Plays",
            callback_data="sports_briefing_toggle_youtube"
        )],
        [InlineKeyboardButton(
            f"{'🔴 Turn Off' if players else '🟢 Turn On'} Player Tracking",
            callback_data="sports_briefing_toggle_players"
        )],
    ]
    if players:
        keyboard.append([
            InlineKeyboardButton("➕ Add Player", callback_data="sports_briefing_add_player"),
        ])
        if fav:
            keyboard.append([
                InlineKeyboardButton("🗑 Clear All Players", callback_data="sports_briefing_clear_players"),
            ])
    return InlineKeyboardMarkup(keyboard)


async def _handle_briefing_menu(query) -> None:
    """Show the briefing settings menu."""
    settings = sports_config.load_sports_settings()
    await query.edit_message_text(
        _briefing_menu_text(settings),
        reply_markup=_briefing_menu_keyboard(settings),
        parse_mode="HTML",
    )


async def _handle_briefing_toggle(query, setting_key: str) -> None:
    """
    Toggle a briefing boolean setting.

    setting_key: "reddit" | "youtube" | "players"
    """
    key_map = {
        "reddit":  "briefing_reddit_highlights",
        "youtube": "briefing_youtube_top_plays",
        "players": "briefing_track_fav_players",
    }
    full_key = key_map.get(setting_key)
    if not full_key:
        await query.answer("Unknown setting", show_alert=True)
        return

    settings = sports_config.load_sports_settings()
    current  = settings.get(full_key, False)
    settings[full_key] = not current
    sports_config.save_sports_settings(settings)

    # If turning player tracking ON, show the cost warning once via popup
    if setting_key == "players" and not current:
        await query.answer(
            "⚠️ Player tracking uses API-Sports (100 req/day free). "
            "Add players with /sports addplayer <name>",
            show_alert=True,
        )
    else:
        await query.answer()

    # Refresh the menu
    await query.edit_message_text(
        _briefing_menu_text(settings),
        reply_markup=_briefing_menu_keyboard(settings),
        parse_mode="HTML",
    )


async def _handle_briefing_add_player_prompt(query) -> None:
    """Show instructions for adding a tracked player."""
    await query.edit_message_text(
        "<b>➕ Add Tracked Player</b>\n\n"
        "Send a message:\n"
        "<code>/sports addplayer &lt;name&gt;</code>\n\n"
        "Examples:\n"
        "<code>/sports addplayer LeBron James</code>\n"
        "<code>/sports addplayer Jokic</code>\n\n"
        "Their last-game stats will appear in your morning briefing "
        "if they played yesterday.\n\n"
        "Remove with: <code>/sports removeplayer &lt;name&gt;</code>",
        parse_mode="HTML",
    )


async def _handle_briefing_clear_players(query) -> None:
    """Clear all favorite players."""
    settings = sports_config.load_sports_settings()
    settings["briefing_favorite_players"] = []
    sports_config.save_sports_settings(settings)
    await query.answer("Cleared all tracked players.")
    await query.edit_message_text(
        _briefing_menu_text(settings),
        reply_markup=_briefing_menu_keyboard(settings),
        parse_mode="HTML",
    )


async def _handle_bet_stats(query) -> None:
    """Show betting statistics."""
    stats = sports_data.get_bet_stats()

    if stats["total_bets"] == 0:
        await query.edit_message_text("📊 No bets to analyze yet.")
        return

    message = "<b>📊 Betting Statistics</b>\n\n"
    message += f"Total Bets: {stats['total_bets']}\n"
    message += f"W-L-P: {stats['wins']}-{stats['losses']}-{stats['pushes']}\n"
    message += f"Win Rate: {stats['win_rate']}%\n"
    message += f"Stake: ${stats['total_stake']:.2f}\n"
    message += f"P&L: ${stats['total_pnl']:+.2f}\n"
    message += f"ROI: {stats['roi']:+.2f}%\n"

    await query.edit_message_text(message, parse_mode="HTML")

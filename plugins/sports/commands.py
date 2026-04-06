"""
Command handlers for sports plugin.

Each function handles a /command from Telegram.
"""

import logging
from typing import Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from core.config import ALLOWED_USER_ID
from plugins.sports import config as sports_config
from plugins.sports import espn_api
from plugins.sports import formatting
from plugins.sports import data as sports_data
from plugins.sports import betting
from plugins.sports import charts
from plugins.sports import stats_api

logger = logging.getLogger(__name__)


async def cmd_scores(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /scores [league] [team]

    Get live scores for a league or team.
    """
    if update.message.from_user.id != ALLOWED_USER_ID:
        return

    # Parse arguments
    args = update.message.text.split()[1:] if len(update.message.text.split()) > 1 else []

    if not args:
        # Show league selection
        await _show_league_menu(update, "scores")
        return

    # Get league
    league_input = args[0].lower()
    league_slug = sports_config.normalize_league(league_input)

    if not league_slug:
        await update.message.reply_text(
            f"❌ Unknown league: <b>{league_input}</b>\n\n"
            "Use: /scores [nfl|nba|mlb|nhl|ncaaf|ncaab|epl|mls|bundesliga|laliga] [team]",
            parse_mode="HTML"
        )
        return

    league_info = sports_config.get_league_info(league_slug)
    emoji = league_info.get("emoji", "🏆")

    # Fetch scores
    scores = await espn_api.get_scores(league_slug)
    if not scores:
        await update.message.reply_text(
            formatting.format_error("Could not fetch scores from ESPN", league_info["name"]),
            parse_mode="HTML"
        )
        return

    # Filter by team if provided
    games = scores.get("games", [])
    if len(args) > 1:
        team_filter = " ".join(args[1:]).lower()
        games = [
            g for g in games
            if team_filter in g["home_team"].lower() or team_filter in g["away_team"].lower()
        ]

    message = formatting.format_scoreboard(games, league_info["name"], emoji)
    await update.message.reply_text(message, parse_mode="HTML")


async def cmd_standings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /standings [league]

    View league standings.
    """
    if update.message.from_user.id != ALLOWED_USER_ID:
        return

    args = update.message.text.split()[1:] if len(update.message.text.split()) > 1 else []

    if not args:
        await _show_league_menu(update, "standings")
        return

    league_input = args[0].lower()
    league_slug = sports_config.normalize_league(league_input)

    if not league_slug:
        await update.message.reply_text(
            f"❌ Unknown league: <b>{league_input}</b>",
            parse_mode="HTML"
        )
        return

    league_info = sports_config.get_league_info(league_slug)
    emoji = league_info.get("emoji", "🏆")

    standings = await espn_api.get_standings(league_slug)
    if not standings:
        await update.message.reply_text(
            formatting.format_error("Could not fetch standings from ESPN", league_info["name"]),
            parse_mode="HTML"
        )
        return

    message = formatting.format_standings(
        standings.get("standings", []),
        league_info["name"],
        emoji
    )
    await update.message.reply_text(message, parse_mode="HTML")


async def cmd_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /schedule [league] [team]

    View upcoming games.
    """
    if update.message.from_user.id != ALLOWED_USER_ID:
        return

    args = update.message.text.split()[1:] if len(update.message.text.split()) > 1 else []

    if not args:
        await _show_league_menu(update, "schedule")
        return

    league_input = args[0].lower()
    league_slug = sports_config.normalize_league(league_input)

    if not league_slug:
        await update.message.reply_text(
            f"❌ Unknown league: <b>{league_input}</b>",
            parse_mode="HTML"
        )
        return

    league_info = sports_config.get_league_info(league_slug)
    emoji = league_info.get("emoji", "🏆")

    # Optional team filter
    team_filter = " ".join(args[1:]) if len(args) > 1 else None

    schedule = await espn_api.get_schedule(league_slug, team_name=team_filter)
    if not schedule:
        await update.message.reply_text(
            formatting.format_error("Could not fetch schedule from ESPN", league_info["name"]),
            parse_mode="HTML"
        )
        return

    message = formatting.format_schedule(
        schedule.get("games", []),
        league_info["name"],
        emoji,
        team=team_filter or ""
    )
    await update.message.reply_text(message, parse_mode="HTML")


async def cmd_sports(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /sports [setup|config]

    Configure favorite teams, alerts, and betting settings.
    """
    if update.message.from_user.id != ALLOWED_USER_ID:
        return

    args = update.message.text.split()[1:] if len(update.message.text.split()) > 1 else []
    action = args[0].lower() if args else "setup"

    if action in ["setup", "config"]:
        # Show settings menu
        settings = sports_config.load_sports_settings()

        fav_teams = settings.get("favorite_teams", [])
        fav_leagues = settings.get("favorite_leagues", [])
        alerts = settings.get("alerts_enabled", True)
        bankroll = settings.get("bankroll", 0.0)

        message = "<b>⚙️ Sports Settings</b>\n\n"
        message += f"Alerts: {'✓ Enabled' if alerts else '✗ Disabled'}\n"
        message += f"Favorite Teams: {len(fav_teams)}\n"
        message += f"Favorite Leagues: {len(fav_leagues)}\n"
        message += f"Bankroll: ${bankroll:.2f}\n\n"
        message += "Use the buttons below to configure."

        keyboard = [
            [
                InlineKeyboardButton("Add Team", callback_data="sports_setup_add_team"),
                InlineKeyboardButton("Toggle Alerts", callback_data="sports_alert_toggle"),
            ],
            [
                InlineKeyboardButton("Set Bankroll", callback_data="sports_setup_bankroll"),
                InlineKeyboardButton("View Teams", callback_data="sports_setup_view_teams"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode="HTML")
    else:
        await update.message.reply_text(
            "Usage: /sports [setup|config]",
            parse_mode="HTML"
        )


async def cmd_bets(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /bets [view|add|stats|chart|bankroll|resolve]

    Manage sports betting records.

    Subcommands:
      /bets                   — Show recent bets and P&L summary
      /bets add <text>        — Log a bet from text description
      /bets stats             — Detailed statistics
      /bets chart [type]      — Send visual chart (pnl|winrate|roi|units|distribution)
      /bets bankroll          — Show/set bankroll and unit size
      /bets resolve <id> <result> — Resolve a pending bet (won|lost|push)
    """
    if update.message.from_user.id != ALLOWED_USER_ID:
        return

    args = update.message.text.split()[1:] if len(update.message.text.split()) > 1 else []
    action = args[0].lower() if args else "view"

    if action == "view":
        # Show recent bets and summary
        await _show_recent_bets(update, context)

    elif action == "add":
        # Log bet from text
        text = " ".join(args[1:]) if len(args) > 1 else ""
        if not text:
            await update.message.reply_text(
                "Usage: /bets add <bet description>\n\n"
                "Examples:\n"
                "  bet $50 on Chiefs -3\n"
                "  FanDuel: $100 on Over 45\n"
                "  moneyline +200 Celtics",
                parse_mode="HTML"
            )
            return

        await update.message.reply_text("📝 Logging bet from text...", parse_mode="HTML")
        settings = sports_config.load_sports_settings()
        result = await betting.log_bet_from_text(text, settings)

        if result.get("success"):
            message = f"✓ {result.get('message', 'Bet logged')}\n\n"
            bet = result.get("bet", {})
            message += f"<b>{bet.get('league')}</b> | {bet.get('pick')} @ {bet.get('odds'):+d}\n"
            message += f"Stake: ${bet.get('stake'):.2f} | Result: Pending"
            await update.message.reply_text(message, parse_mode="HTML")
        else:
            await update.message.reply_text(
                f"❌ Error: {result.get('error', 'Unknown error')}",
                parse_mode="HTML"
            )

    elif action == "stats":
        # Show detailed betting statistics
        await _show_betting_stats(update, context)

    elif action == "chart":
        # Generate and send chart
        chart_type = args[1].lower() if len(args) > 1 else "pnl"
        await _send_chart(update, context, chart_type)

    elif action == "bankroll":
        # Show/set bankroll
        await _show_bankroll_settings(update, context)

    elif action == "resolve":
        # Resolve a bet
        if len(args) < 3:
            await update.message.reply_text(
                "Usage: /bets resolve <bet_id> <won|lost|push>",
                parse_mode="HTML"
            )
            return

        bet_id = args[1]
        result = args[2].lower()
        await _resolve_bet(update, context, bet_id, result)

    else:
        # Show help/menu
        await update.message.reply_text(
            "<b>📊 Sports Betting Manager</b>\n\n"
            "Available commands:\n"
            "/bets                    — Recent bets & summary\n"
            "/bets add <description>  — Log a new bet\n"
            "/bets stats              — Detailed statistics\n"
            "/bets chart [type]       — Visual charts (pnl|winrate|roi|units|distribution)\n"
            "/bets bankroll           — Manage bankroll\n"
            "/bets resolve <id> <res> — Resolve pending bet\n\n"
            "Send a screenshot of sportsbook odds for line comparison.",
            parse_mode="HTML"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# BETTING HELPERS
# ═══════════════════════════════════════════════════════════════════════════════


async def _show_recent_bets(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show recent bets and P&L summary."""
    bets = sports_data.get_bets(limit=10)

    if not bets:
        await update.message.reply_text("📊 No bets recorded yet.", parse_mode="HTML")
        return

    # Calculate quick stats
    resolved = [b for b in bets if b.get("result") != "pending"]
    wins = sum(1 for b in resolved if b.get("result") == "win")
    losses = sum(1 for b in resolved if b.get("result") == "loss")
    total_pnl = sum(float(b.get("pnl", 0)) for b in resolved)

    message = "<b>📊 Recent Bets</b>\n\n"
    for bet in bets[:5]:
        league = bet.get("league", "")
        pick = bet.get("pick", "")
        odds = bet.get("odds", 0)
        result = bet.get("result", "pending").upper()
        pnl = bet.get("pnl", 0)
        bet_id = bet.get("id", "")[:8]

        status_emoji = "✓" if result == "WIN" else "✗" if result == "LOSS" else "⏳"
        pnl_str = f"+${pnl:.2f}" if pnl > 0 else f"-${abs(pnl):.2f}" if pnl < 0 else "Push"

        message += f"{status_emoji} <b>{league}</b> | {pick} @ {odds:+d}\n"
        message += f"   Result: {result} | P&L: {pnl_str} | ID: {bet_id}\n\n"

    message += f"\n<b>Summary:</b> W {wins}-{losses} | Total P&L: ${total_pnl:+.2f}"

    keyboard = [
        [
            InlineKeyboardButton("Add Bet", callback_data="sports_bet_add_text"),
            InlineKeyboardButton("Stats", callback_data="sports_bet_stats"),
        ],
        [
            InlineKeyboardButton("Charts", callback_data="sports_bet_charts"),
            InlineKeyboardButton("Bankroll", callback_data="sports_bankroll_view"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(message, reply_markup=reply_markup, parse_mode="HTML")


async def _show_betting_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show detailed betting statistics."""
    bets = sports_data.get_bets(limit=1000)
    stats = await betting.calculate_stats(bets)

    if stats.get("total_bets", 0) == 0:
        await update.message.reply_text("📊 No bets to analyze yet.", parse_mode="HTML")
        return

    message = "<b>📊 Detailed Statistics</b>\n\n"
    message += f"<b>Overall Performance:</b>\n"
    message += f"  Total Bets: {stats.get('total_bets', 0)}\n"
    message += f"  Record: {stats.get('wins', 0)}-{stats.get('losses', 0)}-{stats.get('pushes', 0)}\n"
    message += f"  Win Rate: {stats.get('win_rate', 0):.1f}%\n"
    message += f"  Streak: {stats.get('streak', {}).get('current', 'N/A')} {stats.get('streak', {}).get('count', 0)}\n\n"

    message += f"<b>Financial:</b>\n"
    message += f"  Total Staked: ${stats.get('total_staked', 0):.2f}\n"
    message += f"  Total Returned: ${stats.get('total_returned', 0):.2f}\n"
    message += f"  Net P&L: ${stats.get('net_pnl', 0):+.2f}\n"
    message += f"  ROI: {stats.get('roi', 0):+.1f}%\n\n"

    # By league breakdown
    by_league = stats.get("by_league", {})
    if by_league:
        message += f"<b>By League:</b>\n"
        for league, data in sorted(by_league.items())[:5]:
            wr = data.get("win_rate", 0)
            roi = data.get("roi", 0)
            message += f"  {league}: {data.get('wins', 0)}-{data.get('losses', 0)} ({wr:.0f}%) | ROI: {roi:+.1f}%\n"

    await update.message.reply_text(message, parse_mode="HTML")


async def _send_chart(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chart_type: str,
) -> None:
    """Generate and send a chart."""
    bets = sports_data.get_bets(limit=1000)

    if not bets:
        await update.message.reply_text("No bets to chart.", parse_mode="HTML")
        return

    chart_map = {
        "pnl": ("Cumulative P&L Chart", charts.generate_pnl_chart),
        "winrate": ("Win Rate by League", charts.generate_win_rate_chart),
        "roi": ("ROI by Sportsbook", charts.generate_roi_chart),
        "units": ("Unit Tracker", charts.generate_unit_tracker),
        "distribution": ("Bet Distribution", charts.generate_bet_distribution),
    }

    if chart_type not in chart_map:
        await update.message.reply_text(
            f"Unknown chart type: {chart_type}\n\n"
            "Available: pnl, winrate, roi, units, distribution",
            parse_mode="HTML"
        )
        return

    title, chart_fn = chart_map[chart_type]
    await update.message.reply_text(f"📈 Generating {title}...", parse_mode="HTML")

    png_bytes = await chart_fn(bets)
    if png_bytes:
        await update.message.reply_photo(
            photo=png_bytes,
            caption=f"<b>{title}</b>",
            parse_mode="HTML"
        )
    else:
        await update.message.reply_text(
            f"Could not generate chart (may need more data)",
            parse_mode="HTML"
        )


async def _show_bankroll_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show/set bankroll and unit size."""
    settings = sports_config.load_sports_settings()
    bankroll = settings.get("bankroll", 0.0)
    unit_size = settings.get("unit_size", 0.0)

    message = "<b>💰 Bankroll Settings</b>\n\n"
    message += f"Current Bankroll: ${bankroll:.2f}\n"
    message += f"Unit Size: ${unit_size:.2f}\n"

    if bankroll > 0 and unit_size > 0:
        units = bankroll / unit_size
        message += f"Units Available: {units:.1f}\n\n"

    message += "To set bankroll:\n"
    message += "<code>/bets bankroll 1000</code> — Set bankroll to $1000\n"
    message += "<code>/bets bankroll 1000 50</code> — Set bankroll $1000, unit $50"

    await update.message.reply_text(message, parse_mode="HTML")


async def _resolve_bet(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    bet_id: str,
    result: str,
) -> None:
    """Resolve a bet."""
    if result not in ["win", "loss", "push"]:
        await update.message.reply_text(
            f"Invalid result: {result}\n\nUse: won, lost, or push",
            parse_mode="HTML"
        )
        return

    resolve_result = await betting.resolve_bet(bet_id, result)

    if resolve_result.get("success"):
        message = f"✓ {resolve_result.get('message', '')}\n\n"
        bet = resolve_result.get("bet", {})
        message += f"<b>{bet.get('league')}</b> | {bet.get('pick')} @ {bet.get('odds'):+d}\n"
        message += f"Stake: ${bet.get('stake'):.2f}"
        await update.message.reply_text(message, parse_mode="HTML")
    else:
        await update.message.reply_text(
            f"❌ Error: {resolve_result.get('error', 'Unknown error')}",
            parse_mode="HTML"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# GENERAL HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

async def _show_league_menu(update: Update, action: str) -> None:
    """Show league selection menu."""
    message = f"<b>Select League for /{action}</b>\n\nChoose a league:"

    # Create buttons for each league
    buttons = []
    for slug, info in list(sports_config.LEAGUES.items())[:6]:
        buttons.append(InlineKeyboardButton(
            f"{info['emoji']} {info['name']}",
            callback_data=f"sports_{action}_{slug}"
        ))

    keyboard = [buttons[i:i+2] for i in range(0, len(buttons), 2)]

    # Add more leagues
    more_buttons = []
    for slug, info in list(sports_config.LEAGUES.items())[6:]:
        more_buttons.append(InlineKeyboardButton(
            f"{info['emoji']} {info['name']}",
            callback_data=f"sports_{action}_{slug}"
        ))

    if more_buttons:
        keyboard.extend([more_buttons[i:i+2] for i in range(0, len(more_buttons), 2)])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(message, reply_markup=reply_markup, parse_mode="HTML")


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /stats command.

    Usage:
      /stats team nba lakers     — Lakers team stats
      /stats player lebron        — LeBron James stats
      /stats gamelog lebron       — Recent game log
      /stats roster nba lakers    — Team roster

    If just "/stats" with no args, show usage help.
    """
    if update.message.from_user.id != ALLOWED_USER_ID:
        return

    args = update.message.text.split()[1:] if len(update.message.text.split()) > 1 else []

    if not args:
        # Show help
        await update.message.reply_text(
            "<b>📊 Stats Command</b>\n\n"
            "Usage:\n"
            "<code>/stats player &lt;name&gt;</code> — Player stats\n"
            "<code>/stats gamelog &lt;name&gt;</code> — Recent game log\n"
            "<code>/stats team &lt;league&gt; &lt;name&gt;</code> — Team stats\n"
            "<code>/stats roster &lt;league&gt; &lt;name&gt;</code> — Team roster\n\n"
            "<b>Also try:</b>\n"
            "<code>/leaders &lt;league&gt;</code> — Top scorers & stat leaders\n"
            "<code>/compare Player1 vs Player2</code> — Side-by-side comparison\n\n"
            "Examples:\n"
            "  /stats player LeBron James\n"
            "  /stats team nba lakers\n"
            "  /leaders nba\n"
            "  /compare LeBron vs Durant",
            parse_mode="HTML"
        )
        return

    subcommand = args[0].lower()
    remaining = " ".join(args[1:]) if len(args) > 1 else ""

    # ─────────────────────────────────────────────────────────────────────────────
    # PLAYER STATS
    # ─────────────────────────────────────────────────────────────────────────────
    if subcommand == "player":
        if not remaining:
            await update.message.reply_text(
                "Usage: /stats player &lt;player name&gt;",
                parse_mode="HTML"
            )
            return

        await update.message.reply_text("🔍 Searching for player...", parse_mode="HTML")

        search_results = await stats_api.search_player(remaining)
        if not search_results:
            await update.message.reply_text(
                f"❌ No players found matching: <b>{remaining}</b>",
                parse_mode="HTML"
            )
            return

        # If exactly one result, show stats directly
        if len(search_results) == 1:
            player = search_results[0]
            athlete_id = player.get("id")
            league = player.get("league") or ""

            # Map ESPN league names to our league slugs, with fallback
            league_slug = _map_league_name_to_slug(league) if league else None
            if not league_slug:
                # Try to infer from sport field or default to NBA
                sport_val = (player.get("sport") or "").lower()
                if "football" in sport_val:
                    league_slug = "nfl"
                elif "baseball" in sport_val:
                    league_slug = "mlb"
                elif "hockey" in sport_val:
                    league_slug = "nhl"
                else:
                    league_slug = "nba"  # default fallback

            # Get league info for sport/league values
            league_info = sports_config.get_league_info(league_slug)
            if not league_info:
                await update.message.reply_text(
                    f"❌ Unsupported league: {league}",
                    parse_mode="HTML"
                )
                return

            player_stats = await stats_api.get_player_stats(
                athlete_id,
                league_info["sport"],
                league_info["league"],
                player_name=player.get("name", remaining),
            )

            if player_stats:
                message = formatting.format_player_stats(player_stats)
                await update.message.reply_text(message, parse_mode="HTML")
            else:
                await update.message.reply_text(
                    f"❌ Could not fetch stats for {player.get('name', remaining)}",
                    parse_mode="HTML"
                )
        else:
            # Show numbered list for user to pick
            message = formatting.format_player_search_results(search_results[:5])
            context.user_data["player_search_results"] = search_results
            context.user_data["last_action"] = "player_stats"
            await update.message.reply_text(message, parse_mode="HTML")

    # ─────────────────────────────────────────────────────────────────────────────
    # GAMELOG
    # ─────────────────────────────────────────────────────────────────────────────
    elif subcommand == "gamelog":
        if not remaining:
            await update.message.reply_text(
                "Usage: /stats gamelog &lt;player name&gt;",
                parse_mode="HTML"
            )
            return

        await update.message.reply_text("🔍 Searching for player...", parse_mode="HTML")

        search_results = await stats_api.search_player(remaining)
        if not search_results:
            await update.message.reply_text(
                f"❌ No players found matching: <b>{remaining}</b>",
                parse_mode="HTML"
            )
            return

        if len(search_results) == 1:
            player = search_results[0]
            athlete_id = player.get("id")
            league = player.get("league") or ""

            league_slug = _map_league_name_to_slug(league) if league else None
            if not league_slug:
                sport_val = (player.get("sport") or "").lower()
                if "football" in sport_val:
                    league_slug = "nfl"
                elif "baseball" in sport_val:
                    league_slug = "mlb"
                elif "hockey" in sport_val:
                    league_slug = "nhl"
                else:
                    league_slug = "nba"

            league_info = sports_config.get_league_info(league_slug)
            if not league_info:
                await update.message.reply_text(
                    f"❌ Unsupported league: {league}",
                    parse_mode="HTML"
                )
                return

            gamelog = await stats_api.get_player_gamelog(
                athlete_id,
                league_info["sport"],
                league_info["league"],
                player_name=player.get("name", remaining),
            )

            if gamelog:
                message = formatting.format_player_gamelog(gamelog, limit=5)
                await update.message.reply_text(message, parse_mode="HTML")
            else:
                await update.message.reply_text(
                    f"❌ Could not fetch game log",
                    parse_mode="HTML"
                )
        else:
            message = formatting.format_player_search_results(search_results[:5])
            context.user_data["player_search_results"] = search_results
            context.user_data["last_action"] = "gamelog"
            await update.message.reply_text(message, parse_mode="HTML")

    # ─────────────────────────────────────────────────────────────────────────────
    # TEAM STATS
    # ─────────────────────────────────────────────────────────────────────────────
    elif subcommand == "team":
        if len(args) < 2:
            await update.message.reply_text(
                "Usage: /stats team &lt;league&gt; &lt;team name&gt;",
                parse_mode="HTML"
            )
            return

        league_input = args[1].lower()
        team_name = " ".join(args[2:]) if len(args) > 2 else ""

        if not team_name:
            await update.message.reply_text(
                "Usage: /stats team &lt;league&gt; &lt;team name&gt;",
                parse_mode="HTML"
            )
            return

        # Normalize league
        league_slug = sports_config.normalize_league(league_input)
        if not league_slug:
            await update.message.reply_text(
                f"❌ Unknown league: <b>{league_input}</b>",
                parse_mode="HTML"
            )
            return

        await update.message.reply_text(f"🔍 Searching for {team_name}...", parse_mode="HTML")

        team_results = await stats_api.search_team(team_name, league_slug)
        if not team_results:
            await update.message.reply_text(
                f"❌ No teams found matching: <b>{team_name}</b> in <b>{league_slug.upper()}</b>",
                parse_mode="HTML"
            )
            return

        if len(team_results) == 1:
            team = team_results[0]
            team_id = team.get("id")
            league_info = sports_config.get_league_info(league_slug)

            team_stats = await stats_api.get_team_stats(
                team_id,
                league_info["sport"],
                league_info["league"]
            )

            if team_stats:
                message = formatting.format_team_stats(team_stats)
                await update.message.reply_text(message, parse_mode="HTML")
            else:
                await update.message.reply_text(
                    f"❌ Could not fetch stats for {team.get('name', team_name)}",
                    parse_mode="HTML"
                )
        else:
            # Show list
            lines = ["<b>🔍 Team Search Results</b>", ""]
            for idx, team in enumerate(team_results[:5], 1):
                name = team.get("name", "Unknown")
                abbrev = team.get("abbreviation", "")
                lines.append(f"<code>{idx}. {name}</code>")
                if abbrev:
                    lines.append(f"   <i>{abbrev}</i>")
            lines.append("")
            lines.append("<i>Reply with the number to select a team</i>")

            message = "\n".join(lines)
            context.user_data["team_search_results"] = team_results
            context.user_data["team_league"] = league_slug
            context.user_data["last_action"] = "team_stats"
            await update.message.reply_text(message, parse_mode="HTML")

    # ─────────────────────────────────────────────────────────────────────────────
    # TEAM ROSTER
    # ─────────────────────────────────────────────────────────────────────────────
    elif subcommand == "roster":
        if len(args) < 2:
            await update.message.reply_text(
                "Usage: /stats roster &lt;league&gt; &lt;team name&gt;",
                parse_mode="HTML"
            )
            return

        league_input = args[1].lower()
        team_name = " ".join(args[2:]) if len(args) > 2 else ""

        if not team_name:
            await update.message.reply_text(
                "Usage: /stats roster &lt;league&gt; &lt;team name&gt;",
                parse_mode="HTML"
            )
            return

        league_slug = sports_config.normalize_league(league_input)
        if not league_slug:
            await update.message.reply_text(
                f"❌ Unknown league: <b>{league_input}</b>",
                parse_mode="HTML"
            )
            return

        await update.message.reply_text(f"🔍 Searching for {team_name}...", parse_mode="HTML")

        team_results = await stats_api.search_team(team_name, league_slug)
        if not team_results:
            await update.message.reply_text(
                f"❌ No teams found matching: <b>{team_name}</b>",
                parse_mode="HTML"
            )
            return

        if len(team_results) == 1:
            team = team_results[0]
            team_id = team.get("id")
            league_info = sports_config.get_league_info(league_slug)

            roster = await stats_api.get_team_roster(
                team_id,
                league_info["sport"],
                league_info["league"]
            )

            if roster and roster.get("players"):
                players = roster.get("players", [])
                team_name_str = roster.get("team_name", team.get("name", "Team"))

                lines = [f"<b>📋 {team_name_str} Roster</b>", ""]

                for player in players[:20]:  # Limit to 20 for readability
                    name = player.get("name", "")
                    position = player.get("position", "")
                    jersey = player.get("jersey", "")

                    if name:
                        pos_jersey = []
                        if position:
                            pos_jersey.append(position)
                        if jersey:
                            pos_jersey.append(f"#{jersey}")

                        info_str = f" | {' | '.join(pos_jersey)}" if pos_jersey else ""
                        lines.append(f"<code>{name:25}{info_str}</code>")

                lines.append("")
                lines.append(f"<i>Showing {min(20, len(players))} of {len(players)} players</i>")

                message = "\n".join(lines)
                await update.message.reply_text(message, parse_mode="HTML")
            else:
                await update.message.reply_text(
                    f"❌ Could not fetch roster",
                    parse_mode="HTML"
                )
        else:
            # Show list
            lines = ["<b>🔍 Team Search Results</b>", ""]
            for idx, team in enumerate(team_results[:5], 1):
                name = team.get("name", "Unknown")
                abbrev = team.get("abbreviation", "")
                lines.append(f"<code>{idx}. {name}</code>")
                if abbrev:
                    lines.append(f"   <i>{abbrev}</i>")
            lines.append("")
            lines.append("<i>Reply with the number to select a team</i>")

            message = "\n".join(lines)
            context.user_data["team_search_results"] = team_results
            context.user_data["team_league"] = league_slug
            context.user_data["last_action"] = "roster"
            await update.message.reply_text(message, parse_mode="HTML")

    else:
        await update.message.reply_text(
            f"❌ Unknown subcommand: <b>{subcommand}</b>\n\n"
            "Use: /stats [player|gamelog|team|roster] ...",
            parse_mode="HTML"
        )


async def cmd_leaders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /leaders [league]

    View league leaders (top scorers, stat leaders).
    Soccer: top scorers + assists from API-Sports.
    NBA/NFL/MLB/NHL: stat leaders from ESPN.
    """
    if update.message.from_user.id != ALLOWED_USER_ID:
        return

    args = update.message.text.split()[1:] if len(update.message.text.split()) > 1 else []

    if not args:
        await _show_league_menu(update, "leaders")
        return

    league_input = args[0].lower()
    league_slug = sports_config.normalize_league(league_input)

    if not league_slug:
        await update.message.reply_text(
            f"❌ Unknown league: <b>{league_input}</b>",
            parse_mode="HTML"
        )
        return

    league_info = sports_config.get_league_info(league_slug)
    emoji = league_info.get("emoji", "🏆")

    await update.message.reply_text(f"🔍 Fetching {league_info['name']} leaders...", parse_mode="HTML")

    leaders = await stats_api.get_league_leaders(league_slug)
    if not leaders:
        await update.message.reply_text(
            formatting.format_error("Could not fetch league leaders", league_info["name"]),
            parse_mode="HTML"
        )
        return

    message = formatting.format_leaders(leaders, emoji)
    await update.message.reply_text(message, parse_mode="HTML")


async def cmd_compare(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /compare [player1] vs [player2]

    Compare two players' stats side by side.
    """
    if update.message.from_user.id != ALLOWED_USER_ID:
        return

    args = update.message.text.split(maxsplit=1)
    if len(args) < 2:
        await update.message.reply_text(
            "<b>⚔️ Player Comparison</b>\n\n"
            "Usage: <code>/compare player1 vs player2</code>\n\n"
            "Examples:\n"
            "  /compare LeBron James vs Kevin Durant\n"
            "  /compare Messi vs Ronaldo\n"
            "  /compare Mahomes vs Allen",
            parse_mode="HTML"
        )
        return

    raw_query = args[1]

    # Split on " vs " or " versus " or " v "
    import re
    parts = re.split(r'\s+(?:vs\.?|versus|v)\s+', raw_query, maxsplit=1, flags=re.I)

    if len(parts) != 2:
        await update.message.reply_text(
            "❌ Please use 'vs' to separate two player names.\n\n"
            "Example: <code>/compare LeBron James vs Kevin Durant</code>",
            parse_mode="HTML"
        )
        return

    name1 = parts[0].strip()
    name2 = parts[1].strip()

    if not name1 or not name2:
        await update.message.reply_text(
            "❌ Both player names are required.\n\n"
            "Example: <code>/compare LeBron James vs Kevin Durant</code>",
            parse_mode="HTML"
        )
        return

    await update.message.reply_text(
        f"🔍 Comparing {name1} vs {name2}...",
        parse_mode="HTML"
    )

    # Search both players in parallel
    import asyncio
    results = await asyncio.gather(
        stats_api.search_player(name1),
        stats_api.search_player(name2),
        return_exceptions=True,
    )

    search1 = results[0] if not isinstance(results[0], Exception) else None
    search2 = results[1] if not isinstance(results[1], Exception) else None

    if not search1:
        await update.message.reply_text(
            f"❌ Could not find player: <b>{name1}</b>",
            parse_mode="HTML"
        )
        return

    if not search2:
        await update.message.reply_text(
            f"❌ Could not find player: <b>{name2}</b>",
            parse_mode="HTML"
        )
        return

    player1 = search1[0]
    player2 = search2[0]

    # Get league info for both players
    def _resolve_league(player):
        league_raw = player.get("league") or ""
        slug = _map_league_name_to_slug(league_raw) if league_raw else None
        if not slug:
            sport_val = (player.get("sport") or "").lower()
            if "football" in sport_val:
                slug = "nfl"
            elif "baseball" in sport_val:
                slug = "mlb"
            elif "hockey" in sport_val:
                slug = "nhl"
            else:
                slug = "nba"
        return slug

    slug1 = _resolve_league(player1)
    slug2 = _resolve_league(player2)

    info1 = sports_config.get_league_info(slug1)
    info2 = sports_config.get_league_info(slug2)

    if not info1 or not info2:
        await update.message.reply_text(
            "❌ Could not determine league for one or both players.",
            parse_mode="HTML"
        )
        return

    # Fetch stats for both players in parallel
    import asyncio
    stat_results = await asyncio.gather(
        stats_api.get_player_stats(
            player1.get("id"), info1["sport"], info1["league"],
            player_name=player1.get("name", name1),
        ),
        stats_api.get_player_stats(
            player2.get("id"), info2["sport"], info2["league"],
            player_name=player2.get("name", name2),
        ),
        return_exceptions=True,
    )

    stats1 = stat_results[0] if not isinstance(stat_results[0], Exception) else None
    stats2 = stat_results[1] if not isinstance(stat_results[1], Exception) else None

    if not stats1:
        await update.message.reply_text(
            f"❌ Could not fetch stats for {player1.get('name', name1)}",
            parse_mode="HTML"
        )
        return

    if not stats2:
        await update.message.reply_text(
            f"❌ Could not fetch stats for {player2.get('name', name2)}",
            parse_mode="HTML"
        )
        return

    message = formatting.format_player_comparison(stats1, stats2)
    await update.message.reply_text(message, parse_mode="HTML")


# ═══════════════════════════════════════════════════════════════════════════════
# STATS COMMAND HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _map_league_name_to_slug(league_name: str) -> Optional[str]:
    """
    Map ESPN league names to our internal league slugs.

    ESPN league names: "NBA", "NFL", "Major League Baseball", etc.
    """
    league_lower = league_name.lower().strip()

    # Direct mappings
    mappings = {
        "nba": "nba",
        "nfl": "nfl",
        "mlb": "mlb",
        "major league baseball": "mlb",
        "nhl": "nhl",
        "ncaaf": "ncaaf",
        "college football": "ncaaf",
        "ncaab": "ncaab",
        "college basketball": "ncaab",
        "mens college basketball": "ncaab",
        "epl": "epl",
        "premier league": "epl",
        "english premier league": "epl",
        "mls": "mls",
        "bundesliga": "bundesliga",
        "laliga": "laliga",
        "la liga": "laliga",
    }

    return mappings.get(league_lower)

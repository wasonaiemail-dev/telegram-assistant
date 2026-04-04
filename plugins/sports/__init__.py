"""
Sports Pack — Live scores, standings, schedules, and betting tracker for Alfred.

Supported leagues:
  • NFL (football/nfl)
  • NBA (basketball/nba)
  • MLB (baseball/mlb)
  • NHL (hockey/nhl)
  • NCAAF (football/college-football)
  • NCAAB (basketball/mens-college-basketball)
  • EPL (soccer/eng.1)
  • MLS (soccer/usa.1)
  • Bundesliga (soccer/ger.1)
  • La Liga (soccer/esp.1)

Commands:
  /scores [league] [team]      — Get latest scores
  /standings [league]          — View league standings
  /schedule [league] [team]    — View upcoming games
  /sports [setup|config]       — Configure favorite teams and alerts
  /bets [view|add|stats]       — Manage sports betting records
  /stats [player|team|gamelog|roster] — Player and team statistics

Intents:
  sports_scores, sports_standings, sports_schedule, sports_setup,
  sports_alert_toggle, sports_bet_add, sports_bet_view, sports_bet_compare,
  sports_bet_calculate, sports_player_stats, sports_player_gamelog,
  sports_team_stats, sports_roster
"""

PLUGIN_META = {
    "name": "Sports Pack",
    "version": "1.0.0",
    "description": "Live scores, standings, schedules, and betting tracker",
    "author": "Alfred",

    # ── Telegram /commands ──────────────────────────────────────
    "commands": [
        {
            "command": "scores",
            "handler": "plugins.sports.commands.cmd_scores",
            "description": "Live scores and results",
        },
        {
            "command": "standings",
            "handler": "plugins.sports.commands.cmd_standings",
            "description": "League standings and rankings",
        },
        {
            "command": "schedule",
            "handler": "plugins.sports.commands.cmd_schedule",
            "description": "Upcoming games and schedule",
        },
        {
            "command": "sports",
            "handler": "plugins.sports.commands.cmd_sports",
            "description": "Setup favorite teams and alerts",
        },
        {
            "command": "bets",
            "handler": "plugins.sports.commands.cmd_bets",
            "description": "Manage sports betting records",
        },
        {
            "command": "stats",
            "handler": "plugins.sports.commands.cmd_stats",
            "description": "Player and team statistics",
        },
    ],

    # ── Intent routing ──────────────────────────────────────────
    "intents": [
        "sports_scores",
        "sports_standings",
        "sports_schedule",
        "sports_setup",
        "sports_alert_toggle",
        "sports_bet_add",
        "sports_bet_view",
        "sports_bet_compare",
        "sports_bet_calculate",
        "sports_player_stats",
        "sports_player_gamelog",
        "sports_team_stats",
        "sports_roster",
    ],
    "intent_handler": "plugins.sports.dispatch.handle_sports_intent",

    # ── Layer 1 keyword rules ───────────────────────────────────
    "keyword_rules_fn": "plugins.sports.keywords.build_rules",

    # ── Layer 2 GPT intent definitions ──────────────────────────
    "gpt_intent_block": """
sports_scores       Get live scores for a league or team
sports_standings    View standings, rankings, or league table
sports_schedule     Check upcoming games, schedule, or "who's playing"
sports_setup        Configure favorite teams, toggle alerts, set bankroll
sports_alert_toggle Enable or disable game day alerts
sports_bet_add      Log a sports bet with odds, stake, and pick
sports_bet_view     View recent bets or bet history
sports_bet_compare  Compare ROI across leagues or teams
sports_bet_calculate Calculate parlay, unit sizing, or expected value
sports_player_stats  Get player stats, averages, or season numbers by name
sports_player_gamelog View a player's recent game log or performance history
sports_team_stats    Get team-level statistics and record
sports_roster        View a team's current roster
""",

    # ── Background jobs ────────────────────────────────────────
    "jobs": [
        {
            "type": "repeating",
            "handler": "plugins.sports.jobs.job_score_updates",
            "interval": 1800,  # Every 30 minutes during game days
            "name": "sports_score_updates",
        },
        {
            "type": "daily",
            "handler": "plugins.sports.jobs.job_game_alerts",
            "hour": 9,
            "minute": 0,
            "name": "sports_game_alerts",
        },
    ],

    # ── Callback query patterns ────────────────────────────────
    "callbacks": [
        {
            "pattern": "^sports_",
            "handler": "plugins.sports.callbacks.handle_sports_callback",
        },
    ],
}

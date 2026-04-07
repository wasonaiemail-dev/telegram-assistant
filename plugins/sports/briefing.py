"""
Sports morning briefing section builder.

Generates a compact daily sports recap for the morning briefing:
  • Yesterday's results for the buyer's favorite leagues
  • Top 3 performers per game (composite: PTS + REB×0.5 + AST×0.5)
  • Favorite team games highlighted with a ⭐ callout
  • Optional: top Reddit highlight posts (Highlight-flair, free, rate-limited)
  • Optional: YouTube top plays deep-link (API key or search URL fallback)

Called by features/briefing.py as _SECTION_BUILDERS["sports"].

SETTINGS (stored in /data/sports_plugin/settings.json via config.py):
  briefing_reddit_highlights   bool  default True   — fetch Reddit highlights
  briefing_youtube_top_plays   bool  default False  — include YouTube top plays link
  briefing_track_fav_players   bool  default False  — track favorite player stat lines
  briefing_favorite_players    list  default []     — player display names to track

API QUOTA NOTES (shown to buyer in /sports → Briefing Settings):
  • ESPN scoreboard + box score = ~2 calls per league (free, no key, no limit)
  • Reddit r/<sub>/top.json = 1 call per subreddit (free; ~60 req/min limit)
  • API-Sports player tracking = ~3-5 calls per player/day (100/day free tier)
  • YouTube Data API = 1-2 calls per league (requires YOUTUBE_API_KEY env var)
    Without the key: a YouTube search URL is generated instead (no API cost).
"""

import asyncio
import aiohttp
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

from plugins.sports.config import LEAGUES, load_sports_settings

logger = logging.getLogger(__name__)

# ── ESPN endpoints ────────────────────────────────────────────────────────────

ESPN_SCOREBOARD_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard"
)
ESPN_SUMMARY_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/summary"
)

# ── Reddit ────────────────────────────────────────────────────────────────────

REDDIT_TOP_URL = "https://www.reddit.com/r/{sub}/top.json"
REDDIT_HEADERS = {"User-Agent": "alfred-bot/1.0 (personal morning briefing)"}
# Reddit requires a User-Agent header to avoid 429 rate-limit responses.

# League → subreddit
LEAGUE_SUBREDDITS: Dict[str, str] = {
    "nba":        "nba",
    "nfl":        "nfl",
    "mlb":        "baseball",
    "nhl":        "hockey",
    "ncaaf":      "CFB",
    "ncaab":      "CollegeBasketball",
    "epl":        "PremierLeague",
    "mls":        "MLS",
    "bundesliga": "Bundesliga",
    "laliga":     "LaLiga",
}

# ── YouTube ───────────────────────────────────────────────────────────────────

YOUTUBE_SEARCH_URL = "https://www.youtube.com/results?search_query={q}"
YOUTUBE_API_URL    = "https://www.googleapis.com/youtube/v3/search"

# League → official channel info + fallback search query
LEAGUE_YT_INFO: Dict[str, Dict[str, str]] = {
    "nba":  {"channel": "UCWJ2lWNubArHWmf3FIHbfcQ", "query": "NBA Top 10 Plays"},
    "nfl":  {"channel": "UCDVYQ4Zhbm3S2dlz7P1GBDg", "query": "NFL Top 10 Plays"},
    "mlb":  {"channel": "UCzWQYUVCpZqtN93H8RR44Qw", "query": "MLB Top 10 Plays"},
    "nhl":  {"channel": "UCqFMzb-4AUf6WAIbl132QKA", "query": "NHL Top 10 Plays"},
    "epl":  {"channel": "UCqZQlzSHbVJrwrn5XvzrzcA", "query": "Premier League Top 10 Goals"},
}

# ── ESPN box score stat indices ───────────────────────────────────────────────
# Confirmed via live test: labels = ["MIN","PTS","FG","3PT","FT","REB","AST","TO","STL","BLK"]
_DEFAULT_LABELS = ["MIN", "PTS", "FG", "3PT", "FT", "REB", "AST", "TO", "STL", "BLK"]
_DEFAULT_PTS = 1
_DEFAULT_REB = 5
_DEFAULT_AST = 6
_DEFAULT_STL = 8
_DEFAULT_BLK = 9
_DEFAULT_FG  = 2

# HTTP timeout
_TIMEOUT = aiohttp.ClientTimeout(total=10)


# ═══════════════════════════════════════════════════════════════════════════════
# LOW-LEVEL HTTP
# ═══════════════════════════════════════════════════════════════════════════════

async def _fetch_json(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, str]] = None,
) -> Optional[Dict[str, Any]]:
    """Fetch URL and return parsed JSON. Returns None on any failure."""
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 200:
                    return await resp.json(content_type=None)
                logger.warning(f"HTTP {resp.status}: {url}")
    except asyncio.TimeoutError:
        logger.warning(f"Timeout fetching: {url}")
    except Exception as e:
        logger.error(f"Fetch error {url}: {e}")
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# ESPN BOX SCORE
# ═══════════════════════════════════════════════════════════════════════════════

async def _fetch_box_score(
    event_id: str, sport: str, league_code: str
) -> Optional[Dict[str, Any]]:
    """Fetch ESPN game summary (box score) for a specific event ID."""
    url = ESPN_SUMMARY_URL.format(sport=sport, league=league_code)
    return await _fetch_json(url, params={"event": event_id})


def _composite_score(stat_vals: List[str], pts_i: int, reb_i: int, ast_i: int) -> float:
    """
    Compute composite fantasy score: PTS + REB×0.5 + AST×0.5.
    Handles FG-style values like "12-22" (takes first number).
    """
    def _safe(i: int) -> float:
        try:
            v = stat_vals[i]
            if isinstance(v, str) and "-" in v and not v.startswith("-"):
                v = v.split("-")[0]
            return float(v) if v and str(v) not in ("-", "") else 0.0
        except (IndexError, ValueError, TypeError):
            return 0.0

    return _safe(pts_i) + _safe(reb_i) * 0.5 + _safe(ast_i) * 0.5


def _parse_top_players(
    box_score_data: Dict[str, Any], n: int = 3
) -> List[Dict[str, str]]:
    """
    Extract top N players from an ESPN summary API response.

    Returns list of dicts:
        name, team, pts, reb, ast, stl, blk, fg,
        tpt_made (int), tpt_att (int), score (float)
    Sorted by composite score descending.
    """
    players = []

    try:
        for team_section in box_score_data.get("boxscore", {}).get("players", []):
            team_name = team_section.get("team", {}).get("abbreviation", "") or \
                        team_section.get("team", {}).get("displayName", "")
            stats_sections = team_section.get("statistics", [])
            if not stats_sections:
                continue

            stat_section = stats_sections[0]
            labels = [lbl.upper() for lbl in stat_section.get("labels", _DEFAULT_LABELS)]

            # Build label → index map (ESPN order can vary)
            lbl_idx = {lbl: i for i, lbl in enumerate(labels)}
            pts_i  = lbl_idx.get("PTS", _DEFAULT_PTS)
            reb_i  = lbl_idx.get("REB", _DEFAULT_REB)
            ast_i  = lbl_idx.get("AST", _DEFAULT_AST)
            stl_i  = lbl_idx.get("STL", _DEFAULT_STL)
            blk_i  = lbl_idx.get("BLK", _DEFAULT_BLK)
            fg_i   = lbl_idx.get("FG",  _DEFAULT_FG)
            # "3PT" label varies — try both ESPN variants
            tpt_i  = lbl_idx.get("3PT", lbl_idx.get("3P", lbl_idx.get("3FG", 3)))

            for athlete_entry in stat_section.get("athletes", []):
                athlete    = athlete_entry.get("athlete", {})
                name       = athlete.get("displayName", "Unknown")
                stat_vals  = athlete_entry.get("stats", [])

                if not stat_vals:
                    continue  # DNP or no stats available

                def _v(i: int) -> str:
                    try:
                        val = stat_vals[i]
                        return str(val) if val not in (None, "") else "-"
                    except IndexError:
                        return "-"

                def _made_att(i: int):
                    """
                    Parse a 'made-attempted' stat like '5-12'.
                    Returns (made: int, attempted: int).
                    """
                    try:
                        raw = stat_vals[i]
                        if isinstance(raw, str) and "-" in raw and not raw.startswith("-"):
                            parts = raw.split("-")
                            return int(parts[0]), int(parts[1])
                        val = int(float(raw)) if raw and str(raw) not in ("-", "") else 0
                        return val, val
                    except (IndexError, ValueError, TypeError):
                        return 0, 0

                tpt_made, tpt_att = _made_att(tpt_i)
                composite = _composite_score(stat_vals, pts_i, reb_i, ast_i)
                players.append({
                    "name":     name,
                    "team":     team_name,
                    "pts":      _v(pts_i),
                    "reb":      _v(reb_i),
                    "ast":      _v(ast_i),
                    "stl":      _v(stl_i),
                    "blk":      _v(blk_i),
                    "fg":       _v(fg_i),
                    "tpt_made": tpt_made,   # threes made (int)
                    "tpt_att":  tpt_att,    # threes attempted (int)
                    "score":    composite,
                })
    except Exception as e:
        logger.error(f"Box score parse error: {e}")

    players.sort(key=lambda p: p["score"], reverse=True)
    return players[:n]


# ═══════════════════════════════════════════════════════════════════════════════
# REDDIT HIGHLIGHTS
# ═══════════════════════════════════════════════════════════════════════════════

async def _fetch_reddit_highlights(
    subreddit: str, limit: int = 15
) -> List[Dict[str, Any]]:
    """
    Fetch top Reddit posts from the past 24 hours, filtered to video highlights.

    Accepts posts where:
      - link_flair_text contains "highlight" (case-insensitive)
      - OR is_video = True
      - OR domain is a known video host (streamable.com, v.redd.it, youtu.be, etc.)

    Returns top 5 by score: [{"title": str, "url": str, "score": int}]
    """
    url  = REDDIT_TOP_URL.format(sub=subreddit)
    data = await _fetch_json(
        url,
        headers=REDDIT_HEADERS,
        params={"t": "day", "limit": str(limit)},
    )
    if not data:
        return []

    VIDEO_DOMAINS = {
        "streamable.com", "v.redd.it", "youtu.be", "youtube.com",
        "twitter.com", "x.com", "instagram.com", "clips.twitch.tv",
    }

    highlights = []
    try:
        for child in data.get("data", {}).get("children", []):
            post    = child.get("data", {})
            flair   = (post.get("link_flair_text") or "").lower()
            title   = post.get("title", "")
            domain  = post.get("domain", "")
            score   = post.get("score", 0)
            plink   = post.get("permalink", "")
            url_out = f"https://reddit.com{plink}" if plink else ""

            if not url_out:
                continue

            is_highlight = "highlight" in flair
            is_video     = post.get("is_video", False)
            has_vid_host = domain in VIDEO_DOMAINS

            if is_highlight or is_video or has_vid_host:
                highlights.append({"title": title, "url": url_out, "score": score})
    except Exception as e:
        logger.error(f"Reddit parse error (r/{subreddit}): {e}")

    highlights.sort(key=lambda h: h["score"], reverse=True)
    return highlights[:5]


# ═══════════════════════════════════════════════════════════════════════════════
# YOUTUBE TOP PLAYS
# ═══════════════════════════════════════════════════════════════════════════════

async def _get_youtube_url(league_slug: str, date: datetime) -> Optional[str]:
    """
    Return a YouTube URL for the league's top plays from the given date.

    With YOUTUBE_API_KEY: queries official channel, returns direct video link.
    Without key: returns a YouTube search URL (no API cost, always works).
    """
    yt = LEAGUE_YT_INFO.get(league_slug.lower())
    if not yt:
        # No official channel mapped — still return search URL
        league_info = LEAGUES.get(league_slug.lower(), {})
        league_name = league_info.get("name", league_slug.upper())
        query = f"{league_name} top plays {date.strftime('%B %-d %Y')}"
        return YOUTUBE_SEARCH_URL.format(q=quote_plus(query))

    api_key = os.environ.get("YOUTUBE_API_KEY")
    date_str = date.strftime("%B %-d, %Y")

    if api_key:
        published_after = date.replace(
            hour=0, minute=0, second=0, microsecond=0
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        data = await _fetch_json(
            YOUTUBE_API_URL,
            params={
                "part":           "snippet",
                "channelId":      yt["channel"],
                "q":              yt["query"],
                "type":           "video",
                "order":          "viewCount",
                "publishedAfter": published_after,
                "maxResults":     "1",
                "key":            api_key,
            },
        )
        if data:
            items = data.get("items", [])
            if items:
                video_id = items[0].get("id", {}).get("videoId")
                if video_id:
                    return f"https://youtu.be/{video_id}"

    # Fallback: YouTube search URL (always works, no key needed)
    query = f"{yt['query']} {date_str}"
    return YOUTUBE_SEARCH_URL.format(q=quote_plus(query))


# ═══════════════════════════════════════════════════════════════════════════════
# FORMATTING
# ═══════════════════════════════════════════════════════════════════════════════

def _fmt_player_line(player: Dict[str, str]) -> str:
    """
    Format a single player stat line for the briefing.

    Core stats always shown: pts, reb, ast.
    Bonus stats shown only when they clear a "notable" threshold:
      3PT  ≥ 3 made     (e.g. "5 3PT")
      STL  ≥ 2           (e.g. "3 STL")
      BLK  ≥ 2           (e.g. "4 BLK")
    This keeps lines tight — no padding with 1-steal noise.
    """
    name = player.get("name", "Unknown")
    team = player.get("team", "?")[:3]
    pts  = player.get("pts", "-")
    reb  = player.get("reb", "-")
    ast  = player.get("ast", "-")

    tpt_made = player.get("tpt_made", 0)
    tpt_att  = player.get("tpt_att",  0)

    extras = []

    # 3PT: show "X/Y 3PT" if ≥4 attempts, ≥35% efficiency, and ≥2 made.
    # Filters out small-sample noise (1/2 = 50% but not meaningful)
    # while catching both hot nights (6/12) and efficient shooters (3/7).
    if tpt_att >= 4 and tpt_made >= 2:
        pct = tpt_made / tpt_att
        if pct >= 0.35:
            extras.append(f"{tpt_made}/{tpt_att} 3PT")

    # STL / BLK: threshold ≥ 2 (1 is routine, 2+ is a standout defensive night)
    for stat_key, label, threshold in (("stl", "STL", 2), ("blk", "BLK", 2)):
        try:
            v = player.get(stat_key, "-")
            if v not in ("-", "") and float(v) >= threshold:
                extras.append(f"{int(float(v))} {label}")
        except (ValueError, TypeError):
            pass

    stat_str = f"{pts}pts · {reb}reb · {ast}ast"
    if extras:
        stat_str += " · " + " · ".join(extras)

    return f"  <code>{name} ({team}): {stat_str}</code>"


def _fmt_game_recap(
    game: Dict[str, Any],
    top_players: List[Dict[str, str]],
    is_favorite: bool = False,
) -> str:
    """Format a single game result with top player lines."""
    away        = game.get("away_team", "Away")
    home        = game.get("home_team", "Home")
    away_score  = game.get("away_score", "")
    home_score  = game.get("home_score", "")
    fav_prefix  = "⭐ " if is_favorite else ""

    if away_score and home_score:
        score_line = f"{fav_prefix}<b>{away} {away_score} — {home_score} {home}</b>"
    else:
        score_line = f"{fav_prefix}<b>{away} @ {home}</b>"

    lines = [score_line]
    for player in top_players:
        lines.append(_fmt_player_line(player))

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN SECTION BUILDER
# ═══════════════════════════════════════════════════════════════════════════════

async def section_sports_briefing(_now) -> str:
    """
    Morning briefing section: sports recap.

    Hooked into features/briefing.py as _SECTION_BUILDERS["sports"].
    Returns formatted Telegram HTML string or "" if nothing to show.
    """
    # ── Load settings ──────────────────────────────────────────────────────
    try:
        settings = load_sports_settings()
    except Exception as e:
        logger.error(f"Sports briefing: settings load failed: {e}")
        return ""

    favorite_teams   = settings.get("favorite_teams", [])    # [{league, team_id, team_name}]
    favorite_leagues = settings.get("favorite_leagues", [])  # [league_slug, ...]
    reddit_enabled   = settings.get("briefing_reddit_highlights", True)
    youtube_enabled  = settings.get("briefing_youtube_top_plays", False)

    # Derive league list from favorites (explicit leagues + leagues from fav teams)
    leagues_to_show = list(favorite_leagues)
    for ft in favorite_teams:
        league = ft.get("league", "").lower()
        if league and league not in leagues_to_show:
            leagues_to_show.append(league)

    if not leagues_to_show:
        # No favorite teams/leagues set — skip silently (buyer hasn't configured sports)
        return ""

    # Quick-lookup set of favorite team names for ⭐ highlighting
    fav_team_names = {
        ft.get("team_name", "").lower()
        for ft in favorite_teams
        if ft.get("team_name")
    }

    # ── Date setup ─────────────────────────────────────────────────────────
    yesterday     = datetime.now(timezone.utc) - timedelta(days=1)
    yesterday_str = yesterday.strftime("%Y%m%d")
    date_label    = yesterday.strftime("%A, %b %-d")  # e.g. "Sunday, Apr 5"

    section_lines = [f"🏆 <b>Sports Recap — {date_label}</b>"]
    had_any_game  = False

    # ── Per-league: fetch scoreboard + box scores ──────────────────────────
    for league_slug in leagues_to_show:
        league_info = LEAGUES.get(league_slug.lower())
        if not league_info:
            continue

        sport       = league_info["sport"]
        league_code = league_info["league"]
        league_name = league_info["name"]
        emoji       = league_info["emoji"]

        # 1. Fetch yesterday's scoreboard
        sb_url  = ESPN_SCOREBOARD_URL.format(sport=sport, league=league_code)
        sb_data = await _fetch_json(sb_url, params={"dates": yesterday_str})
        events  = sb_data.get("events", []) if sb_data else []

        if not events:
            continue

        # 2. Fetch box scores concurrently for all games in this league
        event_ids = [e.get("id") for e in events if e.get("id")]
        bs_tasks  = [
            asyncio.create_task(_fetch_box_score(eid, sport, league_code))
            for eid in event_ids
        ]
        bs_results = await asyncio.gather(*bs_tasks, return_exceptions=True)

        # Map event_id → box score
        box_score_map: Dict[str, Optional[Dict]] = {}
        for eid, result in zip(event_ids, bs_results):
            box_score_map[eid] = result if isinstance(result, dict) else None

        # 3. Format each completed game
        league_lines = [f"\n{emoji} <b>{league_name}</b>"]

        for event in events:
            try:
                # Parse game data from scoreboard
                comps = event.get("competitions", [{}])[0].get("competitors", [])
                if len(comps) < 2:
                    continue

                away_comp  = comps[1]
                home_comp  = comps[0]
                raw_status = event.get("status", {}).get("type", {}).get("name", "")

                # Skip games that haven't finished
                if "SCHEDULED" in raw_status.upper() or "IN_PROGRESS" in raw_status.upper():
                    continue

                game = {
                    "id":          event.get("id"),
                    "home_team":   home_comp.get("team", {}).get("displayName", "Unknown"),
                    "home_score":  home_comp.get("score", ""),
                    "away_team":   away_comp.get("team", {}).get("displayName", "Unknown"),
                    "away_score":  away_comp.get("score", ""),
                }

                # Check if a favorite team played in this game
                is_fav = (
                    game["home_team"].lower() in fav_team_names
                    or game["away_team"].lower() in fav_team_names
                )

                # Extract top 3 players from box score
                top_players: List[Dict[str, str]] = []
                bs = box_score_map.get(event.get("id"))
                if bs:
                    top_players = _parse_top_players(bs, n=3)

                league_lines.append(_fmt_game_recap(game, top_players, is_favorite=is_fav))
                had_any_game = True

            except Exception as e:
                logger.debug(f"Game parse error: {e}")
                continue

        if len(league_lines) > 1:  # More than just the league header
            section_lines.extend(league_lines)

    if not had_any_game:
        return ""  # No completed games — nothing useful to show

    # ── Reddit Highlights (opt-in, default ON) ─────────────────────────────
    if reddit_enabled:
        reddit_lines = ["\n🎬 <b>Top Highlights</b>"]
        any_highlights = False

        for league_slug in leagues_to_show:
            sub = LEAGUE_SUBREDDITS.get(league_slug.lower())
            if not sub:
                continue

            league_info = LEAGUES.get(league_slug.lower(), {})
            emoji_r     = league_info.get("emoji", "🏆")
            name_r      = league_info.get("name", league_slug.upper())

            posts = await _fetch_reddit_highlights(sub, limit=15)
            if not posts:
                continue

            reddit_lines.append(f"\n{emoji_r} {name_r}")
            for post in posts[:3]:
                title = post["title"]
                if len(title) > 80:
                    title = title[:77] + "…"
                reddit_lines.append(f'  • <a href="{post["url"]}">{title}</a>')
            any_highlights = True

        if any_highlights:
            section_lines.extend(reddit_lines)

    # ── YouTube Top Plays (opt-in, default OFF, API key optional) ──────────
    if youtube_enabled:
        yt_lines = ["\n▶️ <b>Top Plays</b>"]
        any_yt   = False

        for league_slug in leagues_to_show:
            yt_url = await _get_youtube_url(league_slug, yesterday)
            if yt_url:
                league_info = LEAGUES.get(league_slug.lower(), {})
                name_yt     = league_info.get("name", league_slug.upper())
                emoji_yt    = league_info.get("emoji", "🏆")
                yt_lines.append(f'  {emoji_yt} <a href="{yt_url}">{name_yt} Top Plays</a>')
                any_yt = True

        if any_yt:
            section_lines.extend(yt_lines)

    return "\n".join(section_lines)

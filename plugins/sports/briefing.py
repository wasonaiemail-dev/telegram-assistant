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
import html as _html_escape
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
    "nba":  {"channel": "UCWJ2lWNubArHWmf3FIHbfcQ", "query": "Top 10 Plays of the Night"},
    "nfl":  {"channel": "UCDVYQ4Zhbm3S2dlz7P1GBDg", "query": "Top 10 Plays of the Week"},
    "mlb":  {"channel": "UCzWQYUVCpZqtN93H8RR44Qw", "query": "Top 10 Plays"},
    "nhl":  {"channel": "UCqFMzb-4AUf6WAIbl132QKA", "query": "Top 10 Plays of the Night"},
    "epl":  {"channel": "UCqZQlzSHbVJrwrn5XvzrzcA", "query": "Top 10 Goals"},
}

# Words that indicate a title is NOT a "top plays" clip (used to filter API results)
_YT_EXCLUDE_TITLE_WORDS = ["recap", "nightly recap", "weekly", "monthly", "interview",
                            "press conference", "podcast", "preview", "schedule"]
# At least one of these must appear in the title for it to be kept
_YT_REQUIRE_TITLE_WORDS = ["top 10", "top plays", "best plays", "top dunks", "top goals",
                            "top moments", "top shots", "highlights", "plays of the night",
                            "plays of the week"]

# ── ESPN box score stat indices ───────────────────────────────────────────────
# Confirmed via live test: labels = ["MIN","PTS","FG","3PT","FT","REB","AST","TO","STL","BLK"]
_DEFAULT_LABELS = ["MIN", "PTS", "FG", "3PT", "FT", "REB", "AST", "TO", "STL", "BLK"]
_DEFAULT_PTS = 1
_DEFAULT_REB = 5
_DEFAULT_AST = 6
_DEFAULT_STL = 8
_DEFAULT_BLK = 9
_DEFAULT_FG  = 2

# ── Top performer thresholds ──────────────────────────────────────────────────
# Always show the top MIN players; show additional players up to MAX if their
# composite score (PTS + REB×0.5 + AST×0.5) meets the threshold.
# e.g. threshold=25 catches: 25 pts, 20/10, 18/8/8, etc.
TOP_PLAYERS_MIN       = 3
TOP_PLAYERS_MAX       = 6
COMPOSITE_THRESHOLD   = 25.0   # extra players shown only if score >= this

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


def _select_players_for_game(
    all_players: List[Dict[str, str]],
    min_n: int = TOP_PLAYERS_MIN,
    max_n: int = TOP_PLAYERS_MAX,
    threshold: float = COMPOSITE_THRESHOLD,
) -> List[Dict[str, str]]:
    """
    Return top performers for a game using a threshold-expansion rule:
      • Always include the top min_n players (floor).
      • Include additional players (up to max_n) whose composite score ≥ threshold.
      • Never exceed max_n to keep the briefing tight.

    Example with defaults (min=3, max=6, threshold=25):
      - A game with scores [38, 28, 18, 14] → returns 2 (both ≥25) + 1 mandatory = but
        since sorted, top 3 are 38/28/18; 38 and 28 qualify, 18 doesn't, so we keep 3.
      - A game with scores [40, 35, 30, 26, 12] → returns 4 (all ≥25 up to max 6).
    """
    if not all_players:
        return []

    # Guarantee at least min_n (or all players if fewer exist)
    result = list(all_players[:min_n])

    # Expand: add players beyond min_n who clear the threshold, up to max_n
    for player in all_players[min_n:max_n]:
        if player["score"] >= threshold:
            result.append(player)
        else:
            break  # sorted descending — once below threshold, rest are too

    return result


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


# ── YouTube domain set for sorting top plays ──────────────────────────────────
_YOUTUBE_DOMAINS = {"youtu.be", "youtube.com", "www.youtube.com"}

# ── Domains that reliably auto-embed as playable video in Discord ──────────────
# v.redd.it uses DASH streams (separate audio/video) → no inline playback
# instagram.com, twitter.com, x.com → require login or don't embed
# gfycat.com → shut down
# medal.tv → inconsistent embed support
_DISCORD_INLINE_DOMAINS = {
    "youtu.be", "youtube.com", "www.youtube.com",
    "streamable.com", "www.streamable.com",
    "clips.twitch.tv",
}


async def _fetch_reddit_top_plays_sub(
    subreddit: str,
    limit: int = 25,
    highlight_flair_only: bool = True,
    min_score: int = 0,
) -> List[Dict[str, Any]]:
    """
    Fetch highlight clips from a subreddit for the Top Plays section.

    When highlight_flair_only=True (league subs): only posts where
    link_flair_text contains "highlight" are returned — filters out
    interviews, quotes, news, and other non-play content.

    When highlight_flair_only=False (r/sports catch-all): falls back to
    any post with a video domain that clears min_score.

    Returns list of dicts: {title, url, score, domain, subreddit}
    url = the actual video link the post points to (not the Reddit permalink).
    """
    VIDEO_DOMAINS = {
        "streamable.com", "v.redd.it", "youtu.be", "youtube.com",
        "www.youtube.com", "twitter.com", "x.com", "instagram.com",
        "clips.twitch.tv", "gfycat.com", "medal.tv",
    }

    data = await _fetch_json(
        REDDIT_TOP_URL.format(sub=subreddit),
        headers=REDDIT_HEADERS,
        params={"t": "day", "limit": str(limit)},
    )
    if not data:
        return []

    posts = []
    try:
        for child in data.get("data", {}).get("children", []):
            post   = child.get("data", {})
            flair  = (post.get("link_flair_text") or "").lower()
            title  = post.get("title", "")
            domain = post.get("domain", "")
            score  = post.get("score", 0)
            url    = post.get("url", "")  # actual video URL, not permalink

            if not url or score < min_score:
                continue

            if highlight_flair_only:
                if "highlight" not in flair:
                    continue
            else:
                # Catch-all: require a known video domain
                if domain not in VIDEO_DOMAINS:
                    continue

            posts.append({
                "title":     title,
                "url":       url,
                "score":     score,
                "domain":    domain,
                "subreddit": subreddit,
            })
    except Exception as e:
        logger.error(f"Reddit top plays parse error (r/{subreddit}): {e}")

    posts.sort(key=lambda p: p["score"], reverse=True)
    return posts


async def _build_top_plays(
    leagues: List[str],
    total: int = 10,
) -> List[Dict[str, Any]]:
    """
    Assemble a cross-sport top plays list for the briefing.

    1. Fetches Highlight-flair posts from each configured league's subreddit.
    2. Fetches r/sports as a catch-all for sports not covered by a specific
       subreddit (tennis, cricket, Olympics, etc.) — requires ≥1000 upvotes.
    3. Deduplicates by URL.
    4. Sorts YouTube links first (they auto-embed inline in Discord/Telegram),
       then all others — both groups sorted by score descending.
    5. Returns top `total` clips.
    """
    CATCHALL_MIN_SCORE = 1000

    seen_urls: set = set()
    all_clips: List[Dict[str, Any]] = []

    # ── League-specific subreddits (Highlight flair only) ─────────────────
    tasks = []
    slugs = []
    for league_slug in leagues:
        sub = LEAGUE_SUBREDDITS.get(league_slug.lower())
        if sub:
            tasks.append(_fetch_reddit_top_plays_sub(sub, limit=25, highlight_flair_only=True))
            slugs.append(league_slug)

    results = await asyncio.gather(*tasks, return_exceptions=True)
    for posts in results:
        if isinstance(posts, list):
            for p in posts:
                if p["url"] not in seen_urls:
                    seen_urls.add(p["url"])
                    all_clips.append(p)

    # ── r/sports catch-all (any video domain, ≥1000 upvotes) ─────────────
    catchall = await _fetch_reddit_top_plays_sub(
        "sports", limit=50,
        highlight_flair_only=False,
        min_score=CATCHALL_MIN_SCORE,
    )
    for p in catchall:
        if p["url"] not in seen_urls:
            seen_urls.add(p["url"])
            all_clips.append(p)

    # ── Sort: YouTube links first (inline embed), then others — both by score
    yt_clips    = sorted([p for p in all_clips if p["domain"] in _YOUTUBE_DOMAINS],
                         key=lambda p: p["score"], reverse=True)
    other_clips = sorted([p for p in all_clips if p["domain"] not in _YOUTUBE_DOMAINS],
                         key=lambda p: p["score"], reverse=True)

    return (yt_clips + other_clips)[:total]


# ═══════════════════════════════════════════════════════════════════════════════
# YOUTUBE TOP PLAYS
# ═══════════════════════════════════════════════════════════════════════════════

async def _get_youtube_top10(
    league_slug: str, date: datetime, n: int = 10
) -> List[Dict[str, str]]:
    """
    Return up to n YouTube videos for the league's top plays from the given date.

    Each item: {"title": str, "url": str}

    With YOUTUBE_API_KEY:
      - Queries the league's official channel by viewCount for videos published
        on or after the given date (publishedAfter).
      - Returns up to n results as individual video links.

    Without YOUTUBE_API_KEY:
      - Returns a single search URL item (can't enumerate videos without the API).
      - title = "{League} Top Plays — {date}", url = YouTube search URL.

    Telegram callers render each item as a numbered hyperlink.
    Discord callers post each raw URL on its own line for auto-embed.
    """
    yt       = LEAGUE_YT_INFO.get(league_slug.lower())
    league_info = LEAGUES.get(league_slug.lower(), {})
    league_name = league_info.get("name", league_slug.upper())
    date_str    = date.strftime("%B %-d, %Y")

    if not yt:
        # No official channel mapped — fall back to a single search URL
        query = f"{league_name} top plays {date.strftime('%B %-d %Y')}"
        return [{"title": f"{league_name} Top Plays — {date_str}",
                 "url":   YOUTUBE_SEARCH_URL.format(q=quote_plus(query))}]

    api_key = os.environ.get("YOUTUBE_API_KEY")

    if api_key:
        import datetime as _dt
        import html as _html
        # Search 3 days back so we always catch the previous night's upload
        # even if it was posted just after midnight
        search_from = date - _dt.timedelta(days=1)
        published_after = _dt.datetime(
            search_from.year, search_from.month, search_from.day, 0, 0, 0
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        data = await _fetch_json(
            YOUTUBE_API_URL,
            params={
                "part":           "snippet",
                "channelId":      yt["channel"],
                "q":              yt["query"],
                "type":           "video",
                "order":          "date",          # most-recent first, not most-viewed
                "publishedAfter": published_after,
                "maxResults":     "25",            # fetch more so we can filter
                "key":            api_key,
            },
        )
        if data:
            items = data.get("items", [])
            results = []
            for item in items:
                video_id = item.get("id", {}).get("videoId")
                title    = _html_escape.escape(_html.unescape(item.get("snippet", {}).get("title", "Top Plays")))
                title_lower = title.lower()
                # Skip videos whose title contains excluded words
                if any(w in title_lower for w in _YT_EXCLUDE_TITLE_WORDS):
                    continue
                # Only keep videos that look like actual highlight/plays clips
                if not any(w in title_lower for w in _YT_REQUIRE_TITLE_WORDS):
                    continue
                if video_id:
                    results.append({
                        "title": title,
                        "url":   f"https://youtu.be/{video_id}",
                    })
                if len(results) >= n:
                    break
            if results:
                return results

    # Fallback: single search URL (no API key or API returned nothing)
    query = f"{yt['query']} {date_str}"
    return [{"title": f"{league_name} Top Plays — {date_str}",
             "url":   YOUTUBE_SEARCH_URL.format(q=quote_plus(query))}]


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
    name = _html_escape.escape(player.get("name", "Unknown"))
    team = _html_escape.escape(player.get("team", "?")[:3])
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
    away        = _html_escape.escape(game.get("away_team", "Away"))
    home        = _html_escape.escape(game.get("home_team", "Home"))
    away_score  = _html_escape.escape(str(game.get("away_score", "")))
    home_score  = _html_escape.escape(str(game.get("home_score", "")))
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

async def section_sports_briefing(_now, platform: str = "telegram") -> str:
    """
    Morning briefing section: sports recap.

    Hooked into features/briefing.py as _SECTION_BUILDERS["sports"].
    Returns formatted HTML string or "" if nothing to show.

    platform: "telegram" or "discord"
      - Telegram: HTML links (<a href>), numbered YouTube list
      - Discord:  plain YouTube URLs on separate lines (auto-embed)
    """
    # ── Load settings ──────────────────────────────────────────────────────
    try:
        settings = load_sports_settings()
    except Exception as e:
        logger.error(f"Sports briefing: settings load failed: {e}")
        return ""

    favorite_teams    = settings.get("favorite_teams", [])    # [{league, team_id, team_name}]
    favorite_leagues  = settings.get("favorite_leagues", [])  # [league_slug, ...]
    reddit_enabled    = settings.get("briefing_top_plays", True)
    youtube_enabled   = False  # dormant — Reddit Top Plays is the active source
    track_players     = settings.get("briefing_track_fav_players", False)
    tracked_names     = settings.get("briefing_favorite_players", [])  # display names

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

    # Lookup dict populated as we parse box scores — name.lower() → player dict
    # Used at the end for tracked player stat lines (zero extra API calls).
    all_players_seen: Dict[str, Dict[str, str]] = {}

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

                # Extract top performers from box score using threshold expansion.
                # _parse_top_players with n=99 gets everyone sorted; we then apply
                # the threshold rule (min 3, extras up to max 6 if score ≥ 25).
                top_players: List[Dict[str, str]] = []
                bs = box_score_map.get(event.get("id"))
                if bs:
                    all_in_game = _parse_top_players(bs, n=99)
                    top_players = _select_players_for_game(all_in_game)
                    # Also register everyone for tracked-player stat lookup
                    for p in all_in_game:
                        all_players_seen[p["name"].lower()] = p

                league_lines.append(_fmt_game_recap(game, top_players, is_favorite=is_fav))
                had_any_game = True

            except Exception as e:
                logger.debug(f"Game parse error: {e}")
                continue

        if len(league_lines) > 1:  # More than just the league header
            section_lines.extend(league_lines)

    if not had_any_game:
        return ""  # No completed games — nothing useful to show

    # ── Top Plays (opt-in, default ON) ────────────────────────────────────
    # Sources Reddit highlight-flair clips from league subreddits + r/sports
    # catch-all. YouTube links sorted first for inline embed in Discord.
    if reddit_enabled:
        # On Discord, fetch a larger pool so we have enough after filtering to
        # inline-playable domains (v.redd.it and others don't embed in Discord).
        _reddit_fetch_total = 25 if platform == "discord" else 10
        clips = await _build_top_plays(leagues_to_show, total=_reddit_fetch_total)
        if platform == "discord":
            # Keep only clips that will actually play inline in Discord
            clips = [c for c in clips if c["domain"] in _DISCORD_INLINE_DOMAINS][:10]
        if clips:
            plays_lines = ["\n🎬 <b>Top Plays</b>"]
            for i, clip in enumerate(clips, 1):
                title = clip["title"]
                if len(title) > 80:
                    title = title[:77] + "…"
                if platform == "discord":
                    # Discord auto-embeds raw video URLs for supported domains
                    plays_lines.append(f"{i}. {title}")
                    plays_lines.append(clip["url"])
                else:
                    plays_lines.append(f'  {i}. <a href="{clip["url"]}">{_html_escape.escape(title)}</a>')
            section_lines.extend(plays_lines)

    # ── YouTube Top Plays (opt-in, default OFF, API key optional) ──────────
    # Telegram: numbered list of HTML hyperlinks (up to 10 per league)
    # Discord:  raw YouTube URLs on separate lines — Discord auto-embeds each one
    if youtube_enabled:
        yt_lines = ["\n▶️ <b>Top Plays</b>"]
        any_yt   = False

        for league_slug in leagues_to_show:
            league_info = LEAGUES.get(league_slug.lower(), {})
            name_yt     = league_info.get("name", league_slug.upper())
            emoji_yt    = league_info.get("emoji", "🏆")

            videos = await _get_youtube_top10(league_slug, yesterday, n=10)
            if not videos:
                continue

            if platform == "discord":
                # Discord auto-embeds raw YouTube URLs — one URL per line
                yt_lines.append(f"\n{emoji_yt} **{name_yt} Top Plays**")
                for vid in videos:
                    yt_lines.append(vid["url"])
            else:
                # Telegram: numbered hyperlink list
                yt_lines.append(f"\n{emoji_yt} <b>{name_yt} Top Plays</b>")
                for i, vid in enumerate(videos, 1):
                    title = vid["title"]
                    if len(title) > 70:
                        title = title[:67] + "…"
                    yt_lines.append(f'  {i}. <a href="{vid["url"]}">{title}</a>')

            any_yt = True

        if any_yt:
            section_lines.extend(yt_lines)

    # ── Tracked Player Stats (opt-in, default OFF) ─────────────────────────
    # No extra API calls — scanned from box scores already fetched above.
    # If the player didn't appear in any box score yesterday (injury/rest/off-day),
    # we note that rather than silently skipping them.
    if track_players and tracked_names:
        player_lines = ["\n👤 <b>Your Players</b>"]
        for name in tracked_names:
            match = all_players_seen.get(name.lower())
            if match:
                player_lines.append(_fmt_player_line(match).lstrip())  # no indent for this section
            else:
                player_lines.append(f"  <code>{name}: did not play yesterday</code>")
        section_lines.extend(player_lines)

    return "\n".join(section_lines)

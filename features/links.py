"""
alfred/features/links.py
========================
Read-later / link saving — store URLs with AI-extracted titles and summaries.

STORAGE
───────
  config.LINKS_FILE (JSON):
    [
      {id: uuid4, url: "...", title: "...", summary: "...", tags: [...],
       saved_at: "2026-03-27T10:00:00", read: false, snooze_until: null, notes: ""},
      ...
    ]

COMMANDS
────────
  /readlater         — show unread links with buttons
  /rl                — shortcut for /readlater
  /readlater save <url>  — save a link
  /readlater search <query> — search saved links

INTENT HANDLER
──────────────
  handle_link_intent(intent, entities, update, context)
    LINK_SAVE, LINK_VIEW, LINK_SEARCH, LINK_MARK_READ, LINK_SNOOZE
"""

import os
import json
import logging
import datetime
import uuid
import re

import requests

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from core.config import LINKS_FILE, OPENAI_API_KEY, GPT_CHAT_MODEL
from core.intent import LINK_SAVE, LINK_VIEW, LINK_SEARCH, LINK_MARK_READ, LINK_SNOOZE

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# STORAGE HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _load_links() -> list:
    """Load links from file, returning empty list if not found."""
    if not os.path.exists(LINKS_FILE):
        return []
    try:
        with open(LINKS_FILE, "r") as f:
            return json.load(f) or []
    except Exception as e:
        logger.warning(f"links: error loading file: {e}")
        return []


def _save_links(links: list) -> None:
    """Save links to file with atomic write."""
    try:
        os.makedirs(os.path.dirname(LINKS_FILE), exist_ok=True)
        tmp_path = LINKS_FILE + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(links, f, indent=2)
        os.replace(tmp_path, LINKS_FILE)
    except Exception as e:
        logger.error(f"links: error saving file: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# GPT-POWERED LINK EXTRACTION
# ─────────────────────────────────────────────────────────────────────────────

async def _gpt_extract_link_info(url: str) -> dict:
    """
    Fetch URL, strip HTML, and use GPT-4o-mini to extract title, summary, and tags.
    Returns dict with title, summary, tags keys.
    Raises on error.
    """
    from openai import AsyncOpenAI

    # Fetch URL content
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        resp = requests.get(url, timeout=10, headers=headers)
        resp.raise_for_status()
        content = resp.text
    except Exception as e:
        logger.warning(f"links: fetch error for {url}: {e}")
        raise

    # Strip HTML tags
    text = re.sub(r'<script[^>]*>.*?</script>', '', content, flags=re.DOTALL)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    text = text[:2000]  # limit

    # Use GPT to extract
    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    try:
        resp = await client.chat.completions.create(
            model=GPT_CHAT_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "Extract from webpage content: 1) a clear title (under 60 chars), "
                               "2) a 2-sentence summary, 3) 2-4 lowercase tags separated by commas. "
                               "Return JSON: {\"title\": \"...\", \"summary\": \"...\", \"tags\": [...]}"
                },
                {"role": "user", "content": f"Content: {text}"},
            ],
            temperature=0.7,
            max_tokens=200,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content.strip()
        data = json.loads(raw)
        return {
            "title": data.get("title", "Untitled"),
            "summary": data.get("summary", ""),
            "tags": data.get("tags", []),
        }
    except Exception as e:
        logger.error(f"links: GPT extraction error: {e}")
        raise


# ─────────────────────────────────────────────────────────────────────────────
# LINK MANAGEMENT
# ─────────────────────────────────────────────────────────────────────────────

async def save_link(url: str, note: str = "") -> dict:
    """
    Save a link: fetch content, extract info via GPT, save entry.
    Returns the saved entry dict.
    """
    info = await _gpt_extract_link_info(url)

    entry = {
        "id": str(uuid.uuid4()),
        "url": url,
        "title": info.get("title", ""),
        "summary": info.get("summary", ""),
        "tags": info.get("tags", []),
        "saved_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "read": False,
        "snooze_until": None,
        "notes": note,
    }

    links = _load_links()
    links.append(entry)
    _save_links(links)

    return entry


def get_unread_links() -> list:
    """Return unread, non-snoozed links sorted by saved_at."""
    links = _load_links()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return [
        l for l in links
        if not l.get("read") and (not l.get("snooze_until") or l.get("snooze_until") < now)
    ]


def mark_read(link_id: str) -> bool:
    """Mark a link as read. Returns True if found and updated."""
    links = _load_links()
    for link in links:
        if link.get("id") == link_id:
            link["read"] = True
            _save_links(links)
            return True
    return False


def snooze_link(link_id: str, days: int) -> bool:
    """Snooze a link. Returns True if found and updated."""
    links = _load_links()
    snooze_until = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=days)
    for link in links:
        if link.get("id") == link_id:
            link["snooze_until"] = snooze_until.isoformat()
            _save_links(links)
            return True
    return False


def search_links(query: str) -> list:
    """Search links by title, summary, tags, notes."""
    links = _load_links()
    q = query.lower()
    return [
        l for l in links
        if q in l.get("title", "").lower()
        or q in l.get("summary", "").lower()
        or q in " ".join(l.get("tags", [])).lower()
        or q in l.get("notes", "").lower()
    ]


def get_weekly_digest_text() -> str:
    """Return formatted list of unread links for briefing/digest."""
    links = get_unread_links()
    if not links:
        return ""

    lines = ["📚 *Saved Links* (" + str(len(links)) + " unread)\n"]
    for link in links[:5]:
        title = link.get("title", "Untitled")[:40]
        tags = ", ".join(link.get("tags", [])[:2])
        lines.append(f"• {title}" + (f" `{tags}`" if tags else ""))

    if len(links) > 5:
        lines.append(f"  … and {len(links) - 5} more")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# COMMANDS
# ─────────────────────────────────────────────────────────────────────────────

async def cmd_readlater(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /readlater and /rl commands."""
    if not update.message:
        return

    links = get_unread_links()
    if not links:
        await update.message.reply_text("📚 No unread links saved yet. Use /readlater save <url> to add one.")
        return

    # Show first 5 with buttons
    display = links[:5]
    lines = ["📚 *Your Saved Links* (" + str(len(links)) + " unread)\n"]

    keyboard = []
    for i, link in enumerate(display):
        title = link.get("title", "Untitled")[:50]
        lines.append(f"{i+1}. {title}")

        link_id = link.get("id", "")[:8]  # short ID for callback
        keyboard.append([
            InlineKeyboardButton("✓ Read", callback_data=f"link_read_{link_id}"),
            InlineKeyboardButton("⏱️ Snooze", callback_data=f"link_snooze_{link_id}"),
        ])

    if len(links) > 5:
        lines.append(f"\n… and {len(links) - 5} more")

    markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("\n".join(lines), reply_markup=markup, parse_mode="Markdown")


async def handle_link_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle link mark-read and snooze callbacks."""
    query = update.callback_query
    data_str = query.data or ""

    if data_str.startswith("link_read_"):
        link_id_prefix = data_str.split("_")[-1]
        # Find full ID starting with this prefix
        links = _load_links()
        for link in links:
            if link.get("id", "").startswith(link_id_prefix):
                mark_read(link.get("id"))
                await query.answer("✓ Marked as read")
                # Refresh list
                await cmd_readlater(update, context)
                return

    elif data_str.startswith("link_snooze_"):
        link_id_prefix = data_str.split("_")[-1]
        links = _load_links()
        for link in links:
            if link.get("id", "").startswith(link_id_prefix):
                snooze_link(link.get("id"), 3)
                await query.answer("⏱️ Snoozed for 3 days")
                await query.edit_message_text("⏱️ Snoozed for 3 days")
                return


# ─────────────────────────────────────────────────────────────────────────────
# INTENT HANDLER
# ─────────────────────────────────────────────────────────────────────────────

async def handle_link_intent(intent: str, entities: dict, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route LINK_* intents."""
    if not update.message:
        return

    if intent == LINK_SAVE:
        url = entities.get("url", "")
        if not url:
            # Try to extract from text
            text = update.message.text or ""
            url_match = re.search(r'https?://[^\s]+', text)
            if not url_match:
                await update.message.reply_text("Please include a URL (starting with http:// or https://)")
                return
            url = url_match.group(0)

        note = entities.get("note", "")

        await update.message.reply_text("📚 Saving and extracting…")
        try:
            entry = await save_link(url, note)
            await update.message.reply_text(
                f"✓ Saved: *{entry.get('title')}*\n\n_{entry.get('summary', '')}_",
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"links: save error: {e}")
            await update.message.reply_text(f"❌ Failed to save link: {e}")

    elif intent == LINK_VIEW:
        await cmd_readlater(update, context)

    elif intent == LINK_SEARCH:
        query = entities.get("query", "")
        if not query:
            await update.message.reply_text("What would you like to search for?")
            return

        results = search_links(query)
        if not results:
            await update.message.reply_text(f"No links found matching '{query}'")
            return

        lines = [f"🔍 *Search Results for '{query}'* ({len(results)} found)\n"]
        for link in results[:10]:
            lines.append(f"• {link.get('title', 'Untitled')[:40]}")
            if link.get("tags"):
                lines.append(f"  `{', '.join(link.get('tags', [])[:2])}`")

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    elif intent == LINK_MARK_READ:
        # User said "mark that as read" — not fully implemented without context tracking
        await update.message.reply_text("Use the buttons in /readlater to mark links as read.")

    elif intent == LINK_SNOOZE:
        # Similarly incomplete without context
        await update.message.reply_text("Use the buttons in /readlater to snooze links.")

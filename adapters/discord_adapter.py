"""
marvin/adapters/discord_adapter.py
=====================================
Builds an MarvinContext from a Discord Message object.

Usage in discord_bot.py:
    from adapters.discord_adapter import make_context

    @bot.event
    async def on_message(message):
        ctx = make_context(message)
        # ... classify intent and dispatch

DISCORD FORMATTING NOTES
--------------------------
Discord does NOT support HTML. This adapter's reply() implementation
passes text straight to message.channel.send(). The html_to_discord()
converter in core/html_utils.py handles any HTML-formatted text before
it reaches this adapter.

INLINE MENUS (Phase 4 MVP)
--------------------------
Discord supports buttons via discord.ui.View, but for Phase 4 MVP we
render menus as numbered text responses. Full button support is Phase 6.

Example numbered menu output:
    "Choose a league:\n\n1. 🏀 NBA\n2. 🏈 NFL\n3. ⚾ MLB\n\n_Reply with a number._"

DISCORD MARKDOWN
-----------------
Discord uses a subset of Markdown (CommonMark):
    **bold**, *italic*, __underline__, ~~strikethrough~~
    `inline code`, ```code block```
    > blockquote
    [links don't render as clickable — just show the URL or use angle brackets <url>]

DISCORD MESSAGE LENGTH
-----------------------
Discord limits messages to 2000 characters. Long messages are split
automatically by this adapter into 2000-char chunks.
"""

from __future__ import annotations

import logging
from typing import Any

from core.marvin_context import MarvinContext, MenuButton

logger = logging.getLogger(__name__)

# Discord's message character limit
_DISCORD_MAX_LEN = 2000


def make_context(message: Any) -> MarvinContext:
    """
    Build an MarvinContext from a discord.Message object.

    Requires: discord.py (or discord.py-stubs) installed.
    The `message` parameter is typed as Any to avoid a hard import
    dependency on discord.py in non-Discord deployments.
    """
    text = message.content or ""
    user_id = message.author.id
    chat_id = message.channel.id

    # Parse args: "!scores nba" or "/scores nba" → ["nba"]
    # Marvin on Discord uses "!" prefix by default (configurable)
    parts = text.split()
    if parts and (parts[0].startswith("!") or parts[0].startswith("/")):
        args = parts[1:]
    else:
        args = []

    # ── Send functions ────────────────────────────────────────────────────────

    async def _reply(text_: str, parse_mode_: str = None) -> None:
        """Send a text reply. parse_mode is ignored — Discord uses Markdown."""
        # Discord doesn't need parse_mode, but if HTML was passed by mistake,
        # strip the tags to avoid raw HTML showing up in chat.
        if parse_mode_ and parse_mode_.upper() == "HTML":
            from core.html_utils import html_to_discord
            text_ = html_to_discord(text_)

        if not text_:
            return

        # Split long messages at the Discord 2000-char limit
        chunks = _split_message(text_)
        for chunk in chunks:
            try:
                await message.channel.send(chunk)
            except Exception as e:
                logger.error(f"discord_adapter._reply error: {e}")

    async def _reply_doc(file_path: str, caption: str = "") -> None:
        """Send a file attachment to the Discord channel."""
        try:
            import discord  # type: ignore
            discord_file = discord.File(file_path)
            await message.channel.send(content=caption or None, file=discord_file)
        except Exception as e:
            logger.error(f"discord_adapter._reply_doc error: {e}")
            await message.channel.send(f"⚠️ Could not send file: {e}")

    async def _typing() -> None:
        """Show typing indicator via Discord's async context manager."""
        try:
            async with message.channel.typing():
                pass  # Just trigger the typing indicator
        except Exception:
            pass

    async def _reply_menu(text_: str, rows: list[list[MenuButton]]) -> None:
        """
        Render a menu as numbered text options (Phase 4 MVP).

        Full discord.ui.View button support is Phase 6.
        """
        from core.html_utils import html_to_discord

        # Convert any HTML in the prompt text
        clean_text = html_to_discord(text_)

        # Flatten all buttons into a numbered list
        all_buttons = [btn for row in rows for btn in row]
        numbered = "\n".join(
            f"{i+1}. {btn.label}"
            for i, btn in enumerate(all_buttons)
        )

        full_msg = f"{clean_text}\n\n{numbered}\n\n*Reply with a number to choose.*"

        chunks = _split_message(full_msg)
        for chunk in chunks:
            try:
                await message.channel.send(chunk)
            except Exception as e:
                logger.error(f"discord_adapter._reply_menu error: {e}")

    # ── Build and return MarvinContext ────────────────────────────────────────

    return MarvinContext(
        text=text,
        user_id=user_id,
        chat_id=chat_id,
        platform="discord",
        args=args,
        _reply_fn=_reply,
        _reply_doc_fn=_reply_doc,
        _typing_fn=_typing,
        _reply_menu_fn=_reply_menu,
        _update=None,    # No Telegram Update on Discord
        _context=None,   # No Telegram context on Discord
    )


# ═══════════════════════════════════════════════════════════════════════════════
# UTILITIES
# ═══════════════════════════════════════════════════════════════════════════════

def _split_message(text: str, max_len: int = _DISCORD_MAX_LEN) -> list[str]:
    """
    Split a message into chunks that fit within Discord's character limit.

    Splits on newlines where possible to avoid cutting words mid-sentence.
    """
    if len(text) <= max_len:
        return [text]

    chunks = []
    while len(text) > max_len:
        # Try to split at the last newline within the limit
        split_at = text.rfind("\n", 0, max_len)
        if split_at == -1:
            # No newline — hard split at max_len
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")

    if text:
        chunks.append(text)

    return chunks

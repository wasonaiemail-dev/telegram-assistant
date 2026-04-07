"""
alfred/core/alfred_context.py
==============================
Platform-agnostic context object passed to all Alfred command handlers.

WHY THIS EXISTS
---------------
Alfred originally ran only on Telegram, so every handler took
(update: Update, context: ContextTypes.DEFAULT_TYPE) and called
update.message.reply_text(). Adding Discord (or any other platform)
would require duplicating all handler logic.

AlfredContext solves this by wrapping the platform-specific send/reply
interface behind a single object. Handlers call ctx.reply_html(text)
and it works on any platform.

HOW ADAPTERS WORK
-----------------
Each platform provides an adapter that builds an AlfredContext from its
native event object:

    # Telegram (adapters/telegram_adapter.py)
    ctx = telegram_adapter.make_context(update, context)

    # Discord (adapters/discord_adapter.py)
    ctx = discord_adapter.make_context(message)

Both produce an AlfredContext with the same interface. Handlers never
import Telegram or Discord code directly.

MIGRATION PATH
--------------
During the migration period, ctx._update and ctx._context provide
pass-through access to the raw Telegram objects. Code that hasn't been
migrated yet can use these. Eventually they will be removed.

INLINE KEYBOARDS / MENUS
------------------------
Telegram uses InlineKeyboardMarkup + callback queries.
Discord uses discord.ui.View with Button components.

For Phase 4 MVP, menus are rendered as numbered text on Discord:
    "Reply with a number:\n1. NBA\n2. NFL\n3. NHL"
This is handled transparently by ctx.reply_menu().
Full Discord button support is Phase 6 polish.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# MENU BUTTON SPEC (platform-agnostic)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class MenuButton:
    """A single button in a reply menu."""
    label: str          # Display text, e.g. "🏀 NBA"
    callback_id: str    # Callback data string, e.g. "sports_league_nba"


# ═══════════════════════════════════════════════════════════════════════════════
# ALFRED CONTEXT
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class AlfredContext:
    """
    Platform-agnostic context object passed to all command handlers.

    Build one using the platform adapter, never directly:
        ctx = telegram_adapter.make_context(update, context)
        ctx = discord_adapter.make_context(message)
    """

    # ── Incoming message info ────────────────────────────────────────────────
    text:      str        # Raw message text (command included, e.g. "/scores nba")
    user_id:   int        # Sender's user/member ID
    chat_id:   int        # Chat / channel / DM ID
    platform:  str        # "telegram" | "discord"

    # ── Platform-specific send callables (set by adapter) ────────────────────
    # Each is an async callable. Set by the platform adapter.
    _reply_fn:     Callable = field(repr=False)   # async (text, parse_mode=None) -> None
    _reply_doc_fn: Callable = field(repr=False)   # async (file_path, caption="") -> None
    _typing_fn:    Callable = field(repr=False)   # async () -> None
    _reply_menu_fn: Callable = field(repr=False)  # async (text, rows: list[list[MenuButton]]) -> None

    # ── Backward-compat pass-throughs (Telegram only, None on Discord) ───────
    # These exist to support feature code that hasn't been migrated yet.
    # Do not use in new code. They will be removed in Phase 6.
    _update:  Any = field(default=None, repr=False)    # telegram.Update
    _context: Any = field(default=None, repr=False)    # telegram ContextTypes

    # ── Command args parsed from text ────────────────────────────────────────
    # Populated by the adapter: e.g. "/scores nba" → args = ["nba"]
    args: list = field(default_factory=list)


    # ── Core reply interface ─────────────────────────────────────────────────

    async def reply(self, text: str, parse_mode: Optional[str] = None) -> None:
        """Send a plain text reply. parse_mode is ignored on Discord."""
        await self._reply_fn(text, parse_mode)

    async def reply_html(self, text: str) -> None:
        """
        Send an HTML-formatted reply.

        On Telegram: sends with parse_mode=HTML (unchanged).
        On Discord:  converts HTML tags to Discord markdown first.
        """
        if self.platform == "telegram":
            await self._reply_fn(text, "HTML")
        else:
            from core.html_utils import html_to_discord
            await self._reply_fn(html_to_discord(text), None)

    async def reply_markdown(self, text: str) -> None:
        """
        Send a Markdown-formatted reply.

        On Telegram: sends with parse_mode=MARKDOWN.
        On Discord:  Discord uses its own markdown natively — just send as-is.
        """
        if self.platform == "telegram":
            await self._reply_fn(text, "MARKDOWN")
        else:
            await self._reply_fn(text, None)

    async def reply_document(self, file_path: str, caption: str = "") -> None:
        """Send a file/document attachment."""
        await self._reply_doc_fn(file_path, caption)

    async def send_typing(self) -> None:
        """Show a typing indicator (best-effort, no-op if not supported)."""
        try:
            await self._typing_fn()
        except Exception:
            pass  # Typing indicators are non-critical

    async def reply_menu(
        self,
        text: str,
        rows: list[list[MenuButton]],
    ) -> None:
        """
        Send a message with an interactive button menu.

        On Telegram: renders as InlineKeyboardMarkup.
        On Discord (Phase 4 MVP): renders as numbered text options,
            e.g. "1. NBA  2. NFL  3. NHL — reply with a number".
        Full Discord button support is Phase 6.
        """
        await self._reply_menu_fn(text, rows)


    # ── Backward-compat properties (Telegram only) ───────────────────────────

    @property
    def update(self):
        """
        Raw Telegram Update object (None on Discord).
        Use only for code not yet migrated to AlfredContext.
        """
        return self._update

    @property
    def context(self):
        """
        Raw Telegram context (None on Discord).
        Use only for code not yet migrated to AlfredContext.
        """
        return self._context


    # ── Convenience ──────────────────────────────────────────────────────────

    @property
    def is_telegram(self) -> bool:
        return self.platform == "telegram"

    @property
    def is_discord(self) -> bool:
        return self.platform == "discord"

    def get_arg(self, index: int, default: str = "") -> str:
        """Get a parsed command argument by index, with a default."""
        try:
            return self.args[index]
        except IndexError:
            return default

    def args_text(self, start: int = 0) -> str:
        """Join args from `start` onwards into a single string."""
        return " ".join(self.args[start:])

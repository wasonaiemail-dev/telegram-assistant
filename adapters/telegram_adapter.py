"""
alfred/adapters/telegram_adapter.py
=====================================
Builds an AlfredContext from a Telegram Update + ContextTypes object.

Usage in bot.py:
    from adapters.telegram_adapter import make_context

    async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        ctx = make_context(update, context)
        await some_handler(intent, ents, ctx)

The resulting AlfredContext wraps all Telegram-specific send calls so that
handlers work unchanged when ported to other platforms.

INLINE KEYBOARD MENUS
---------------------
Telegram renders menus as InlineKeyboardMarkup buttons. The reply_menu()
call here builds a full InlineKeyboardMarkup from the platform-agnostic
list[list[MenuButton]] spec.
"""

from __future__ import annotations

import logging
from typing import Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode, ChatAction
from telegram.ext import ContextTypes

from core.alfred_context import AlfredContext, MenuButton

logger = logging.getLogger(__name__)


def make_context(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> AlfredContext:
    """
    Build an AlfredContext from a Telegram Update.

    Works for both command messages (/scores nba) and plain text messages.
    Returns None if the update has no message (e.g. edited messages — callers
    should guard against this).
    """
    msg = update.effective_message
    user = update.effective_user

    if msg is None or user is None:
        raise ValueError("telegram_adapter: update has no message or user")

    text = msg.text or ""
    chat_id = msg.chat_id
    user_id = user.id

    # Parse args from command messages: "/scores nba lakers" → ["nba", "lakers"]
    parts = text.split()
    if parts and parts[0].startswith("/"):
        args = parts[1:]
    else:
        args = []

    # ── Send functions ────────────────────────────────────────────────────────

    async def _reply(text_: str, parse_mode_: str = None) -> None:
        """Send a text reply to the user."""
        kwargs = {}
        if parse_mode_:
            if parse_mode_.upper() == "HTML":
                kwargs["parse_mode"] = ParseMode.HTML
            elif parse_mode_.upper() in ("MARKDOWN", "MD"):
                kwargs["parse_mode"] = ParseMode.MARKDOWN
        try:
            await msg.reply_text(text_, **kwargs)
        except Exception as e:
            logger.error(f"telegram_adapter._reply error: {e}")
            # Fallback: strip formatting and retry
            try:
                await msg.reply_text(text_)
            except Exception:
                pass

    async def _reply_doc(file_path: str, caption: str = "") -> None:
        """Send a file/document to the user."""
        try:
            with open(file_path, "rb") as f:
                await context.bot.send_document(
                    chat_id=chat_id,
                    document=f,
                    caption=caption,
                )
        except Exception as e:
            logger.error(f"telegram_adapter._reply_doc error: {e}")
            await msg.reply_text(f"⚠️ Could not send file: {e}")

    async def _typing() -> None:
        """Show typing indicator."""
        try:
            await context.bot.send_chat_action(
                chat_id=chat_id,
                action=ChatAction.TYPING,
            )
        except Exception:
            pass

    async def _reply_menu(text_: str, rows: list[list[MenuButton]]) -> None:
        """
        Build and send an InlineKeyboardMarkup from a list of MenuButton rows.

        rows is a list of rows, each row is a list of MenuButton objects.
        Example:
            rows = [
                [MenuButton("🏀 NBA", "sports_league_nba"),
                 MenuButton("🏈 NFL", "sports_league_nfl")],
                [MenuButton("⚾ MLB", "sports_league_mlb")],
            ]
        """
        keyboard = [
            [
                InlineKeyboardButton(btn.label, callback_data=btn.callback_id)
                for btn in row
            ]
            for row in rows
        ]
        try:
            await msg.reply_text(
                text_,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            logger.error(f"telegram_adapter._reply_menu error: {e}")
            # Fallback: numbered text list
            numbered = "\n".join(
                f"{i+1}. {btn.label}"
                for i, btn in enumerate(btn for row in rows for btn in row)
            )
            await msg.reply_text(f"{text_}\n\n{numbered}")

    # ── Build and return AlfredContext ────────────────────────────────────────

    return AlfredContext(
        text=text,
        user_id=user_id,
        chat_id=chat_id,
        platform="telegram",
        args=args,
        _reply_fn=_reply,
        _reply_doc_fn=_reply_doc,
        _typing_fn=_typing,
        _reply_menu_fn=_reply_menu,
        _update=update,
        _context=context,
    )

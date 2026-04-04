"""
Photo handling integration for sports betting screenshots.

This module should be called from bot.py when a sports context is detected
or when a screenshot containing betting lines is identified.
"""

import logging
import os
from telegram import Update
from telegram.ext import ContextTypes

from plugins.sports import betting
from plugins.sports import config as sports_config

logger = logging.getLogger(__name__)


async def handle_sports_photo(
    photo_path: str,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    caption: str = "",
) -> bool:
    """
    Handle a photo that may contain sportsbook odds or betting data.

    This is called when:
    1. A photo is sent with sports-related caption text
    2. A screenshot is detected and classified as betting-related
    3. User explicitly asks about sportsbooks in the message

    Args:
        photo_path: Path to the downloaded photo file
        update: Telegram Update object
        context: Telegram context
        caption: Optional caption text from user

    Returns:
        True if handled as a sports photo, False otherwise
    """
    try:
        # Read photo bytes
        with open(photo_path, "rb") as f:
            photo_bytes = f.read()

        # Try to analyze as betting screenshot
        logger.info("Analyzing photo as sportsbook odds screenshot...")
        result = await betting.analyze_betting_screenshot(photo_bytes, caption)

        if not result.get("success"):
            logger.debug(f"Not a sportsbook screenshot: {result.get('error')}")
            return False

        # Format response
        message = "<b>📊 Line Comparison</b>\n\n"
        message += f"Game: <b>{result.get('game', 'Unknown')}</b>\n"
        message += f"Bet Type: {result.get('bet_type', 'Unknown').upper()}\n\n"

        # Show all books
        books = result.get("books", [])
        if books:
            message += "<b>Available Books:</b>\n"
            for book in books:
                odds = book.get("odds", 0)
                prob = book.get("implied_prob", 0)
                message += f"  {book.get('name', 'Unknown')}: {odds:+d} ({prob:.1f}%)\n"

        # Highlight best book
        best = result.get("best_book", {})
        if best:
            message += f"\n<b>Best Line:</b> {best.get('name', 'Unknown')} @ {best.get('odds', 0):+d}\n"
            if best.get("edge"):
                message += f"  {best.get('edge')}\n"

        message += "\n💡 <i>Send a bet slip screenshot for automatic logging, or use /bets add</i>"

        await update.message.reply_text(message, parse_mode="HTML")
        return True

    except Exception as e:
        logger.error(f"Sports photo handling error: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# BOT.PY INTEGRATION INSTRUCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

"""
TO INTEGRATE INTO bot.py:

In the handle_message() function, after the photo detection block (around line 409),
add this before the general photo analysis:

    # Add this after: photo_type = await _detect_photo_type(tmp_path)

    # Check for sports betting context
    if "sports" in caption.lower() or "bet" in caption.lower() or "odds" in caption.lower():
        from plugins.sports.photo_handler import handle_sports_photo
        handled = await handle_sports_photo(tmp_path, update, context, caption)
        if handled:
            os.unlink(tmp_path)
            return

    # Or check photo type and route to sports handler:
    if photo_type == "screenshot" and _is_sports_context(update, context):
        from plugins.sports.photo_handler import handle_sports_photo
        handled = await handle_sports_photo(tmp_path, update, context, caption)
        if handled:
            os.unlink(tmp_path)
            return

ALTERNATIVELY:

The photo handler can be triggered by modifying the _detect_photo_type() function
to return "sportsbook" as a classification, then routing accordingly.

FULL INTEGRATION PATTERN:

    elif update.message.photo:
        from features.reply_assist import handle_photo_for_reply
        import os
        import tempfile

        photo   = update.message.photo[-1]
        caption = (update.message.caption or "").strip()
        tg_file = await context.bot.get_file(photo.file_id)
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            await tg_file.download_to_drive(tmp.name)
            tmp_path = tmp.name

        try:
            photo_type = await _detect_photo_type(tmp_path)

            # NEW: Check for sports betting context
            if "sports" in caption.lower() or "bet" in caption.lower():
                from plugins.sports.photo_handler import handle_sports_photo
                handled = await handle_sports_photo(tmp_path, update, context, caption)
                if handled:
                    return

            if photo_type == "receipt":
                from features.shopping import handle_receipt_photo
                await handle_receipt_photo(tmp_path, update, context)
            elif photo_type == "screenshot":
                await handle_photo_for_reply(tmp_path, update, context, is_email=False)
            else:
                description = await _analyse_photo_file(tmp_path)
                if description:
                    await update.message.reply_text(description)
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
        return
"""


def _is_sports_context(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Check if the message has sports-related context.

    Can be enhanced to check:
    - Message caption for sports keywords
    - User's stored favorite leagues/teams
    - Recent message history
    """
    caption = (update.message.caption or "").strip().lower()
    sports_keywords = [
        "nfl",
        "nba",
        "mlb",
        "nhl",
        "sports",
        "bet",
        "odds",
        "line",
        "parlay",
        "sportsbook",
        "draft",
        "fan",
        "caesars",
        "draftkings",
        "fanduel",
        "betmgm",
    ]
    return any(keyword in caption for keyword in sports_keywords)

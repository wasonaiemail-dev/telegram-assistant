# Sports Betting Module Integration Guide

This guide explains how to integrate the Sports Betting Module's photo handler into the bot's main message handling.

## Quick Integration

The Sports Betting Module is **plug-and-play** and requires no changes to bot.py to function. However, to enable automatic screenshot analysis for sportsbook odds, follow the optional integration below.

## Optional: Photo Handler Integration

### What It Does

When a user sends a screenshot of sportsbook odds (with or without a caption mentioning sports), the bot will:

1. Detect it's a sports-related screenshot
2. Use GPT-4o Vision to extract odds from all visible sportsbooks
3. Show a formatted comparison with the best line highlighted
4. Prompt the user to use `/bets add` to log a bet

### Integration Steps

**File:** `/bot.py`

**Location:** In the `handle_message()` function, around line 420-430 (after photo detection)

**Current Code (lines 409-439):**
```python
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

        if photo_type == "receipt":
            from features.shopping import handle_receipt_photo
            await handle_receipt_photo(tmp_path, update, context)
        elif photo_type == "screenshot":
            await handle_photo_for_reply(tmp_path, update, context, is_email=False)
        else:
            # General photo — existing analysis
            description = await _analyse_photo_file(tmp_path)
            if description:
                await update.message.reply_text(description)
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
    return
```

**Modified Code (Add 7 lines after line 420):**

```python
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

        # ✨ NEW: Check for sports betting context (OPTIONAL)
        if _is_sports_betting_photo(caption):
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
            # General photo — existing analysis
            description = await _analyse_photo_file(tmp_path)
            if description:
                await update.message.reply_text(description)
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
    return
```

### Add Helper Function

At the end of bot.py, add this helper function:

```python
def _is_sports_betting_photo(caption: str) -> bool:
    """
    Check if a photo caption indicates sports betting content.

    Triggers on:
    - Sports league mentions (NFL, NBA, MLB, NHL, EPL, MLS)
    - Betting keywords (odds, lines, sportsbook, bet, parlay)
    - Sportsbook names (DraftKings, FanDuel, BetMGM, Caesars, etc.)
    """
    caption_lower = caption.lower()

    sports_keywords = [
        # Leagues
        "nfl", "nba", "mlb", "nhl", "ncaaf", "ncaab",
        "epl", "mls", "bundesliga", "laliga",

        # Betting terms
        "bet", "odds", "line", "lines", "spread", "moneyline",
        "parlay", "props", "o/u", "over", "under", "ml",

        # Sportsbooks
        "draftkings", "fanduel", "betmgm", "caesars",
        "espn bet", "fanatics", "bovada", "mybookie",
        "draft", "fan", "mgm", "sportsbook",
    ]

    return any(keyword in caption_lower for keyword in sports_keywords)
```

### Alternative: Automatic Detection

If you want the bot to automatically detect sports screenshots even without a caption, you can enhance `_detect_photo_type()`:

```python
async def _detect_photo_type(file_path: str) -> str:
    """
    Classify image type: 'receipt', 'screenshot', 'sportsbook', or 'general'.
    """
    # ... existing code ...

    # Modify the prompt to include 'sportsbook' as an option:
    prompt_text = """Classify this image as exactly one of:
    - 'receipt' (store/restaurant receipt showing purchased items and prices)
    - 'screenshot' (screenshot of text messages, emails, social media, apps)
    - 'sportsbook' (screenshot of betting lines/odds from a sportsbook)
    - 'general' (anything else like photos of people, places, food, objects)

    Reply with ONLY the single word."""

    # ... Then route 'sportsbook' to the sports handler ...
```

## Without Integration

The Sports Betting Module works perfectly fine without modifying bot.py:

- Users can send screenshots with caption: "DraftKings odds" or "betting lines"
- The `/bets` commands work fully
- Users can send bet slip screenshots and the bot can process them if explicitly called

To use without bot.py integration:

```
# User sends screenshot with caption
/bets add screenshot

# Or mentions it in the caption
<sends photo>
Caption: "Can you analyze these DraftKings lines?"

# Or directly commands
/bets chart pnl
```

## Testing the Integration

### Test 1: Sportsbook Screenshot

```
1. Take a screenshot of DraftKings or FanDuel odds
2. Send to bot with caption: "DraftKings odds"
3. Bot should show formatted line comparison
4. Verify best book is highlighted
```

### Test 2: Bet Slip

```
1. Take screenshot of bet slip confirmation
2. Send with caption: "New bet on FanDuel $100"
3. Bot should extract details and show confirmation
4. Check /bets to confirm bet was logged
```

### Test 3: Text Logging

```
/bets add $100 on Chiefs -3 at DraftKings
# Should log and show confirmation
```

### Test 4: Statistics

```
/bets stats
# Should show calculated win rate, ROI, etc.
```

### Test 5: Charts

```
/bets chart pnl
# Should send PNG chart
```

## Configuration

No additional configuration needed. The module uses:

- **Data Storage:** `/data/sports_plugin/bets.json`
- **Settings:** `/data/sports_plugin/settings.json`
- **OpenAI API:** Uses existing `OPENAI_API_KEY` from config
- **Requirements:** Added `matplotlib>=3.8.0` to requirements.txt

## Logging

Enable debug logging to see module operation:

```python
import logging
logging.getLogger("plugins.sports.betting").setLevel(logging.DEBUG)
logging.getLogger("plugins.sports.charts").setLevel(logging.DEBUG)
logging.getLogger("plugins.sports.photo_handler").setLevel(logging.DEBUG)
```

## Troubleshooting Integration

### Photo Handler Not Triggering

1. Verify caption contains a sports keyword
2. Check `_is_sports_betting_photo()` function is defined
3. Confirm import path: `from plugins.sports.photo_handler import handle_sports_photo`
4. Check bot logs for errors

### GPT-4o Vision Calls Failing

1. Verify `OPENAI_API_KEY` is set correctly
2. Check OpenAI account has access to Vision API
3. Ensure image quality and size are reasonable
4. Look for API errors in logs

### Charts Not Generating

1. Install matplotlib: `pip install matplotlib>=3.8.0`
2. Ensure you have at least 3 resolved bets
3. Check disk space for image generation
4. Verify permission to write to temp directory

## Production Checklist

- [ ] Add photo handler integration to bot.py (optional but recommended)
- [ ] Install matplotlib: `pip install -r requirements.txt`
- [ ] Test all `/bets` commands
- [ ] Test screenshot analysis with sample sportsbook image
- [ ] Verify chart generation works
- [ ] Check that bets persist across restarts
- [ ] Review error handling in logs
- [ ] Test with multiple leagues (NFL, NBA, etc.)

## Rollback

If you add the photo handler integration and need to remove it:

1. Delete the sports photo handler check (lines with `_is_sports_betting_photo`)
2. Remove the helper function `_is_sports_betting_photo`
3. Restart the bot

The `/bets` commands will continue to work without the integration.

## Files Modified/Created

### Created
- `plugins/sports/betting.py` — Main betting logic
- `plugins/sports/charts.py` — Chart generation
- `plugins/sports/photo_handler.py` — Photo handler (optional integration)
- `plugins/sports/BETTING_MODULE.md` — Full documentation
- `plugins/sports/INTEGRATION_GUIDE.md` — This file

### Modified
- `plugins/sports/commands.py` — Added betting subcommands
- `plugins/sports/dispatch.py` — Added intent routing
- `requirements.txt` — Added matplotlib

### No Changes Needed
- `bot.py` — Optional integration (see above)
- `plugins/sports/__init__.py` — Already configured for betting
- `plugins/sports/data.py` — Already supports bet storage
- `plugins/sports/config.py` — Already has settings

## Support & Updates

For issues:
1. Check BETTING_MODULE.md for detailed API reference
2. Review error messages in logs
3. Verify JSON data integrity in `/data/sports_plugin/`
4. Test with simpler commands first (`/bets stats` before charts)

For enhancements:
- Review "Future Enhancements" section in BETTING_MODULE.md
- Consider adding live odds API integration
- Extend chart types and visualization options

# Sports Betting Module Documentation

## Overview

The Sports Betting Module extends the Alfred Sports Pack with advanced sports betting tools including:

- **Screenshot-based Line Comparison** — Extract odds from sportsbook screenshots using GPT-4o Vision
- **Bet Sizing Calculators** — Fixed unit, percentage, and Kelly Criterion sizing
- **Bet Tracking** — Log, resolve, and track all bets with automatic P&L calculation
- **Analytics & Charts** — Comprehensive statistics and dark-themed visualization charts
- **Intent Routing** — Full integration with Alfred's intent system for natural language commands

## Quick Start

### Viewing Recent Bets

```
/bets                    # Show recent bets and P&L summary
/bets stats              # Detailed statistics with breakdowns
```

### Logging Bets

#### From Text Description
```
/bets add $50 on Chiefs -3 at DraftKings
/bets add FanDuel: $100 Over 45
/bets add moneyline +200 Celtics
```

#### From Bet Slip Screenshot
Send a screenshot of a bet slip with the caption:
```
Screenshot of DraftKings $100 parlay
```

The module will automatically extract:
- Game/matchup
- Bet type (moneyline, spread, over/under, prop, parlay)
- Odds
- Stake
- Potential payout

### Resolving Bets

```
/bets resolve <bet_id> won      # Mark bet as won
/bets resolve <bet_id> lost     # Mark bet as lost
/bets resolve <bet_id> push     # Mark bet as a push

# Example: /bets resolve abc123de won
```

To find bet IDs, use `/bets` to view recent bets — IDs are shown as the first 8 characters.

## Core Modules

### 1. `betting.py` — Main Betting Logic

Core functions for all betting operations.

#### Screenshot Analysis
```python
result = await analyze_betting_screenshot(photo_bytes, context_text="")

# Returns:
{
    "success": True,
    "game": "Chiefs vs 49ers",
    "bet_type": "spread",
    "books": [
        {
            "name": "DraftKings",
            "odds": -110,
            "implied_prob": 52.38,
            "display": "-110"
        },
        {
            "name": "FanDuel",
            "odds": -105,
            "implied_prob": 51.22
        }
    ],
    "best_book": {
        "name": "FanDuel",
        "odds": -105,
        "implied_prob": 51.22,
        "edge": "Better odds by 5"
    },
    "notes": "Line movement detected"
}
```

**Supported Sportsbooks:**
- DraftKings
- FanDuel
- BetMGM
- Caesars
- ESPN Bet
- Fanatics
- Bovada
- MyBookie

**Supported Bet Types:**
- Moneyline (ML)
- Spread
- Over/Under (O/U)
- Prop bets
- Parlays
- Futures

---

#### Bet Sizing Calculator
```python
# Fixed unit sizing
result = await calculate_bet_size(
    odds=-110,
    bankroll_or_unit=50.0,  # Your unit size
    method="fixed_unit",
    confidence=None
)
# Returns: {"stake": 50.00, "units": 1.0, "recommendation": "..."}

# Percentage of bankroll
result = await calculate_bet_size(
    odds=-110,
    bankroll_or_unit=1000.0,  # Your bankroll
    method="percentage"
)
# Returns: {"stake": 20.00, "percentage": 2.0, "recommendation": "..."}

# Kelly Criterion
result = await calculate_bet_size(
    odds=-110,
    bankroll_or_unit=1000.0,
    method="kelly",
    confidence=0.60  # Your estimated edge (60% win probability)
)
# Returns: Kelly-sized stake based on edge
```

**Methods:**
- **fixed_unit**: Bet N × your unit size (recommended for consistent sizing)
- **percentage**: Risk a percentage of your total bankroll (conservative approach)
- **kelly**: Kelly Criterion sizing based on win probability (aggressive)

---

#### Logging Bets

From text:
```python
result = await log_bet_from_text(
    text="$50 on Chiefs -3 at DraftKings",
    user_settings=settings
)

# Returns:
{
    "success": True,
    "bet_id": "uuid-string",
    "message": "Bet logged: Chiefs @ -3",
    "bet": {
        "league": "NFL",
        "game": "Chiefs vs 49ers",
        "bet_type": "spread",
        "pick": "Chiefs",
        "odds": -3,
        "stake": 50.0,
        "result": "pending",
        "pnl": 0.0,
        "notes": "..."
    }
}
```

From bet slip screenshot:
```python
result = await log_bet_from_screenshot(
    photo_bytes=image_data,
    user_settings=settings
)
# Same return structure as log_bet_from_text
```

---

#### Resolving Bets

```python
result = await resolve_bet(
    bet_id="uuid-string",
    result="win",  # "win", "loss", or "push"
    pnl=None  # Optional; auto-calculated if not provided
)

# Returns:
{
    "success": True,
    "bet": {...updated bet record...},
    "message": "Bet resolved: WIN | P&L: +$45.45"
}
```

---

#### Statistics & Analytics

```python
stats = await calculate_stats(
    bets=None,  # Uses all bets if None
    period=None,
    league=None  # Filter by league
)

# Returns:
{
    "total_bets": 50,
    "wins": 30,
    "losses": 15,
    "pushes": 5,
    "pending": 0,
    "win_rate": 66.67,
    "total_staked": 2500.0,
    "total_returned": 3000.0,
    "net_pnl": 500.0,
    "roi": 20.0,
    "by_league": {
        "NFL": {
            "wins": 20,
            "losses": 10,
            "win_rate": 66.67,
            "roi": 25.0,
            "pnl": 500.0
        },
        "NBA": {
            "wins": 10,
            "losses": 5,
            "win_rate": 66.67,
            "roi": 15.0,
            "pnl": 0.0
        }
    },
    "by_bet_type": {...},
    "streak": {
        "current": "W",
        "count": 3
    },
    "best_league": "NFL",
    "worst_league": "NBA"
}
```

---

### 2. `charts.py` — Visualization

Generate professional, dark-themed PNG charts for Telegram.

#### P&L Chart
```python
png_bytes = await generate_pnl_chart(bets, period="all")
# Line chart of cumulative P&L over time
# Green/red coloring for profit/loss
```

#### Win Rate by League
```python
png_bytes = await generate_win_rate_chart(bets)
# Bar chart showing win rate (%) for each league
# Green bars for >50%, red for <50%
```

#### ROI by Sportsbook
```python
png_bytes = await generate_roi_chart(bets)
# Horizontal bar chart of ROI (%) by sportsbook
# Green for positive ROI, red for negative
```

#### Unit Tracker
```python
png_bytes = await generate_unit_tracker(bets)
# Line chart of units won/lost over time
# Helpful for tracking unit profitability
```

#### Bet Distribution
```python
png_bytes = await generate_bet_distribution(bets)
# Pie chart showing % breakdown by bet type
# (moneyline, spread, over/under, props, parlays)
```

---

## Commands Reference

### `/bets` — Main Betting Manager

**Usage:**
```
/bets                           # View recent bets (default)
/bets view                      # Same as above
/bets add <description>         # Log bet from text
/bets stats                     # Detailed statistics
/bets chart [type]              # Generate chart (pnl|winrate|roi|units|distribution)
/bets bankroll                  # Show/set bankroll
/bets resolve <id> <result>     # Resolve pending bet
/bets help                      # Show this menu
```

**Examples:**

View recent bets:
```
/bets
```

Log a new bet:
```
/bets add $100 Chiefs -3 DraftKings

/bets add
{caption text} FanDuel $50 Over 45
```

Show statistics:
```
/bets stats
```

Send P&L chart:
```
/bets chart pnl
/bets chart winrate
/bets chart roi
/bets chart units
/bets chart distribution
```

Resolve pending bets:
```
/bets resolve abc123de won
/bets resolve xyz789ab lost
/bets resolve qwerty00 push
```

---

## Data Storage

All betting data is stored in JSON at:
```
/data/sports_plugin/bets.json
```

Bet Record Schema:
```json
{
    "id": "uuid-string",
    "date": "2024-01-15T14:30:00Z",
    "league": "NFL",
    "game": "Chiefs vs 49ers",
    "bet_type": "spread",
    "pick": "Chiefs",
    "odds": -110,
    "stake": 50.0,
    "result": "pending",
    "pnl": 0.0,
    "unit_size": 1.0,
    "notes": "Optional notes"
}
```

---

## Configuration

User settings stored at:
```
/data/sports_plugin/settings.json
```

Settings include:
```json
{
    "bankroll": 1000.0,
    "unit_size": 50.0,
    "kelly_fraction": 0.25,
    "min_odds": -110,
    "favorite_teams": [],
    "favorite_leagues": [],
    "alerts_enabled": true
}
```

**Set bankroll via command:**
```
/bets bankroll 1000           # Set bankroll to $1000
/bets bankroll 1000 50        # Set bankroll $1000, unit size $50
```

---

## Photo/Screenshot Integration

### Sending Sportsbook Screenshots

Send a screenshot of odds from any sportsbook with a caption:

```
<screenshot of DraftKings odds>
Caption: "DraftKings lines"
```

The bot will:
1. Analyze the image using GPT-4o Vision
2. Extract all visible lines and odds
3. Identify the best book
4. Show line comparison

### Sending Bet Slips

Send a screenshot of a completed bet slip:

```
<screenshot of bet confirmation>
Caption: "New bet on FanDuel"
```

The bot will:
1. Extract bet details (game, type, odds, stake)
2. Automatically create a bet record
3. Show confirmation with bet ID

---

## Intent System Integration

The module integrates with Alfred's intent detection system.

### Supported Intents

| Intent | Handler | Description |
|--------|---------|-------------|
| `sports_bet_add` | Bet logging | "Log a bet" or "I bet $50 on..." |
| `sports_bet_view` | Recent bets | "Show my bets" or "Recent wagers" |
| `sports_bet_compare` | Statistics | "Compare my performance" or "Show stats" |
| `sports_bet_calculate` | Sizing | "Calculate bet size" or "Kelly sizing" |

### Natural Language Examples

```
"Log a $100 parlay on the Chiefs"
→ sports_bet_add intent

"Show my betting statistics"
→ sports_bet_compare intent

"What's my win rate?"
→ sports_bet_compare intent

"Calculate Kelly sizing for -110 odds"
→ sports_bet_calculate intent
```

---

## API Reference

### Supported Odds Formats

American (default):
- Negative = Favorite (e.g., -110)
- Positive = Underdog (e.g., +200)

### Helper Functions

#### Odds Conversion
```python
# American to Decimal
decimal = sports_data.american_to_decimal(-110)  # 1.909

# Decimal to American
american = sports_data.decimal_to_american(1.909)  # -110
```

#### Implied Probability
```python
prob = betting._implied_probability(-110)  # 52.38%
```

#### Payout Calculation
```python
payout = betting._calculate_payout(stake=100, odds=-110)  # 190.91
```

#### Kelly Criterion
```python
kelly_frac = sports_data.calculate_kelly_fraction(
    win_probability=0.55,
    odds=-110,
    kelly_fraction=0.25  # 25% of full Kelly
)  # Returns optimal bet size fraction
```

#### Parlay Odds
```python
parlay_odds = sports_data.calculate_parlay_odds([-110, +200, -150])
# Returns combined parlay odds
```

---

## Error Handling

All functions return result dictionaries with `success` boolean:

```python
result = await betting.log_bet_from_text(text, settings)

if result.get("success"):
    bet_id = result["bet_id"]
    # Handle success
else:
    error = result.get("error", "Unknown error")
    # Handle error
```

Common errors:
- Invalid odds format
- Missing required fields
- File I/O failures
- API errors (when using Vision API)

---

## Performance Notes

### API Usage

- **GPT-4o Vision API** — Used for screenshot analysis (line comparison & bet slip extraction)
- **GPT-3.5-Turbo** — Used for natural language bet parsing
- **No external APIs** — All stat calculations are local

### Caching

- Bets are cached in memory during command execution
- Statistics are calculated on-demand (no background caching)
- User settings are loaded once per command

### Optimization

For large bet histories (1000+ bets):
- Use league filtering: `sports_data.get_bets(league="NFL", limit=500)`
- Chart generation takes 1-2 seconds (matplotlib rendering)

---

## Troubleshooting

### Screenshot Analysis Not Working

1. Ensure photo quality is clear and legible
2. Include sportsbook name in caption if possible
3. Crop to show only the relevant odds lines
4. Try again with better lighting/contrast

### Bets Not Being Logged

1. Check that description includes: league, team, odds, stake
2. Use standard abbreviations (NFL, NBA, ML, -110, etc.)
3. Verify date/time is not corrupted

### Charts Not Generating

1. Ensure you have at least 3 resolved bets
2. Check that matplotlib is installed: `pip install matplotlib>=3.8.0`
3. Verify bets have valid dates in ISO format

### Photo Handler Not Triggering

See `photo_handler.py` for integration instructions into `bot.py`.

---

## Example Workflow

### Complete Betting Cycle

```
1. User sends sportsbook screenshot
   /bets (or screenshot with caption "DraftKings")
   → Bot shows line comparison

2. User decides to place bet
   /bets add $100 on Chiefs -3
   → Bet logged with status "pending"

3. Game is played
   /bets
   → Shows pending bet in recent list

4. User resolves the bet
   /bets resolve abc123de won
   → Bet marked as won with P&L calculated

5. User reviews performance
   /bets stats
   → Shows updated win rate, ROI, and streak

6. User views charts
   /bets chart pnl
   /bets chart roi
   → Sends PNG charts via Telegram
```

---

## Future Enhancements

Potential features for future versions:

- [ ] Closing Line Value (CLV) tracking
- [ ] Integration with live odds APIs (for line shopping)
- [ ] Parlay builder with expected value calculation
- [ ] Bankroll management alerts and warnings
- [ ] Scheduled weekly/monthly performance summaries
- [ ] Export to CSV or spreadsheet
- [ ] Multi-user tracking (if needed)
- [ ] Alerts for line moves or opportunities
- [ ] Historical odds comparison
- [ ] Pro tipster tracking against user performance

---

## Support

For issues or questions:
1. Check error messages in logs
2. Review examples in this documentation
3. Verify JSON data is valid (use online JSON validator)
4. Check that all required fields are present in bet records

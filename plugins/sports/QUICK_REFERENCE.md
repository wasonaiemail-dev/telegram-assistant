# Sports Betting Module — Quick Reference

## Core Commands

| Command | Purpose |
|---------|---------|
| `/bets` | Show recent bets & summary |
| `/bets add <text>` | Log a bet from description |
| `/bets stats` | Detailed statistics |
| `/bets chart [type]` | Generate chart (pnl\|winrate\|roi\|units\|distribution) |
| `/bets bankroll [amt] [unit]` | Set bankroll |
| `/bets resolve <id> <result>` | Mark bet as won/lost/push |

## Example Usage

### Log a Bet
```
/bets add $100 on Chiefs -3
/bets add FanDuel: $50 Over 45
/bets add moneyline +200 Lakers
```

### View Performance
```
/bets            # Recent bets
/bets stats      # Full stats
/bets chart pnl  # P&L chart
```

### Resolve Bets
```
/bets resolve abc123de won
/bets resolve xyz789ab lost
/bets resolve qrs456tu push
```

## Photo Integration

Send a sportsbook screenshot with caption:
```
<Screenshot of DraftKings odds>
Caption: "DraftKings lines"
```

Bot responds with line comparison and best book.

## Statistics Returned

| Metric | Description |
|--------|-------------|
| **Total Bets** | Number of bets placed |
| **Record** | W-L-Push (wins-losses-pushes) |
| **Win Rate** | % of resolved bets won |
| **Streak** | Current W/L streak |
| **Total Staked** | Sum of all bet amounts |
| **Net P&L** | Total profit/loss |
| **ROI** | Return on investment % |
| **By League** | Stats broken down by NFL, NBA, etc. |

## Bet Sizing Methods

### Fixed Unit
```
/bets chart pnl  # Then: $50 × 2 = $100 bet
```
Use multiples of your unit size (conservative, consistent)

### Percentage
```
Risk 2% of bankroll on each bet
Bankroll $1000 = $20 per bet
```
More aggressive but proportional to account size

### Kelly Criterion
```
Optimal sizing based on your edge
Only use if you have confidence in probability estimate
```
Most aggressive, requires accurate probability assessment

## Sportsbooks Supported

DraftKings • FanDuel • BetMGM • Caesars • ESPN Bet • Fanatics • Bovada • MyBookie

## Data Files

| File | Purpose |
|------|---------|
| `/data/sports_plugin/bets.json` | All bet records |
| `/data/sports_plugin/settings.json` | User preferences |

## Key Concepts

**Odds Formats:**
- Negative = Favorite (e.g., -110)
- Positive = Underdog (e.g., +200)

**Implied Probability:**
- -110 → 52.38% implied probability
- +200 → 33.33% implied probability

**ROI = (Net P&L / Total Staked) × 100**

**Streak = Current consecutive wins or losses**

## Keyboard Shortcuts (Telegram)

After sending a command with inline buttons:
- Click "Add Bet" → Prompts for description
- Click "Stats" → Shows statistics
- Click "Charts" → Shows chart options
- Click "Bankroll" → Opens settings

## File Structure

```
plugins/sports/
├── betting.py              (Main logic)
├── charts.py               (Chart generation)
├── photo_handler.py        (Photo handling)
├── commands.py             (Command handlers)
├── dispatch.py             (Intent routing)
├── BETTING_MODULE.md       (Full documentation)
├── INTEGRATION_GUIDE.md    (bot.py integration)
├── QUICK_REFERENCE.md      (This file)
└── BETTING_MODULE_SUMMARY.txt
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Chart won't generate | Need 3+ resolved bets |
| Screenshot not working | Caption must mention sports/betting keywords |
| Stats show 0% | Need at least one resolved bet (win or loss) |
| Matplotlib error | Run: `pip install matplotlib>=3.8.0` |

## Tips & Tricks

1. **Name your bets:** Add notes for future reference
   ```
   /bets add $100 Chiefs -3 (home game, good matchup)
   ```

2. **Use consistent units:** Helps with bankroll management
   ```
   /bets bankroll 1000 50  (1000 total, 50 per unit)
   ```

3. **Track best leagues:** Check which leagues you perform best in
   ```
   /bets stats  (shows by_league breakdown)
   ```

4. **Review streaks:** Know when you're hot/cold
   ```
   Current streak shown in /bets stats
   ```

5. **Monitor ROI by book:** Find where you win most
   ```
   /bets chart roi
   ```

## Common Workflows

### Daily Check-in
```
/bets          # See recent bets
/bets stats    # Quick stats
/bets chart pnl  # See P&L trend
```

### New Bet
```
/bets add [description]  # Log the bet
(Wait for result)
/bets resolve [id] [result]  # Mark as won/lost
```

### Weekly Review
```
/bets stats      # Full statistics
/bets chart roi  # ROI analysis
/bets chart winrate  # League breakdown
```

## Advanced Usage

### Parse Natural Language
The module understands various formats:
- "bet $100 on chiefs"
- "$50 chiefs -3"
- "100 to win moneyline chiefs"
- "fanuel [sic] parlay chiefs + over"

### Implied Probability Conversion
- Favorites: -X odds → X/(X+100) probability
- Underdogs: +X odds → 100/(X+100) probability

### Kelly Criterion Sizing
- Requires estimated win probability
- Automatically calculates optimal bet size
- Limited to 25% of full Kelly (conservative)

## Format Examples

### Bet Record
```json
{
  "id": "uuid",
  "date": "2024-01-15T14:30:00Z",
  "league": "NFL",
  "game": "Chiefs vs 49ers",
  "bet_type": "spread",
  "pick": "Chiefs",
  "odds": -110,
  "stake": 100.0,
  "result": "win",
  "pnl": 90.91,
  "notes": "home game advantage"
}
```

### Stats Response
```
Total Bets: 50
Record: 30-15-5
Win Rate: 66.67%
Total Staked: $2500.00
Net P&L: +$500.00
ROI: 20.00%
Streak: W 3
```

## API Keys & Configuration

Required:
- `OPENAI_API_KEY` — For GPT-4o Vision and text parsing

Optional:
- Integration into bot.py for auto photo handling
- See `INTEGRATION_GUIDE.md`

## Performance

- Screenshot analysis: 2-5 seconds (GPT-4o API call)
- Stats calculation: <1 second (up to 1000 bets)
- Chart generation: 1-2 seconds (matplotlib rendering)

## Support Resources

1. **Full API Reference:** `BETTING_MODULE.md`
2. **Bot Integration:** `INTEGRATION_GUIDE.md`
3. **Implementation Details:** `BETTING_MODULE_SUMMARY.txt`
4. **Source Code:** `betting.py`, `charts.py`, `photo_handler.py`

## Version Info

- **Module Version:** 1.0.0
- **Created:** 2026-04-04
- **Status:** Production ready

---

**Need help?** Check the full documentation in `BETTING_MODULE.md`

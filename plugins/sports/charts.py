"""
Chart generation for sports betting analytics.

Generates professional, dark-themed PNG charts for Telegram using matplotlib.
"""

import io
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.ticker import FuncFormatter

logger = logging.getLogger(__name__)

# Dark theme configuration
DARK_BG = "#1a1a1a"
DARK_FG = "#ffffff"
ACCENT_GREEN = "#00d084"
ACCENT_RED = "#ff3860"
ACCENT_BLUE = "#3273dc"
GRID_COLOR = "#333333"


def _setup_dark_theme():
    """Configure matplotlib for dark-themed charts."""
    plt.style.use("dark_background")
    plt.rcParams.update({
        "figure.facecolor": DARK_BG,
        "axes.facecolor": DARK_BG,
        "axes.edgecolor": GRID_COLOR,
        "text.color": DARK_FG,
        "grid.color": GRID_COLOR,
        "grid.linestyle": "--",
        "grid.alpha": 0.3,
        "font.size": 10,
        "font.family": "sans-serif",
    })


# ═══════════════════════════════════════════════════════════════════════════════
# P&L CHART
# ═══════════════════════════════════════════════════════════════════════════════


async def generate_pnl_chart(
    bets: List[Dict[str, Any]],
    period: str = "all",
) -> Optional[bytes]:
    """
    Generate cumulative P&L line chart over time.

    Args:
        bets: List of bet records (sorted by date, most recent first)
        period: Filter period (not yet implemented, uses all bets)

    Returns:
        PNG bytes or None on error
    """
    try:
        _setup_dark_theme()

        # Filter resolved bets only
        resolved = [b for b in bets if b.get("result") != "pending"]
        if not resolved:
            logger.warning("No resolved bets for P&L chart")
            return None

        # Sort by date ascending
        resolved = sorted(resolved, key=lambda b: b.get("date", ""))

        # Calculate cumulative P&L
        dates = []
        cumulative_pnl = []
        running_total = 0.0

        for bet in resolved:
            try:
                date_str = bet.get("date", "")
                if date_str:
                    # Parse ISO format date
                    date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    dates.append(date)
                    running_total += float(bet.get("pnl", 0))
                    cumulative_pnl.append(running_total)
            except Exception as e:
                logger.debug(f"Date parse error: {e}")
                continue

        if not dates:
            return None

        # Create figure
        fig, ax = plt.subplots(figsize=(12, 6))

        # Plot line
        colors = [ACCENT_GREEN if y >= 0 else ACCENT_RED for y in cumulative_pnl]
        ax.plot(dates, cumulative_pnl, color=ACCENT_BLUE, linewidth=2.5, label="Cumulative P&L")

        # Fill area
        for i in range(len(dates) - 1):
            color = ACCENT_GREEN if cumulative_pnl[i + 1] >= 0 else ACCENT_RED
            ax.fill_between(
                dates[i : i + 2],
                cumulative_pnl[i : i + 2],
                alpha=0.3,
                color=color,
            )

        # Formatting
        ax.axhline(y=0, color=GRID_COLOR, linestyle="-", linewidth=1)
        ax.grid(True, alpha=0.3)
        ax.set_xlabel("Date")
        ax.set_ylabel("Cumulative P&L ($)")
        ax.set_title("Cumulative P&L Over Time")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)

        # Format y-axis as currency
        ax.yaxis.set_major_formatter(FuncFormatter(lambda x, p: f"${x:,.0f}"))

        plt.tight_layout()

        # Save to bytes
        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=100, facecolor=DARK_BG)
        buf.seek(0)
        plt.close()

        return buf.getvalue()

    except Exception as e:
        logger.error(f"P&L chart generation error: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# WIN RATE BY LEAGUE
# ═══════════════════════════════════════════════════════════════════════════════


async def generate_win_rate_chart(bets: List[Dict[str, Any]]) -> Optional[bytes]:
    """
    Generate win rate by league as bar chart.

    Args:
        bets: List of bet records

    Returns:
        PNG bytes or None on error
    """
    try:
        _setup_dark_theme()

        resolved = [b for b in bets if b.get("result") != "pending"]
        if not resolved:
            return None

        # Calculate stats by league
        leagues = {}
        for bet in resolved:
            league = bet.get("league", "Unknown")
            if league not in leagues:
                leagues[league] = {"wins": 0, "losses": 0, "pushes": 0}

            result = bet.get("result")
            if result == "win":
                leagues[league]["wins"] += 1
            elif result == "loss":
                leagues[league]["losses"] += 1
            elif result == "push":
                leagues[league]["pushes"] += 1

        # Calculate win rates
        league_names = []
        win_rates = []
        colors = []

        for league, stats in sorted(leagues.items()):
            total = stats["wins"] + stats["losses"]
            if total > 0:
                wr = (stats["wins"] / total) * 100
                league_names.append(league)
                win_rates.append(wr)
                colors.append(ACCENT_GREEN if wr > 50 else ACCENT_RED)

        if not league_names:
            return None

        # Create figure
        fig, ax = plt.subplots(figsize=(10, 6))

        bars = ax.bar(league_names, win_rates, color=colors, alpha=0.7, edgecolor=DARK_FG)

        # Add value labels on bars
        for bar, wr in zip(bars, win_rates):
            height = bar.get_height()
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                height + 1,
                f"{wr:.1f}%",
                ha="center",
                va="bottom",
                fontsize=10,
            )

        ax.axhline(y=50, color=GRID_COLOR, linestyle="--", linewidth=1, alpha=0.5)
        ax.set_xlabel("League")
        ax.set_ylabel("Win Rate (%)")
        ax.set_title("Win Rate by League")
        ax.set_ylim(0, 100)
        ax.grid(True, alpha=0.3, axis="y")

        plt.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=100, facecolor=DARK_BG)
        buf.seek(0)
        plt.close()

        return buf.getvalue()

    except Exception as e:
        logger.error(f"Win rate chart error: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# ROI BY SPORTSBOOK
# ═══════════════════════════════════════════════════════════════════════════════


async def generate_roi_chart(bets: List[Dict[str, Any]]) -> Optional[bytes]:
    """
    Generate ROI by sportsbook as horizontal bar chart.

    Args:
        bets: List of bet records

    Returns:
        PNG bytes or None on error
    """
    try:
        _setup_dark_theme()

        resolved = [b for b in bets if b.get("result") != "pending"]
        if not resolved:
            return None

        # Calculate stats by book
        books = {}
        for bet in resolved:
            # Try to extract book from notes or use Unknown
            notes = bet.get("notes", "")
            book = "Unknown"
            for sportsbook in ["DraftKings", "FanDuel", "BetMGM", "Caesars", "ESPN", "Fanatics", "Bovada"]:
                if sportsbook.lower() in notes.lower():
                    book = sportsbook
                    break

            if book not in books:
                books[book] = {"staked": 0.0, "pnl": 0.0}

            books[book]["staked"] += float(bet.get("stake", 0))
            books[book]["pnl"] += float(bet.get("pnl", 0))

        # Calculate ROI
        book_names = []
        roi_values = []
        colors = []

        for book, stats in sorted(books.items()):
            if stats["staked"] > 0:
                roi = (stats["pnl"] / stats["staked"]) * 100
                book_names.append(book)
                roi_values.append(roi)
                colors.append(ACCENT_GREEN if roi > 0 else ACCENT_RED)

        if not book_names:
            return None

        # Create figure
        fig, ax = plt.subplots(figsize=(10, 6))

        bars = ax.barh(book_names, roi_values, color=colors, alpha=0.7, edgecolor=DARK_FG)

        # Add value labels
        for bar, roi in zip(bars, roi_values):
            width = bar.get_width()
            ax.text(
                width + (2 if width > 0 else -2),
                bar.get_y() + bar.get_height() / 2,
                f"{roi:.1f}%",
                ha="left" if width > 0 else "right",
                va="center",
                fontsize=10,
            )

        ax.axvline(x=0, color=GRID_COLOR, linestyle="-", linewidth=1)
        ax.set_xlabel("ROI (%)")
        ax.set_title("ROI by Sportsbook")
        ax.grid(True, alpha=0.3, axis="x")

        plt.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=100, facecolor=DARK_BG)
        buf.seek(0)
        plt.close()

        return buf.getvalue()

    except Exception as e:
        logger.error(f"ROI chart error: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# UNIT TRACKER
# ═══════════════════════════════════════════════════════════════════════════════


async def generate_unit_tracker(bets: List[Dict[str, Any]]) -> Optional[bytes]:
    """
    Generate units won/lost over time.

    Args:
        bets: List of bet records

    Returns:
        PNG bytes or None on error
    """
    try:
        _setup_dark_theme()

        resolved = [b for b in bets if b.get("result") != "pending"]
        if not resolved:
            return None

        # Sort by date ascending
        resolved = sorted(resolved, key=lambda b: b.get("date", ""))

        # Calculate units
        dates = []
        cumulative_units = []
        running_units = 0.0

        for bet in resolved:
            try:
                date_str = bet.get("date", "")
                if date_str:
                    date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    dates.append(date)

                    # Calculate units from stake and pnl
                    unit_size = float(bet.get("unit_size", 1.0))
                    pnl = float(bet.get("pnl", 0))
                    units = pnl / unit_size if unit_size > 0 else 0

                    running_units += units
                    cumulative_units.append(running_units)
            except Exception as e:
                logger.debug(f"Date parse error: {e}")
                continue

        if not dates:
            return None

        # Create figure
        fig, ax = plt.subplots(figsize=(12, 6))

        ax.plot(dates, cumulative_units, color=ACCENT_BLUE, linewidth=2.5, label="Cumulative Units")

        # Fill area
        for i in range(len(dates) - 1):
            color = ACCENT_GREEN if cumulative_units[i + 1] >= 0 else ACCENT_RED
            ax.fill_between(
                dates[i : i + 2],
                cumulative_units[i : i + 2],
                alpha=0.3,
                color=color,
            )

        ax.axhline(y=0, color=GRID_COLOR, linestyle="-", linewidth=1)
        ax.grid(True, alpha=0.3)
        ax.set_xlabel("Date")
        ax.set_ylabel("Units")
        ax.set_title("Unit Tracker Over Time")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)

        plt.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=100, facecolor=DARK_BG)
        buf.seek(0)
        plt.close()

        return buf.getvalue()

    except Exception as e:
        logger.error(f"Unit tracker chart error: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# BET DISTRIBUTION
# ═══════════════════════════════════════════════════════════════════════════════


async def generate_bet_distribution(bets: List[Dict[str, Any]]) -> Optional[bytes]:
    """
    Generate pie chart of bet types.

    Args:
        bets: List of bet records

    Returns:
        PNG bytes or None on error
    """
    try:
        _setup_dark_theme()

        if not bets:
            return None

        # Count by bet type
        bet_types = {}
        for bet in bets:
            bet_type = bet.get("bet_type", "unknown").capitalize()
            bet_types[bet_type] = bet_types.get(bet_type, 0) + 1

        if not bet_types:
            return None

        # Create figure
        fig, ax = plt.subplots(figsize=(10, 8))

        colors = [ACCENT_BLUE, ACCENT_GREEN, ACCENT_RED, "#ff9800", "#9c27b0"]
        colors = (colors * ((len(bet_types) // len(colors)) + 1))[: len(bet_types)]

        wedges, texts, autotexts = ax.pie(
            bet_types.values(),
            labels=bet_types.keys(),
            autopct="%1.1f%%",
            colors=colors,
            startangle=90,
        )

        # Format text
        for text in texts:
            text.set_color(DARK_FG)
            text.set_fontsize(11)

        for autotext in autotexts:
            autotext.set_color("black")
            autotext.set_fontsize(10)
            autotext.set_weight("bold")

        ax.set_title("Bet Distribution by Type")

        plt.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=100, facecolor=DARK_BG)
        buf.seek(0)
        plt.close()

        return buf.getvalue()

    except Exception as e:
        logger.error(f"Bet distribution chart error: {e}")
        return None

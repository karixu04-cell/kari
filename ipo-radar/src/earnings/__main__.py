"""CLI entry point: python -m src.earnings

Usage:
    python -m src.earnings analyze TICKER
    python -m src.earnings calendar TICKER1 TICKER2 ... [--days N]
"""

from __future__ import annotations

import argparse

from src.earnings.earnings_analyzer import analyze_earnings, format_earnings_analysis
from src.earnings.earnings_calendar import get_earnings_date, get_upcoming_earnings


def _cmd_analyze(args: argparse.Namespace) -> None:
    """Analyze latest earnings for a ticker."""
    ticker = args.ticker.upper()
    print(f"Analyzing earnings for {ticker}...")
    analysis = analyze_earnings(ticker)
    print(format_earnings_analysis(analysis))


def _cmd_calendar(args: argparse.Namespace) -> None:
    """Show upcoming earnings for a watchlist."""
    tickers = [t.upper() for t in args.tickers]
    days = args.days

    # Single ticker → just show next earnings date
    if len(tickers) == 1 and not args.batch:
        ticker = tickers[0]
        print(f"Looking up earnings date for {ticker}...")
        earnings_date = get_earnings_date(ticker)
        if earnings_date:
            delta = (earnings_date - __import__("datetime").date.today()).days
            print(f"  {ticker}: next earnings on {earnings_date} ({delta} days away)")
        else:
            print(f"  {ticker}: earnings date not available")
        return

    # Multiple tickers → batch check
    print(f"Checking upcoming earnings within {days} days for {len(tickers)} tickers...")
    upcoming = get_upcoming_earnings(tickers, days=days)

    if not upcoming:
        print("No upcoming earnings found in the specified window.")
        return

    print(f"\n{'Ticker':<10} {'Company':<30} {'Date':<12} {'Days'}")
    print("-" * 60)
    for ue in upcoming:
        print(f"{ue.ticker:<10} {ue.company_name[:28]:<30} {ue.earnings_date} {ue.days_until:>3}d")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Earnings Tracker - Track and analyze post-IPO earnings",
    )
    subparsers = parser.add_subparsers(dest="command", help="Sub-command")

    # analyze sub-command
    analyze_parser = subparsers.add_parser("analyze", help="Analyze latest earnings")
    analyze_parser.add_argument("ticker", help="Ticker symbol (e.g. CAVA)")

    # calendar sub-command
    cal_parser = subparsers.add_parser("calendar", help="Check upcoming earnings dates")
    cal_parser.add_argument("tickers", nargs="+", help="Ticker symbols")
    cal_parser.add_argument("--days", type=int, default=30, help="Days ahead (default: 30)")
    cal_parser.add_argument("--batch", action="store_true", help="Force batch mode")

    args = parser.parse_args()

    if args.command == "analyze":
        _cmd_analyze(args)
    elif args.command == "calendar":
        _cmd_calendar(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

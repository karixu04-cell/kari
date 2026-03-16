"""CLI entry point: python -m src.scorer

Usage:
    python -m src.scorer TICKER1 TICKER2 ...
    python -m src.scorer --ticker CAVA
    python -m src.scorer --file watchlist.txt
"""

from __future__ import annotations

import argparse
import sys

from src.scorer.daily_scan import format_full_report, run_daily_scan
from src.scorer.signal_aggregator import SignalAggregator


def _cmd_scan(tickers: list[str]) -> None:
    """Run daily scan on a list of tickers."""
    print(f"Running IPO Radar scan on {len(tickers)} tickers...\n")
    reports = run_daily_scan(tickers)
    print(format_full_report(reports))


def _cmd_single(ticker: str) -> None:
    """Run detailed report for a single ticker."""
    agg = SignalAggregator()
    print(f"Generating report for {ticker.upper()}...\n")
    report = agg.generate_report(ticker)

    print(f"{'=' * 55}")
    print(f"  {report.ticker} - {report.company or 'N/A'}")
    print(f"{'=' * 55}")
    print(f"  Price: ${report.current_price:.2f}" if report.current_price else "  Price: N/A")
    if report.ipo_price:
        print(f"  IPO Price: ${report.ipo_price:.2f}  (vs IPO: {report.price_vs_ipo:.2f}x)")
    if report.ipo_date:
        print(f"  IPO Date: {report.ipo_date}  ({report.days_since_ipo} days ago)")
    print(f"  Fundamental Score: {report.fundamental_score}/100")
    sent = report.sentiment
    print(f"  Sentiment: {sent.get('score', 0):+.2f} (buzz: {sent.get('buzz', 'N/A')})")
    print()

    # Windows
    print("  Windows:")
    for name, data in report.windows.items():
        label = name.replace("_", " ").title()
        if isinstance(data, dict):
            active = data.get("active", False)
            status = data.get("status", data.get("signal", data.get("breakout_signal", "")))
            if active or status:
                print(f"    {label}: {status or 'active'}")
    print()

    # Signal
    print(f"  >>> Overall Signal: {report.overall_signal}")
    if report.signal_reasons:
        print("  Reasons:")
        for r in report.signal_reasons:
            print(f"    + {r}")
    if report.risk_factors:
        print("  Risks:")
        for r in report.risk_factors:
            print(f"    ! {r}")
    print(f"{'=' * 55}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="IPO Radar - Composite Signal Scanner",
    )
    parser.add_argument("tickers", nargs="*", help="Ticker symbols to scan")
    parser.add_argument("--ticker", "-t", help="Single ticker for detailed report")
    parser.add_argument(
        "--file", "-f",
        help="File with tickers (one per line)",
    )

    args = parser.parse_args()

    # Single ticker mode
    if args.ticker:
        _cmd_single(args.ticker)
        return

    # Collect tickers
    tickers: list[str] = list(args.tickers)

    if args.file:
        try:
            with open(args.file) as fh:
                for line in fh:
                    t = line.strip().upper()
                    if t and not t.startswith("#"):
                        tickers.append(t)
        except FileNotFoundError:
            print(f"Error: file not found: {args.file}", file=sys.stderr)
            sys.exit(1)

    if not tickers:
        parser.print_help()
        sys.exit(1)

    _cmd_scan(tickers)


if __name__ == "__main__":
    main()

"""CLI entry point: python -m src.lockup

Usage:
    python -m src.lockup parse TICKER [--ipo-date YYYY-MM-DD] [--url S1_URL]
    python -m src.lockup calendar [--days N]
    python -m src.lockup impact TICKER
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta

from src.lockup.lockup_calendar import LockupCalendar, LockupUrgency, format_calendar_report
from src.lockup.lockup_parser import extract_lockup_info


def _demo_calendar() -> LockupCalendar:
    """Build a demo calendar with sample data for illustration."""
    cal = LockupCalendar()
    today = date.today()

    cal.add("DEMO1", "Demo Tech Inc", today - timedelta(days=175), 180,
            shares_locked=40_000_000, current_float=15_000_000)
    cal.add("DEMO2", "Demo Health Corp", today - timedelta(days=170), 180,
            shares_locked=25_000_000, current_float=30_000_000)
    cal.add("DEMO3", "Demo AI Labs", today - timedelta(days=90), 180,
            shares_locked=60_000_000, current_float=20_000_000)
    cal.add("DEMO4", "Demo Fintech", today - timedelta(days=178), 180,
            shares_locked=35_000_000, current_float=12_000_000)
    return cal


def cmd_parse(args: argparse.Namespace) -> None:
    """Parse lockup info from an S-1 filing."""
    ipo_date = None
    if args.ipo_date:
        ipo_date = date.fromisoformat(args.ipo_date)

    ticker = args.ticker.upper()

    # If a URL is provided, fetch the S-1 text
    s1_text = ""
    if args.url:
        try:
            import requests
            from src.screener.s1_parser import _strip_html_tags, _SEC_HEADERS
            resp = requests.get(args.url, headers=_SEC_HEADERS, timeout=20)
            resp.raise_for_status()
            s1_text = _strip_html_tags(resp.text)
        except Exception as exc:
            print(f"Error fetching S-1: {exc}", file=sys.stderr)
            sys.exit(1)
    else:
        # Try to look up via EDGAR
        try:
            from src.screener.s1_parser import _fetch_filing_html, _strip_html_tags
            html = _fetch_filing_html(s1_url=None, cik="", ticker=ticker, timeout=20)
            if html:
                s1_text = _strip_html_tags(html)
        except Exception as exc:
            print(f"EDGAR lookup failed: {exc}", file=sys.stderr)

    if not s1_text:
        print(f"Could not retrieve S-1 filing for {ticker}.")
        print("Try providing a direct URL with --url.\n")
        print("Showing fields with 'unknown' values:\n")
        detail = extract_lockup_info("", ipo_date=ipo_date)
    else:
        detail = extract_lockup_info(s1_text, ipo_date=ipo_date)

    # Print results
    print(f"{'='*55}")
    print(f"  Lockup Info: {ticker}")
    print(f"{'='*55}")
    print(f"  Lockup Days:            {detail.lockup_days or 'unknown'}")
    print(f"  Lockup Expiry:          {detail.lockup_expiry_date or 'unknown'}")
    print(f"  Shares Locked:          {f'{detail.shares_locked:,}' if detail.shares_locked else 'unknown'}")
    print(f"  Locked Holders:         {', '.join(detail.locked_holders) if detail.locked_holders else 'unknown'}")
    print(f"  Early Release:          {detail.early_release_provisions if detail.early_release_provisions is not None else 'unknown'}")
    print(f"  Total Outstanding:      {f'{detail.total_shares_outstanding:,}' if detail.total_shares_outstanding else 'unknown'}")
    print(f"  Float After Lockup:     {f'{detail.float_after_lockup:,}' if detail.float_after_lockup else 'unknown'}")
    print(f"{'='*55}")

    if detail.raw_snippets:
        print("\n  Matched text snippets:")
        for snip in detail.raw_snippets:
            print(f"    - \"{snip}\"")


def cmd_calendar(args: argparse.Namespace) -> None:
    """Show upcoming lockup expirations."""
    cal = _demo_calendar()
    print(format_calendar_report(cal, days=args.days))
    print("\nNote: Using demo data. Integrate with your IPO tracker for live data.")


def cmd_impact(args: argparse.Namespace) -> None:
    """Show supply impact for a ticker."""
    cal = _demo_calendar()
    ticker = args.ticker.upper()

    result = cal.get_supply_impact(ticker)
    if "error" in result:
        print(f"Ticker {ticker} not found in calendar.")
        print("Available tickers:", ", ".join(e.ticker for e in cal.all_entries))
        return

    print(f"{'='*50}")
    print(f"  Supply Impact: {ticker}")
    print(f"{'='*50}")
    print(f"  Days Remaining:    {result['days_remaining']}")
    print(f"  Urgency:           {result['urgency']}")
    print(f"  Locked Shares:     {result['locked_shares']:,}" if result['locked_shares'] else "  Locked Shares:     unknown")
    print(f"  Current Float:     {result['current_float']:,}" if result['current_float'] else "  Current Float:     unknown")
    ratio = result['ratio']
    print(f"  Impact Ratio:      {ratio:.1%}" if ratio else "  Impact Ratio:      unknown")
    print(f"  Severity:          {result['severity'].upper()}")
    print(f"{'='*50}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Lockup Tracker - Track IPO lockup period expirations",
    )
    subparsers = parser.add_subparsers(dest="command", help="Sub-command")

    # parse
    p_parse = subparsers.add_parser("parse", help="Parse lockup info from an S-1")
    p_parse.add_argument("ticker", help="Ticker symbol")
    p_parse.add_argument("--ipo-date", default=None, help="IPO date (YYYY-MM-DD)")
    p_parse.add_argument("--url", default=None, help="Direct URL to S-1 filing")

    # calendar
    p_cal = subparsers.add_parser("calendar", help="Show upcoming lockup expirations")
    p_cal.add_argument("--days", type=int, default=30, help="Look-ahead window (default: 30)")

    # impact
    p_impact = subparsers.add_parser("impact", help="Show supply impact for a ticker")
    p_impact.add_argument("ticker", help="Ticker symbol")

    args = parser.parse_args()

    if args.command == "parse":
        cmd_parse(args)
    elif args.command == "calendar":
        cmd_calendar(args)
    elif args.command == "impact":
        cmd_impact(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

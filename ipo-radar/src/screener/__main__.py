"""CLI entry point: python -m src.screener

Usage:
    python -m src.screener TICKER_OR_CIK [--url S1_URL]
"""

from __future__ import annotations

import argparse
import sys

from src.screener.quick_score import calculate_quick_score, format_report
from src.screener.s1_parser import extract_key_metrics


def main() -> None:
    parser = argparse.ArgumentParser(
        description="IPO Screener - Extract S-1 metrics and generate a quick score",
    )
    parser.add_argument(
        "identifier",
        help="Ticker symbol or CIK number",
    )
    parser.add_argument(
        "--url",
        default=None,
        help="Direct URL to the S-1 filing on EDGAR",
    )
    args = parser.parse_args()

    identifier = args.identifier.strip()

    # Determine if it's a CIK (all digits) or ticker
    if identifier.isdigit():
        cik, ticker = identifier, ""
        print(f"Looking up S-1 filing for CIK: {cik}")
    else:
        cik, ticker = "", identifier.upper()
        print(f"Looking up S-1 filing for ticker: {ticker}")

    print("Extracting key metrics from S-1...\n")

    metrics = extract_key_metrics(s1_url=args.url, cik=cik, ticker=ticker)

    if not metrics.revenues and not metrics.gross_margin and not metrics.lead_underwriter:
        print("Warning: Could not extract financial data from filing.")
        print("This may be due to network issues or an unsupported filing format.")
        print("Try providing a direct --url to the S-1 filing.\n")

    # Print extracted metrics summary
    print("--- Extracted Metrics ---")
    if metrics.revenues:
        rev_strs = [f"${r / 1e6:.1f}M" if r >= 1e6 else f"${r:,.0f}" for r in metrics.revenues]
        print(f"  Revenue (recent years): {', '.join(rev_strs)}")
    if metrics.revenue_yoy_growth:
        growth_strs = [f"{g * 100:.1f}%" for g in metrics.revenue_yoy_growth]
        print(f"  YoY Growth: {', '.join(growth_strs)}")
    if metrics.gross_margin is not None:
        print(f"  Gross Margin: {metrics.gross_margin * 100:.1f}%")
    if metrics.net_income is not None:
        label = "Net Income" if metrics.net_income >= 0 else "Net Loss"
        print(f"  {label}: ${abs(metrics.net_income) / 1e6:.1f}M")
    if metrics.cash_and_equivalents is not None:
        print(f"  Cash & Equivalents: ${metrics.cash_and_equivalents / 1e6:.1f}M")
    if metrics.cash_runway_months is not None:
        print(f"  Cash Runway: {metrics.cash_runway_months:.0f} months")
    if metrics.debt_to_assets is not None:
        print(f"  Debt/Assets: {metrics.debt_to_assets:.2f}")
    if metrics.lead_underwriter:
        tier = " (top-tier)" if metrics.is_top_underwriter else ""
        print(f"  Lead Underwriter: {metrics.lead_underwriter}{tier}")
    if metrics.implied_market_cap:
        print(f"  Implied Market Cap: ${metrics.implied_market_cap / 1e9:.2f}B")
    print()

    # Score and report
    result = calculate_quick_score(metrics)
    print(format_report(result))


if __name__ == "__main__":
    main()

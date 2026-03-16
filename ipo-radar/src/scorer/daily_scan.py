"""Daily Scan - Run the SignalAggregator across a watchlist and produce a report.

Usage::

    from src.scorer.daily_scan import run_daily_scan
    results = run_daily_scan(["CAVA", "ARM", "BIRK"])
"""

from __future__ import annotations

import logging
from datetime import datetime

from src.scorer.signal_aggregator import AggregatedReport, SignalAggregator

logger = logging.getLogger(__name__)

# Signal priority for sorting (lower = higher priority)
_SIGNAL_PRIORITY = {
    "STRONG_OPPORTUNITY": 0,
    "OPPORTUNITY": 1,
    "WATCH": 2,
    "NO_ACTION": 3,
}


def run_daily_scan(watchlist: list[str]) -> list[AggregatedReport]:
    """Run the full analysis pipeline on every ticker in the watchlist.

    Parameters
    ----------
    watchlist : list[str]
        List of ticker symbols to scan.

    Returns
    -------
    List of AggregatedReport, sorted by overall_signal priority
    (STRONG_OPPORTUNITY first, NO_ACTION last).
    """
    aggregator = SignalAggregator()
    reports: list[AggregatedReport] = []

    for ticker in watchlist:
        ticker = ticker.upper().strip()
        if not ticker:
            continue

        logger.info("Scanning %s...", ticker)
        try:
            report = aggregator.generate_report(ticker)
            reports.append(report)
        except Exception as exc:
            logger.error("Failed to scan %s: %s", ticker, exc)
            reports.append(AggregatedReport(
                ticker=ticker,
                overall_signal="NO_ACTION",
                signal_reasons=[],
                risk_factors=[f"Scan error: {exc}"],
            ))

    # Sort by signal priority, then alphabetically
    reports.sort(key=lambda r: (
        _SIGNAL_PRIORITY.get(r.overall_signal, 99),
        r.ticker,
    ))

    return reports


def format_scan_table(reports: list[AggregatedReport]) -> str:
    """Format scan results as a text table.

    Returns a compact table suitable for terminal output.
    """
    if not reports:
        return "No tickers scanned."

    lines = [
        f"{'=' * 78}",
        f"  IPO Radar - Daily Scan  |  {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"  {len(reports)} tickers scanned",
        f"{'=' * 78}",
        "",
        f"  {'Ticker':<8} {'Signal':<22} {'Price':>8} {'vs IPO':>8} {'Fund':>5} {'Sent':>6} {'Days':>5}",
        f"  {'-' * 72}",
    ]

    for r in reports:
        price_str = f"${r.current_price:.2f}" if r.current_price else "N/A"
        vs_ipo_str = f"{r.price_vs_ipo:.2f}x" if r.price_vs_ipo else "N/A"
        fund_str = f"{r.fundamental_score}" if r.fundamental_score else "-"
        sent_score = r.sentiment.get("score", 0.0)
        sent_str = f"{sent_score:+.2f}" if sent_score else "-"
        days_str = str(r.days_since_ipo) if r.days_since_ipo else "-"

        # Signal indicator
        sig_markers = {
            "STRONG_OPPORTUNITY": ">>> STRONG",
            "OPPORTUNITY": " >> OPPORTUNITY",
            "WATCH": "  > WATCH",
            "NO_ACTION": "    --",
        }
        sig_text = sig_markers.get(r.overall_signal, r.overall_signal)

        lines.append(
            f"  {r.ticker:<8} {sig_text:<22} {price_str:>8} {vs_ipo_str:>8} {fund_str:>5} {sent_str:>6} {days_str:>5}"
        )

    lines.append(f"  {'-' * 72}")
    lines.append("")

    return "\n".join(lines)


def format_scan_details(reports: list[AggregatedReport]) -> str:
    """Format detailed scan results for each ticker with signal/risk info."""
    if not reports:
        return ""

    lines = []

    # Only show details for non-NO_ACTION tickers, or all if few
    show_all = len(reports) <= 5
    detail_reports = [
        r for r in reports
        if show_all or r.overall_signal != "NO_ACTION"
    ]

    if not detail_reports:
        lines.append("  All tickers: NO_ACTION (no signals detected)")
        return "\n".join(lines)

    for r in detail_reports:
        lines.append(f"  --- {r.ticker} ({r.company or 'N/A'}) ---")
        lines.append(f"  Signal: {r.overall_signal}")

        if r.signal_reasons:
            lines.append("  Reasons:")
            for reason in r.signal_reasons:
                lines.append(f"    + {reason}")

        if r.risk_factors:
            lines.append("  Risks:")
            for risk in r.risk_factors:
                lines.append(f"    ! {risk}")

        # Window summary
        windows = r.windows
        if windows:
            active_windows = []
            base = windows.get("ipo_base_breakout", {})
            if base.get("active"):
                if base.get("breakout_signal"):
                    active_windows.append(f"Breakout({base['breakout_signal']})")
                elif base.get("base_detected"):
                    active_windows.append("Base forming")

            fdp = windows.get("first_day_pullback", {})
            if fdp.get("active") and fdp.get("signal"):
                active_windows.append(f"FDP({fdp['signal']})")

            lockup = windows.get("lockup_expiry", {})
            if lockup.get("status") in ("imminent", "warning"):
                active_windows.append(f"Lockup({lockup['status']}, {lockup.get('days_until', '?')}d)")

            earnings = windows.get("first_earnings", {})
            if earnings.get("days_until") is not None and earnings["days_until"] >= 0:
                active_windows.append(f"Earnings({earnings.get('days_until', '?')}d)")

            if active_windows:
                lines.append(f"  Windows: {' | '.join(active_windows)}")

        lines.append("")

    return "\n".join(lines)


def format_full_report(reports: list[AggregatedReport]) -> str:
    """Generate the complete daily scan output (table + details)."""
    parts = [
        format_scan_table(reports),
        format_scan_details(reports),
    ]

    # Summary line
    counts = {}
    for r in reports:
        counts[r.overall_signal] = counts.get(r.overall_signal, 0) + 1

    summary_parts = []
    for sig in ("STRONG_OPPORTUNITY", "OPPORTUNITY", "WATCH", "NO_ACTION"):
        if counts.get(sig, 0) > 0:
            summary_parts.append(f"{sig}: {counts[sig]}")

    parts.append(f"  Summary: {' | '.join(summary_parts)}")
    parts.append(f"{'=' * 78}")

    return "\n".join(parts)

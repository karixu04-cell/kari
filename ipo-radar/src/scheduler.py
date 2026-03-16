"""Scheduler - Automated periodic scanning and analysis tasks.

Uses the ``schedule`` library to run tasks at configured intervals:
- Pre-market (8:30 EST): full daily scan
- Intraday (every 15 min): breakout signal check
- Post-market: update pattern analysis
- Weekly (Sunday): refresh IPO calendar & lockup calendar

Usage::

    python -m src.scheduler          # run the scheduler loop
    python -m src.scheduler --once   # run all tasks once then exit
"""

from __future__ import annotations

import argparse
import logging
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import schedule
from dotenv import load_dotenv

from src.scorer.daily_scan import run_daily_scan
from src.scorer.signal_aggregator import AggregatedReport, SignalAggregator

load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

EST = ZoneInfo("America/New_York")

# ---------------------------------------------------------------------------
# Default watchlist (override via WATCHLIST env var, comma-separated)
# ---------------------------------------------------------------------------

_DEFAULT_WATCHLIST = ["CAVA", "ARM", "BIRK", "CART", "KPLT"]


def _get_watchlist() -> list[str]:
    env = os.getenv("WATCHLIST", "")
    if env.strip():
        return [t.strip().upper() for t in env.split(",") if t.strip()]
    return list(_DEFAULT_WATCHLIST)


# ---------------------------------------------------------------------------
# Notification helper (lazy import to avoid hard dependency)
# ---------------------------------------------------------------------------


def _notify(reports: list[AggregatedReport]) -> None:
    """Send notifications for actionable signals."""
    try:
        from src.notifier import TelegramNotifier

        notifier = TelegramNotifier()
        if not notifier.is_configured():
            return
        notifier.process_reports(reports)
    except ImportError:
        logger.debug("Notifier not available, skipping notifications")
    except Exception as exc:
        logger.warning("Notification failed: %s", exc)


# ---------------------------------------------------------------------------
# Scheduled tasks
# ---------------------------------------------------------------------------


def task_daily_scan() -> list[AggregatedReport]:
    """Pre-market full scan: run daily_scan on the entire watchlist."""
    logger.info("=== DAILY SCAN START ===")
    watchlist = _get_watchlist()
    reports = run_daily_scan(watchlist)

    strong = [r for r in reports if r.overall_signal == "STRONG_OPPORTUNITY"]
    opp = [r for r in reports if r.overall_signal == "OPPORTUNITY"]
    watch = [r for r in reports if r.overall_signal == "WATCH"]

    logger.info(
        "Daily scan complete: %d tickers | STRONG=%d OPP=%d WATCH=%d",
        len(reports), len(strong), len(opp), len(watch),
    )

    _notify(reports)
    return reports


def task_check_breakouts() -> list[AggregatedReport]:
    """Intraday check: look for breakout signals only."""
    logger.info("--- Breakout check ---")
    watchlist = _get_watchlist()
    aggregator = SignalAggregator()

    alerts: list[AggregatedReport] = []
    for ticker in watchlist:
        try:
            report = aggregator.generate_report(ticker)
            base = report.windows.get("ipo_base_breakout", {})
            if base.get("breakout_signal"):
                logger.info("BREAKOUT detected: %s (%s)", ticker, base["breakout_signal"])
                alerts.append(report)
        except Exception as exc:
            logger.debug("Breakout check failed for %s: %s", ticker, exc)

    if alerts:
        _notify(alerts)

    logger.info("Breakout check done: %d alerts", len(alerts))
    return alerts


def task_update_patterns() -> None:
    """Post-market: refresh pattern analysis (base detection) for all tickers."""
    logger.info("--- Pattern update ---")
    watchlist = _get_watchlist()
    aggregator = SignalAggregator()

    for ticker in watchlist:
        try:
            aggregator.generate_report(ticker)
            logger.debug("Updated patterns for %s", ticker)
        except Exception as exc:
            logger.debug("Pattern update failed for %s: %s", ticker, exc)

    logger.info("Pattern update complete for %d tickers", len(watchlist))


def task_weekly_refresh() -> None:
    """Weekly: update IPO calendar and lockup calendar."""
    logger.info("=== WEEKLY REFRESH ===")

    # Refresh IPO calendar
    try:
        from src.radar import fetch_upcoming_ipos
        events = fetch_upcoming_ipos()
        logger.info("IPO calendar refreshed: %d upcoming events", len(events))
    except Exception as exc:
        logger.warning("IPO calendar refresh failed: %s", exc)

    # Refresh lockup data for watchlist
    watchlist = _get_watchlist()
    aggregator = SignalAggregator()
    lockup_alerts: list[AggregatedReport] = []

    for ticker in watchlist:
        try:
            report = aggregator.generate_report(ticker)
            lockup = report.windows.get("lockup_expiry", {})
            if lockup.get("status") in ("imminent", "warning"):
                lockup_alerts.append(report)
        except Exception as exc:
            logger.debug("Lockup refresh failed for %s: %s", ticker, exc)

    if lockup_alerts:
        _notify(lockup_alerts)

    logger.info("Weekly refresh complete. Lockup alerts: %d", len(lockup_alerts))


# ---------------------------------------------------------------------------
# Schedule setup
# ---------------------------------------------------------------------------


def setup_schedule() -> None:
    """Configure the schedule with all recurring tasks."""
    # Pre-market daily scan: 8:30 AM EST
    schedule.every().day.at("08:30", EST).do(task_daily_scan)

    # Intraday breakout check: every 15 min during market hours (9:30-16:00 EST)
    schedule.every(15).minutes.do(_intraday_guard(task_check_breakouts))

    # Post-market pattern update: 4:30 PM EST
    schedule.every().day.at("16:30", EST).do(task_update_patterns)

    # Weekly refresh: Sunday 6:00 PM EST
    schedule.every().sunday.at("18:00", EST).do(task_weekly_refresh)

    logger.info("Schedule configured:")
    logger.info("  - Daily scan: 08:30 EST")
    logger.info("  - Breakout check: every 15 min (market hours)")
    logger.info("  - Pattern update: 16:30 EST")
    logger.info("  - Weekly refresh: Sunday 18:00 EST")


def _intraday_guard(func):
    """Wrapper that only runs the task during US market hours."""
    def wrapper():
        now_est = datetime.now(EST)
        hour = now_est.hour
        weekday = now_est.weekday()  # 0=Mon, 6=Sun

        # Only run Mon-Fri, 9:30-16:00 EST
        if weekday >= 5:
            return
        if hour < 9 or (hour == 9 and now_est.minute < 30):
            return
        if hour >= 16:
            return

        return func()

    wrapper.__name__ = getattr(func, "__name__", "guarded_task")
    return wrapper


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def run_loop() -> None:
    """Run the scheduler loop indefinitely."""
    setup_schedule()
    logger.info("Scheduler running. Press Ctrl+C to stop.")

    while True:
        schedule.run_pending()
        time.sleep(30)


def run_once() -> None:
    """Run all tasks once immediately (for testing / manual trigger)."""
    logger.info("Running all tasks once...")
    task_daily_scan()
    task_check_breakouts()
    task_update_patterns()
    task_weekly_refresh()
    logger.info("All tasks completed.")


def main() -> None:
    parser = argparse.ArgumentParser(description="IPO Radar Scheduler")
    parser.add_argument("--once", action="store_true", help="Run all tasks once then exit")
    args = parser.parse_args()

    if args.once:
        run_once()
    else:
        run_loop()


if __name__ == "__main__":
    main()

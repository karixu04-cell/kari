"""Earnings Calendar - Track upcoming earnings dates via yfinance.

Provides functions to look up the next earnings date for a ticker
and batch-check a watchlist for upcoming reports.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import yfinance as yf

logger = logging.getLogger(__name__)


@dataclass
class UpcomingEarnings:
    """An upcoming earnings event."""

    ticker: str
    earnings_date: date
    company_name: str = ""
    days_until: int = 0

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "earnings_date": self.earnings_date.isoformat(),
            "company_name": self.company_name,
            "days_until": self.days_until,
        }


def get_earnings_date(ticker: str) -> date | None:
    """Get the next earnings date for a ticker from yfinance.

    Parameters
    ----------
    ticker : str
        Stock ticker symbol (e.g. "CAVA").

    Returns
    -------
    The next earnings date, or None if unavailable.
    """
    try:
        stock = yf.Ticker(ticker)
        cal = stock.calendar
        if cal is None or cal.empty if hasattr(cal, "empty") else not cal:
            return None

        # yfinance calendar can be a dict or DataFrame
        if isinstance(cal, dict):
            earnings_date_val = cal.get("Earnings Date")
            if earnings_date_val is None:
                return None
            # Can be a list of dates or a single date
            if isinstance(earnings_date_val, list):
                earnings_date_val = earnings_date_val[0] if earnings_date_val else None
            if earnings_date_val is None:
                return None
            if isinstance(earnings_date_val, datetime):
                return earnings_date_val.date()
            if isinstance(earnings_date_val, date):
                return earnings_date_val
            return None
        else:
            # DataFrame format
            if "Earnings Date" in cal.index:
                val = cal.loc["Earnings Date"].iloc[0]
                if hasattr(val, "date"):
                    return val.date()
                return None
            return None

    except Exception as exc:
        logger.warning("Failed to get earnings date for %s: %s", ticker, exc)
        return None


def get_upcoming_earnings(
    watchlist: list[str],
    days: int = 30,
) -> list[UpcomingEarnings]:
    """Batch-check a watchlist for upcoming earnings within N days.

    Parameters
    ----------
    watchlist : list[str]
        List of ticker symbols to check.
    days : int
        How many days ahead to look (default 30).

    Returns
    -------
    List of UpcomingEarnings, sorted by earnings_date (soonest first).
    """
    today = date.today()
    cutoff = today + timedelta(days=days)
    results: list[UpcomingEarnings] = []

    for ticker in watchlist:
        ticker = ticker.upper().strip()
        if not ticker:
            continue

        earnings_date = get_earnings_date(ticker)
        if earnings_date is None:
            continue

        if today <= earnings_date <= cutoff:
            # Try to get company name
            company_name = ""
            try:
                info = yf.Ticker(ticker).info
                company_name = info.get("shortName", "") or info.get("longName", "")
            except Exception:
                pass

            days_until = (earnings_date - today).days
            results.append(UpcomingEarnings(
                ticker=ticker,
                earnings_date=earnings_date,
                company_name=company_name,
                days_until=days_until,
            ))

    results.sort(key=lambda x: x.earnings_date)
    return results

"""IPO Calendar - Fetch upcoming IPOs from SEC EDGAR and Nasdaq."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import requests

logger = logging.getLogger(__name__)

_SEC_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
_NASDAQ_CALENDAR_URL = "https://api.nasdaq.com/api/ipo/calendar"

_REQUEST_HEADERS = {
    "User-Agent": "IPORadar/0.1 (research tool)",
    "Accept": "application/json",
}


@dataclass
class IPOEvent:
    """Standardised representation of an upcoming or recent IPO."""

    ticker: str
    company_name: str
    expected_date: date | None = None
    exchange: str = ""
    price_range: tuple[float, float] | None = None
    shares_offered: int | None = None
    lead_underwriter: str = ""
    status: str = "upcoming"  # upcoming | priced | trading | withdrawn
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# SEC EDGAR
# ---------------------------------------------------------------------------

def fetch_upcoming_ipos(
    form_types: tuple[str, ...] = ("S-1", "424B4"),
    lookback_days: int = 30,
    timeout: int = 15,
) -> list[IPOEvent]:
    """Fetch recent S-1 / 424B4 filings from the SEC EDGAR full-text search.

    Returns a list of :class:`IPOEvent` objects built from the filing metadata.
    """
    end_date = date.today()
    start_date = end_date - timedelta(days=lookback_days)

    events: list[IPOEvent] = []

    for form_type in form_types:
        params = {
            "q": f'"{form_type}"',
            "dateRange": "custom",
            "startdt": start_date.isoformat(),
            "enddt": end_date.isoformat(),
        }

        try:
            resp = requests.get(
                _SEC_SEARCH_URL,
                params=params,
                headers=_REQUEST_HEADERS,
                timeout=timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            logger.warning("SEC EDGAR request failed for %s: %s", form_type, exc)
            continue

        hits = data.get("hits", {}).get("hits", [])
        for hit in hits:
            source = hit.get("_source", {})
            event = _parse_sec_hit(source, form_type)
            if event is not None:
                events.append(event)

    return events


def _parse_sec_hit(source: dict, form_type: str) -> IPOEvent | None:
    """Convert a single SEC EDGAR search hit into an IPOEvent."""
    company_name = source.get("display_names", [None])[0] if source.get("display_names") else source.get("entity_name", "")
    if not company_name:
        return None

    ticker = ""
    tickers = source.get("tickers", [])
    if tickers:
        ticker = tickers[0]

    filed_str = source.get("file_date", "")
    filed_date = None
    if filed_str:
        try:
            filed_date = datetime.strptime(filed_str, "%Y-%m-%d").date()
        except ValueError:
            pass

    return IPOEvent(
        ticker=ticker,
        company_name=company_name,
        expected_date=filed_date,
        status="upcoming",
        metadata={"form_type": form_type, "file_num": source.get("file_num", "")},
    )


# ---------------------------------------------------------------------------
# Nasdaq IPO Calendar
# ---------------------------------------------------------------------------

def fetch_nasdaq_calendar(
    cal_date: date | None = None,
    timeout: int = 15,
) -> list[IPOEvent]:
    """Fetch the Nasdaq IPO calendar for a given date (defaults to today).

    The Nasdaq API returns upcoming, priced, and filed IPOs.
    """
    if cal_date is None:
        cal_date = date.today()

    params = {"date": cal_date.strftime("%Y-%m")}
    headers = {
        **_REQUEST_HEADERS,
        "Accept": "application/json, text/plain, */*",
    }

    try:
        resp = requests.get(
            _NASDAQ_CALENDAR_URL,
            params=params,
            headers=headers,
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        logger.warning("Nasdaq calendar request failed: %s", exc)
        return []

    events: list[IPOEvent] = []
    body = data.get("data", {})

    for section in ("upcoming", "priced", "filed"):
        rows = body.get(section, {}).get("rows", [])
        for row in rows:
            event = _parse_nasdaq_row(row, section)
            if event is not None:
                events.append(event)

    return events


def _parse_nasdaq_row(row: dict, section: str) -> IPOEvent | None:
    """Convert a Nasdaq calendar row into an IPOEvent."""
    company_name = row.get("companyName", "")
    if not company_name:
        return None

    ticker = row.get("proposedTickerSymbol", "") or row.get("ticker", "")
    exchange = row.get("proposedExchange", "") or row.get("exchange", "")

    expected_date = None
    date_str = row.get("expectedPriceDate", "") or row.get("pricedDate", "")
    if date_str:
        for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
            try:
                expected_date = datetime.strptime(date_str, fmt).date()
                break
            except ValueError:
                continue

    price_range = _parse_price_range(row.get("proposedSharePrice", ""))

    shares_offered = None
    shares_str = row.get("sharesOffered", "")
    if shares_str:
        try:
            shares_offered = int(shares_str.replace(",", ""))
        except (ValueError, AttributeError):
            pass

    status_map = {"upcoming": "upcoming", "priced": "priced", "filed": "upcoming"}
    status = status_map.get(section, "upcoming")

    return IPOEvent(
        ticker=ticker,
        company_name=company_name,
        expected_date=expected_date,
        exchange=exchange,
        price_range=price_range,
        shares_offered=shares_offered,
        lead_underwriter=row.get("leadUnderwriters", ""),
        status=status,
        metadata={"source": "nasdaq", "section": section},
    )


def _parse_price_range(price_str: str) -> tuple[float, float] | None:
    """Parse a price range string like '$14.00-$16.00' into a tuple."""
    if not price_str:
        return None
    cleaned = price_str.replace("$", "").replace(" ", "")
    if "-" in cleaned:
        parts = cleaned.split("-", 1)
        try:
            return (float(parts[0]), float(parts[1]))
        except ValueError:
            return None
    try:
        val = float(cleaned)
        return (val, val)
    except ValueError:
        return None

"""Tests for the radar module (ipo_calendar + tracker)."""

from __future__ import annotations

import json
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

from src.radar.ipo_calendar import (
    IPOEvent,
    _parse_nasdaq_row,
    _parse_price_range,
    _parse_sec_hit,
    fetch_nasdaq_calendar,
    fetch_upcoming_ipos,
)
from src.radar.tracker import IPOTracker


# ======================================================================
# ipo_calendar – unit helpers
# ======================================================================


class TestParsePriceRange:
    def test_range(self):
        assert _parse_price_range("$14.00-$16.00") == (14.0, 16.0)

    def test_single(self):
        assert _parse_price_range("$20.00") == (20.0, 20.0)

    def test_empty(self):
        assert _parse_price_range("") is None

    def test_none(self):
        assert _parse_price_range(None) is None

    def test_no_dollar(self):
        assert _parse_price_range("10-12") == (10.0, 12.0)

    def test_invalid(self):
        assert _parse_price_range("abc") is None


class TestParseSecHit:
    def test_basic(self):
        source = {
            "display_names": ["Acme Corp"],
            "tickers": ["ACME"],
            "file_date": "2026-03-01",
            "file_num": "333-12345",
        }
        event = _parse_sec_hit(source, "S-1")
        assert event is not None
        assert event.ticker == "ACME"
        assert event.company_name == "Acme Corp"
        assert event.expected_date == date(2026, 3, 1)
        assert event.metadata["form_type"] == "S-1"

    def test_missing_name_returns_none(self):
        assert _parse_sec_hit({}, "S-1") is None

    def test_fallback_entity_name(self):
        source = {"entity_name": "Beta Inc", "tickers": [], "file_date": ""}
        event = _parse_sec_hit(source, "424B4")
        assert event is not None
        assert event.company_name == "Beta Inc"
        assert event.ticker == ""
        assert event.expected_date is None

    def test_invalid_date(self):
        source = {"display_names": ["Test"], "file_date": "not-a-date"}
        event = _parse_sec_hit(source, "S-1")
        assert event is not None
        assert event.expected_date is None


class TestParseNasdaqRow:
    def test_upcoming(self):
        row = {
            "companyName": "Widget Co",
            "proposedTickerSymbol": "WDGT",
            "proposedExchange": "NASDAQ",
            "expectedPriceDate": "04/15/2026",
            "proposedSharePrice": "$18.00-$20.00",
            "sharesOffered": "5,000,000",
            "leadUnderwriters": "Goldman Sachs",
        }
        event = _parse_nasdaq_row(row, "upcoming")
        assert event is not None
        assert event.ticker == "WDGT"
        assert event.company_name == "Widget Co"
        assert event.exchange == "NASDAQ"
        assert event.expected_date == date(2026, 4, 15)
        assert event.price_range == (18.0, 20.0)
        assert event.shares_offered == 5_000_000
        assert event.lead_underwriter == "Goldman Sachs"
        assert event.status == "upcoming"

    def test_priced(self):
        row = {
            "companyName": "Priced Inc",
            "proposedTickerSymbol": "PRC",
            "pricedDate": "2026-03-10",
        }
        event = _parse_nasdaq_row(row, "priced")
        assert event is not None
        assert event.status == "priced"
        assert event.expected_date == date(2026, 3, 10)

    def test_empty_name(self):
        assert _parse_nasdaq_row({"companyName": ""}, "filed") is None


# ======================================================================
# ipo_calendar – fetch functions (mocked HTTP)
# ======================================================================


class TestFetchUpcomingIpos:
    @patch("src.radar.ipo_calendar.requests.get")
    def test_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "hits": {
                "hits": [
                    {
                        "_source": {
                            "display_names": ["Alpha Corp"],
                            "tickers": ["ALPH"],
                            "file_date": "2026-03-05",
                            "file_num": "333-99999",
                        }
                    }
                ]
            }
        }
        mock_get.return_value = mock_resp

        events = fetch_upcoming_ipos(form_types=("S-1",))
        assert len(events) == 1
        assert events[0].ticker == "ALPH"
        assert events[0].company_name == "Alpha Corp"

    @patch("src.radar.ipo_calendar.requests.get")
    def test_request_failure_returns_empty(self, mock_get):
        import requests as req

        mock_get.side_effect = req.ConnectionError("network down")
        events = fetch_upcoming_ipos()
        assert events == []

    @patch("src.radar.ipo_calendar.requests.get")
    def test_empty_hits(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"hits": {"hits": []}}
        mock_get.return_value = mock_resp

        events = fetch_upcoming_ipos(form_types=("S-1",))
        assert events == []


class TestFetchNasdaqCalendar:
    @patch("src.radar.ipo_calendar.requests.get")
    def test_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": {
                "upcoming": {
                    "rows": [
                        {
                            "companyName": "Demo Inc",
                            "proposedTickerSymbol": "DEMO",
                            "proposedExchange": "NYSE",
                            "expectedPriceDate": "03/20/2026",
                            "proposedSharePrice": "$12.00-$14.00",
                            "sharesOffered": "10,000,000",
                            "leadUnderwriters": "Morgan Stanley",
                        }
                    ]
                },
                "priced": {"rows": []},
                "filed": {"rows": []},
            }
        }
        mock_get.return_value = mock_resp

        events = fetch_nasdaq_calendar()
        assert len(events) == 1
        assert events[0].ticker == "DEMO"

    @patch("src.radar.ipo_calendar.requests.get")
    def test_failure_returns_empty(self, mock_get):
        import requests as req

        mock_get.side_effect = req.Timeout("timeout")
        assert fetch_nasdaq_calendar() == []


# ======================================================================
# tracker – IPOTracker with in-memory SQLite
# ======================================================================


@pytest.fixture
def tracker(tmp_path):
    """Create a tracker backed by a temporary SQLite database."""
    db = tmp_path / "test.db"
    return IPOTracker(db_path=db)


class TestIPOTrackerAddAndGet:
    def test_add_and_get_by_ticker(self, tracker):
        record = tracker.add_ipo(
            ticker="TEST",
            company_name="Test Corp",
            expected_date=date.today() + timedelta(days=7),
            exchange="NASDAQ",
            price_range=(15.0, 17.0),
            shares_offered=1_000_000,
        )
        assert record.ticker == "TEST"
        assert record.id is not None

        fetched = tracker.get_by_ticker("test")  # case-insensitive lookup
        assert fetched is not None
        assert fetched.company_name == "Test Corp"
        assert fetched.price_low == 15.0
        assert fetched.price_high == 17.0

    def test_get_nonexistent(self, tracker):
        assert tracker.get_by_ticker("NOPE") is None


class TestIPOTrackerUpdateStatus:
    def test_update_existing(self, tracker):
        tracker.add_ipo(ticker="UPD", company_name="Update Inc")
        assert tracker.update_status("UPD", "priced", offer_price=20.0)
        rec = tracker.get_by_ticker("UPD")
        assert rec.status == "priced"
        assert rec.offer_price == 20.0

    def test_update_nonexistent(self, tracker):
        assert tracker.update_status("MISSING", "priced") is False


class TestIPOTrackerWatchlist:
    def test_watchlist(self, tracker):
        tracker.add_ipo(ticker="A", company_name="A Inc", status="upcoming")
        tracker.add_ipo(ticker="B", company_name="B Inc", status="priced")
        tracker.add_ipo(ticker="C", company_name="C Inc", status="trading")
        tracker.add_ipo(ticker="D", company_name="D Inc", status="withdrawn")

        watchlist = tracker.get_watchlist()
        tickers = {r.ticker for r in watchlist}
        assert tickers == {"A", "B"}

    def test_watchlist_custom_statuses(self, tracker):
        tracker.add_ipo(ticker="X", company_name="X", status="trading")
        result = tracker.get_watchlist(statuses=("trading",))
        assert len(result) == 1


class TestIPOTrackerUpcoming:
    def test_upcoming_within_range(self, tracker):
        today = date.today()
        tracker.add_ipo(ticker="SOON", company_name="Soon Corp", expected_date=today + timedelta(days=3))
        tracker.add_ipo(ticker="LATER", company_name="Later Corp", expected_date=today + timedelta(days=30))
        tracker.add_ipo(ticker="PAST", company_name="Past Corp", expected_date=today - timedelta(days=5))

        upcoming = tracker.get_upcoming(days=14)
        tickers = [r.ticker for r in upcoming]
        assert "SOON" in tickers
        assert "LATER" not in tickers
        assert "PAST" not in tickers

    def test_upcoming_empty(self, tracker):
        assert tracker.get_upcoming() == []


class TestIPOTrackerImportEvents:
    def test_import_new(self, tracker):
        events = [
            IPOEvent(ticker="IMP1", company_name="Import One", expected_date=date.today()),
            IPOEvent(ticker="IMP2", company_name="Import Two"),
        ]
        count = tracker.import_events(events)
        assert count == 2
        assert tracker.get_by_ticker("IMP1") is not None

    def test_import_skips_duplicates(self, tracker):
        tracker.add_ipo(ticker="DUP", company_name="Dup Corp")
        events = [
            IPOEvent(ticker="DUP", company_name="Dup Corp Again"),
            IPOEvent(ticker="NEW", company_name="New Corp"),
        ]
        count = tracker.import_events(events)
        assert count == 1  # only NEW inserted

    def test_import_skips_empty_ticker(self, tracker):
        events = [IPOEvent(ticker="", company_name="No Ticker")]
        assert tracker.import_events(events) == 0

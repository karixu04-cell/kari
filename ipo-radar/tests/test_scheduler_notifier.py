"""Tests for scheduler and notifier modules."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from src.notifier import TelegramNotifier
from src.scheduler import (
    _get_watchlist,
    _intraday_guard,
    task_check_breakouts,
    task_daily_scan,
)
from src.scorer.signal_aggregator import AggregatedReport


# ======================================================================
# notifier.py – TelegramNotifier
# ======================================================================


class TestTelegramNotifier:
    def test_is_configured_false_by_default(self):
        notifier = TelegramNotifier(bot_token="", chat_id="")
        assert notifier.is_configured() is False

    def test_is_configured_true(self):
        notifier = TelegramNotifier(bot_token="123:ABC", chat_id="456")
        assert notifier.is_configured() is True

    def test_is_configured_partial(self):
        notifier = TelegramNotifier(bot_token="123:ABC", chat_id="")
        assert notifier.is_configured() is False

    @patch("src.notifier.requests.post")
    def test_send_message_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True}
        mock_post.return_value = mock_resp

        notifier = TelegramNotifier(bot_token="123:ABC", chat_id="456")
        result = notifier.send_message("test message")
        assert result is True
        mock_post.assert_called_once()

        # Verify payload
        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["chat_id"] == "456"
        assert payload["text"] == "test message"
        assert payload["parse_mode"] == "HTML"

    @patch("src.notifier.requests.post")
    def test_send_message_failure(self, mock_post):
        mock_post.side_effect = Exception("Connection error")

        notifier = TelegramNotifier(bot_token="123:ABC", chat_id="456")
        result = notifier.send_message("test")
        assert result is False

    def test_send_message_not_configured(self):
        notifier = TelegramNotifier(bot_token="", chat_id="")
        result = notifier.send_message("test")
        assert result is False

    @patch("src.notifier.requests.post")
    def test_send_message_api_error(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": False, "description": "Bad Request"}
        mock_post.return_value = mock_resp

        notifier = TelegramNotifier(bot_token="123:ABC", chat_id="456")
        result = notifier.send_message("test")
        assert result is False


# ======================================================================
# notifier.py – _build_messages
# ======================================================================


class TestBuildMessages:
    def setup_method(self):
        self.notifier = TelegramNotifier(bot_token="test", chat_id="test")

    def test_strong_opportunity_message(self):
        report = AggregatedReport(
            ticker="CAVA",
            company="CAVA Group",
            current_price=80.0,
            ipo_price=22.0,
            price_vs_ipo=3.636,
            fundamental_score=75,
            sentiment={"score": 0.5},
            overall_signal="STRONG_OPPORTUNITY",
            signal_reasons=["Strong breakout from IPO base"],
            risk_factors=["Lockup approaching"],
            windows={
                "ipo_base_breakout": {"breakout_signal": None},
                "lockup_expiry": {"status": "safe"},
                "first_earnings": {},
            },
        )
        messages = self.notifier._build_messages(report)
        assert len(messages) >= 1
        assert "STRONG OPPORTUNITY" in messages[0]
        assert "CAVA" in messages[0]
        assert "$80.00" in messages[0]

    def test_breakout_message(self):
        report = AggregatedReport(
            ticker="ARM",
            company="Arm Holdings",
            current_price=120.0,
            overall_signal="OPPORTUNITY",
            windows={
                "ipo_base_breakout": {"breakout_signal": "strong"},
                "lockup_expiry": {"status": "safe"},
                "first_earnings": {},
            },
        )
        messages = self.notifier._build_messages(report)
        assert any("BREAKOUT" in m for m in messages)
        assert any("strong" in m for m in messages)

    def test_lockup_imminent_message(self):
        report = AggregatedReport(
            ticker="BIRK",
            company="Birkenstock",
            overall_signal="WATCH",
            windows={
                "ipo_base_breakout": {},
                "lockup_expiry": {"status": "imminent", "days_until": 2, "supply_impact_pct": 65.0},
                "first_earnings": {},
            },
        )
        messages = self.notifier._build_messages(report)
        assert any("LOCKUP" in m for m in messages)
        assert any("2 days" in m for m in messages)
        assert any("65%" in m for m in messages)

    def test_earnings_alert_message(self):
        report = AggregatedReport(
            ticker="CART",
            company="Instacart",
            current_price=35.0,
            fundamental_score=60,
            overall_signal="WATCH",
            windows={
                "ipo_base_breakout": {},
                "lockup_expiry": {"status": "safe"},
                "first_earnings": {"days_until": 2, "earnings_signal": None},
            },
        )
        messages = self.notifier._build_messages(report)
        assert any("EARNINGS" in m for m in messages)
        assert any("2 days" in m for m in messages)

    def test_no_alert_for_no_action(self):
        report = AggregatedReport(
            ticker="XYZ",
            overall_signal="NO_ACTION",
            windows={
                "ipo_base_breakout": {},
                "lockup_expiry": {"status": "safe"},
                "first_earnings": {},
            },
        )
        messages = self.notifier._build_messages(report)
        assert len(messages) == 0

    def test_multiple_alerts(self):
        """STRONG_OPPORTUNITY with breakout should produce 2 messages."""
        report = AggregatedReport(
            ticker="TEST",
            company="Test Corp",
            current_price=50.0,
            ipo_price=25.0,
            price_vs_ipo=2.0,
            fundamental_score=70,
            sentiment={"score": 0.5},
            overall_signal="STRONG_OPPORTUNITY",
            signal_reasons=["Breakout"],
            risk_factors=[],
            windows={
                "ipo_base_breakout": {"breakout_signal": "strong"},
                "lockup_expiry": {"status": "safe"},
                "first_earnings": {},
            },
        )
        messages = self.notifier._build_messages(report)
        assert len(messages) == 2  # STRONG_OPPORTUNITY + BREAKOUT


# ======================================================================
# notifier.py – process_reports
# ======================================================================


class TestProcessReports:
    @patch("src.notifier.requests.post")
    def test_process_sends_notifications(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True}
        mock_post.return_value = mock_resp

        notifier = TelegramNotifier(bot_token="123:ABC", chat_id="456")
        reports = [
            AggregatedReport(
                ticker="TEST",
                company="Test",
                current_price=50.0,
                ipo_price=25.0,
                price_vs_ipo=2.0,
                fundamental_score=70,
                sentiment={"score": 0.5},
                overall_signal="STRONG_OPPORTUNITY",
                signal_reasons=["Test reason"],
                windows={
                    "ipo_base_breakout": {},
                    "lockup_expiry": {"status": "safe"},
                    "first_earnings": {},
                },
            ),
        ]
        sent = notifier.process_reports(reports)
        assert sent == 1

    def test_process_not_configured(self):
        notifier = TelegramNotifier(bot_token="", chat_id="")
        sent = notifier.process_reports([])
        assert sent == 0


# ======================================================================
# scheduler.py – _get_watchlist
# ======================================================================


class TestGetWatchlist:
    @patch.dict("os.environ", {"WATCHLIST": "AAPL,GOOG,MSFT"})
    def test_from_env(self):
        wl = _get_watchlist()
        assert wl == ["AAPL", "GOOG", "MSFT"]

    @patch.dict("os.environ", {"WATCHLIST": ""})
    def test_default_watchlist(self):
        wl = _get_watchlist()
        assert "CAVA" in wl
        assert len(wl) >= 3

    @patch.dict("os.environ", {"WATCHLIST": " amd , nvda "})
    def test_strips_whitespace(self):
        wl = _get_watchlist()
        assert wl == ["AMD", "NVDA"]


# ======================================================================
# scheduler.py – _intraday_guard
# ======================================================================


class TestIntradayGuard:
    def test_blocks_weekend(self):
        func = MagicMock(return_value="ran")
        guarded = _intraday_guard(func)

        # Saturday at noon EST
        with patch("src.scheduler.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.hour = 12
            mock_now.minute = 0
            mock_now.weekday.return_value = 5  # Saturday
            mock_dt.now.return_value = mock_now

            result = guarded()
            func.assert_not_called()
            assert result is None

    def test_blocks_premarket(self):
        func = MagicMock(return_value="ran")
        guarded = _intraday_guard(func)

        with patch("src.scheduler.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.hour = 8
            mock_now.minute = 0
            mock_now.weekday.return_value = 1  # Tuesday
            mock_dt.now.return_value = mock_now

            result = guarded()
            func.assert_not_called()

    def test_allows_market_hours(self):
        func = MagicMock(return_value="ran")
        guarded = _intraday_guard(func)

        with patch("src.scheduler.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.hour = 11
            mock_now.minute = 30
            mock_now.weekday.return_value = 2  # Wednesday
            mock_dt.now.return_value = mock_now

            result = guarded()
            func.assert_called_once()

    def test_blocks_after_close(self):
        func = MagicMock(return_value="ran")
        guarded = _intraday_guard(func)

        with patch("src.scheduler.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.hour = 17
            mock_now.minute = 0
            mock_now.weekday.return_value = 3  # Thursday
            mock_dt.now.return_value = mock_now

            result = guarded()
            func.assert_not_called()


# ======================================================================
# scheduler.py – task functions (mocked)
# ======================================================================


class TestSchedulerTasks:
    @patch("src.scheduler._notify")
    @patch("src.scheduler.run_daily_scan")
    def test_task_daily_scan(self, mock_scan, mock_notify):
        mock_scan.return_value = [
            AggregatedReport(ticker="A", overall_signal="STRONG_OPPORTUNITY", windows={}),
            AggregatedReport(ticker="B", overall_signal="NO_ACTION", windows={}),
        ]

        reports = task_daily_scan()
        assert len(reports) == 2
        mock_scan.assert_called_once()
        mock_notify.assert_called_once_with(reports)

    @patch("src.scheduler._notify")
    @patch("src.scheduler.SignalAggregator")
    def test_task_check_breakouts(self, mock_agg_cls, mock_notify):
        mock_agg = MagicMock()
        report_with_breakout = AggregatedReport(
            ticker="CAVA",
            overall_signal="OPPORTUNITY",
            windows={"ipo_base_breakout": {"breakout_signal": "strong"}},
        )
        report_no_breakout = AggregatedReport(
            ticker="ARM",
            overall_signal="NO_ACTION",
            windows={"ipo_base_breakout": {}},
        )
        mock_agg.generate_report.side_effect = lambda t: {
            "CAVA": report_with_breakout,
            "ARM": report_no_breakout,
        }.get(t, report_no_breakout)
        mock_agg_cls.return_value = mock_agg

        with patch("src.scheduler._get_watchlist", return_value=["CAVA", "ARM"]):
            alerts = task_check_breakouts()

        assert len(alerts) == 1
        assert alerts[0].ticker == "CAVA"
        mock_notify.assert_called_once()

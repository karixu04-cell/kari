"""Tests for the scorer module (signal_aggregator, daily_scan)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.scorer.signal_aggregator import (
    AggregatedReport,
    SignalAggregator,
    _analyze_base_breakout,
    _analyze_first_day_pullback,
    _analyze_first_earnings,
    _analyze_lockup_window,
    _safe_float,
)
from src.scorer.daily_scan import (
    format_full_report,
    format_scan_details,
    format_scan_table,
    run_daily_scan,
)


# ======================================================================
# signal_aggregator.py – _safe_float
# ======================================================================


class TestSafeFloat:
    def test_normal(self):
        assert _safe_float(3.14) == 3.14

    def test_none(self):
        assert _safe_float(None) is None

    def test_nan(self):
        assert _safe_float(float("nan")) is None

    def test_string(self):
        assert _safe_float("abc") is None


# ======================================================================
# signal_aggregator.py – _analyze_first_day_pullback
# ======================================================================


class TestAnalyzeFirstDayPullback:
    def test_not_active_old_ipo(self):
        ipo_date = date.today() - timedelta(days=30)
        df = pd.DataFrame({"Close": [50, 48], "High": [52, 49]})
        result = _analyze_first_day_pullback(df, ipo_date)
        assert result["active"] is False

    def test_active_recent_ipo(self):
        ipo_date = date.today() - timedelta(days=3)
        df = pd.DataFrame({
            "Close": [50.0, 48.0, 46.0, 45.0],
            "High": [52.0, 49.0, 47.0, 46.0],
        })
        result = _analyze_first_day_pullback(df, ipo_date)
        assert result["active"] is True

    def test_pullback_entry_signal(self):
        ipo_date = date.today() - timedelta(days=3)
        # First day high=52, current close=48 → pullback ~-7.7%
        df = pd.DataFrame({
            "Close": [50.0, 49.0, 48.0],
            "High": [52.0, 50.0, 48.5],
        })
        result = _analyze_first_day_pullback(df, ipo_date)
        assert result["active"] is True
        assert result["signal"] == "pullback_entry"

    def test_holding_gains(self):
        ipo_date = date.today() - timedelta(days=3)
        # Current above first-day high
        df = pd.DataFrame({
            "Close": [50.0, 53.0, 55.0],
            "High": [51.0, 54.0, 55.5],
        })
        result = _analyze_first_day_pullback(df, ipo_date)
        assert result["signal"] == "holding_gains"

    def test_none_df(self):
        result = _analyze_first_day_pullback(None, date.today())
        assert result["active"] is False

    def test_none_ipo_date(self):
        df = pd.DataFrame({"Close": [50], "High": [52]})
        result = _analyze_first_day_pullback(df, None)
        assert result["active"] is False


# ======================================================================
# signal_aggregator.py – _analyze_lockup_window
# ======================================================================


class TestAnalyzeLockupWindow:
    def test_safe(self):
        ipo_date = date.today() - timedelta(days=30)  # 150 days until lockup
        result = _analyze_lockup_window("TEST", ipo_date)
        assert result["status"] == "safe"
        assert result["days_until"] == 150

    def test_warning(self):
        ipo_date = date.today() - timedelta(days=170)  # 10 days until lockup
        result = _analyze_lockup_window("TEST", ipo_date)
        assert result["status"] == "warning"

    def test_imminent(self):
        ipo_date = date.today() - timedelta(days=178)  # 2 days until lockup
        result = _analyze_lockup_window("TEST", ipo_date)
        assert result["status"] == "imminent"

    def test_expired(self):
        ipo_date = date.today() - timedelta(days=200)  # expired 20 days ago
        result = _analyze_lockup_window("TEST", ipo_date)
        assert result["status"] == "expired"

    def test_none_ipo_date(self):
        result = _analyze_lockup_window("TEST", None)
        assert result["status"] == "safe"
        assert result["days_until"] is None


# ======================================================================
# signal_aggregator.py – _analyze_first_earnings
# ======================================================================


class TestAnalyzeFirstEarnings:
    @patch("src.scorer.signal_aggregator.get_earnings_date")
    def test_no_date(self, mock_get):
        mock_get.return_value = None
        result = _analyze_first_earnings("TEST")
        assert result["days_until"] is None
        assert result["earnings_signal"] is None

    @patch("src.scorer.signal_aggregator.get_earnings_date")
    def test_upcoming(self, mock_get):
        mock_get.return_value = date.today() + timedelta(days=10)
        result = _analyze_first_earnings("TEST")
        assert result["days_until"] == 10
        assert result["earnings_signal"] is None  # Not yet reported

    @patch("src.scorer.signal_aggregator.analyze_earnings")
    @patch("src.scorer.signal_aggregator.get_earnings_date")
    def test_past_earnings(self, mock_get, mock_analyze):
        mock_get.return_value = date.today() - timedelta(days=5)
        mock_analysis = MagicMock()
        mock_analysis.signal = "buy"
        mock_analyze.return_value = mock_analysis

        result = _analyze_first_earnings("TEST")
        assert result["days_until"] == -5
        assert result["earnings_signal"] == "buy"


# ======================================================================
# signal_aggregator.py – _analyze_base_breakout
# ======================================================================


class TestAnalyzeBaseBreakout:
    def test_too_early(self):
        ipo_date = date.today() - timedelta(days=5)
        df = pd.DataFrame({"Close": [50, 51]})
        result = _analyze_base_breakout(df, ipo_date)
        assert result["active"] is False

    def test_none_inputs(self):
        result = _analyze_base_breakout(None, None)
        assert result["active"] is False
        assert result["base_detected"] is False

    @patch("src.scorer.signal_aggregator.BreakoutScanner")
    @patch("src.scorer.signal_aggregator.IPOBaseDetector")
    def test_base_detected_no_breakout(self, mock_detector_cls, mock_scanner_cls):
        ipo_date = date.today() - timedelta(days=30)
        df = pd.DataFrame({"Close": range(50, 80)})

        mock_base = MagicMock()
        mock_base.has_base = True
        mock_base.to_dict.return_value = {"base_type": "flat"}
        mock_detector_cls.return_value.detect_base.return_value = mock_base

        mock_signal = MagicMock()
        mock_signal.breakout_detected = False
        mock_scanner_cls.return_value.scan.return_value = mock_signal

        result = _analyze_base_breakout(df, ipo_date)
        assert result["active"] is True
        assert result["base_detected"] is True
        assert result["breakout_signal"] is None

    @patch("src.scorer.signal_aggregator.BreakoutScanner")
    @patch("src.scorer.signal_aggregator.IPOBaseDetector")
    def test_breakout_detected(self, mock_detector_cls, mock_scanner_cls):
        ipo_date = date.today() - timedelta(days=30)
        df = pd.DataFrame({"Close": range(50, 80)})

        mock_base = MagicMock()
        mock_base.has_base = True
        mock_base.to_dict.return_value = {}
        mock_detector_cls.return_value.detect_base.return_value = mock_base

        mock_signal = MagicMock()
        mock_signal.breakout_detected = True
        mock_signal.signal_strength = "strong"
        mock_scanner_cls.return_value.scan.return_value = mock_signal

        result = _analyze_base_breakout(df, ipo_date)
        assert result["breakout_signal"] == "strong"


# ======================================================================
# signal_aggregator.py – SignalAggregator._compute_overall_signal
# ======================================================================


class TestComputeOverallSignal:
    def setup_method(self):
        self.agg = SignalAggregator()

    def test_strong_opportunity(self):
        """Strong breakout + good fundamentals + positive sentiment."""
        windows = {
            "first_day_pullback": {"active": False, "signal": None},
            "ipo_base_breakout": {
                "active": True, "base_detected": True,
                "breakout_signal": "strong", "base_details": {},
            },
            "lockup_expiry": {"days_until": 100, "supply_impact_pct": None, "status": "safe"},
            "first_earnings": {"days_until": None, "earnings_signal": None},
        }
        signal, reasons, risks = self.agg._compute_overall_signal(
            windows, fundamental_score=70, sentiment={"score": 0.5},
        )
        assert signal == "STRONG_OPPORTUNITY"
        assert any("Strong breakout" in r for r in reasons)

    def test_opportunity(self):
        """Signal present + decent fundamentals."""
        windows = {
            "first_day_pullback": {"active": True, "signal": "pullback_entry"},
            "ipo_base_breakout": {"active": False, "base_detected": False, "breakout_signal": None, "base_details": None},
            "lockup_expiry": {"days_until": 100, "status": "safe"},
            "first_earnings": {"days_until": None, "earnings_signal": None},
        }
        signal, reasons, risks = self.agg._compute_overall_signal(
            windows, fundamental_score=55, sentiment={"score": 0.1},
        )
        assert signal == "OPPORTUNITY"

    def test_watch_base_forming(self):
        """Base detected but no breakout → WATCH."""
        windows = {
            "first_day_pullback": {"active": False, "signal": None},
            "ipo_base_breakout": {
                "active": True, "base_detected": True,
                "breakout_signal": None, "base_details": {},
            },
            "lockup_expiry": {"days_until": 100, "status": "safe"},
            "first_earnings": {"days_until": None, "earnings_signal": None},
        }
        signal, reasons, risks = self.agg._compute_overall_signal(
            windows, fundamental_score=40, sentiment={"score": 0.0},
        )
        assert signal == "WATCH"

    def test_watch_lockup_imminent(self):
        """Lockup imminent → WATCH."""
        windows = {
            "first_day_pullback": {"active": False, "signal": None},
            "ipo_base_breakout": {"active": False, "base_detected": False, "breakout_signal": None, "base_details": None},
            "lockup_expiry": {"days_until": 2, "supply_impact_pct": 80.0, "status": "imminent"},
            "first_earnings": {"days_until": None, "earnings_signal": None},
        }
        signal, reasons, risks = self.agg._compute_overall_signal(
            windows, fundamental_score=30, sentiment={"score": 0.0},
        )
        assert signal == "WATCH"
        assert any("imminent" in r.lower() for r in risks)

    def test_no_action(self):
        """No signals, no watch conditions → NO_ACTION."""
        windows = {
            "first_day_pullback": {"active": False, "signal": None},
            "ipo_base_breakout": {"active": False, "base_detected": False, "breakout_signal": None, "base_details": None},
            "lockup_expiry": {"days_until": 100, "status": "safe"},
            "first_earnings": {"days_until": None, "earnings_signal": None},
        }
        signal, reasons, risks = self.agg._compute_overall_signal(
            windows, fundamental_score=30, sentiment={"score": 0.0},
        )
        assert signal == "NO_ACTION"

    def test_earnings_buy_signal(self):
        """Earnings buy signal + good fundamentals → OPPORTUNITY."""
        windows = {
            "first_day_pullback": {"active": False, "signal": None},
            "ipo_base_breakout": {"active": False, "base_detected": False, "breakout_signal": None, "base_details": None},
            "lockup_expiry": {"days_until": 100, "status": "safe"},
            "first_earnings": {"days_until": -5, "earnings_signal": "buy"},
        }
        signal, reasons, risks = self.agg._compute_overall_signal(
            windows, fundamental_score=55, sentiment={"score": 0.1},
        )
        assert signal == "OPPORTUNITY"

    def test_earnings_caution_adds_risk(self):
        """Earnings caution → risk factor added."""
        windows = {
            "first_day_pullback": {"active": False, "signal": None},
            "ipo_base_breakout": {"active": False, "base_detected": False, "breakout_signal": None, "base_details": None},
            "lockup_expiry": {"days_until": 100, "status": "safe"},
            "first_earnings": {"days_until": -5, "earnings_signal": "caution"},
        }
        signal, reasons, risks = self.agg._compute_overall_signal(
            windows, fundamental_score=30, sentiment={"score": -0.5},
        )
        assert any("Earnings below" in r for r in risks)
        assert any("Negative sentiment" in r for r in risks)

    def test_upcoming_earnings_watch(self):
        """Earnings in 5 days → WATCH."""
        windows = {
            "first_day_pullback": {"active": False, "signal": None},
            "ipo_base_breakout": {"active": False, "base_detected": False, "breakout_signal": None, "base_details": None},
            "lockup_expiry": {"days_until": 100, "status": "safe"},
            "first_earnings": {"days_until": 5, "earnings_signal": None},
        }
        signal, reasons, risks = self.agg._compute_overall_signal(
            windows, fundamental_score=30, sentiment={"score": 0.0},
        )
        assert signal == "WATCH"
        assert any("5 days" in r for r in reasons)

    def test_moderate_breakout_is_opportunity(self):
        """Moderate breakout + fundamentals >= 50 → OPPORTUNITY."""
        windows = {
            "first_day_pullback": {"active": False, "signal": None},
            "ipo_base_breakout": {
                "active": True, "base_detected": True,
                "breakout_signal": "moderate", "base_details": {},
            },
            "lockup_expiry": {"days_until": 100, "status": "safe"},
            "first_earnings": {"days_until": None, "earnings_signal": None},
        }
        signal, reasons, risks = self.agg._compute_overall_signal(
            windows, fundamental_score=55, sentiment={"score": 0.1},
        )
        assert signal == "OPPORTUNITY"

    def test_signal_without_fundamentals_no_upgrade(self):
        """Signal present but fundamentals < 50 → NO_ACTION (not OPPORTUNITY)."""
        windows = {
            "first_day_pullback": {"active": True, "signal": "pullback_entry"},
            "ipo_base_breakout": {"active": False, "base_detected": False, "breakout_signal": None, "base_details": None},
            "lockup_expiry": {"days_until": 100, "status": "safe"},
            "first_earnings": {"days_until": None, "earnings_signal": None},
        }
        signal, reasons, risks = self.agg._compute_overall_signal(
            windows, fundamental_score=30, sentiment={"score": 0.0},
        )
        # Has signal but fundamentals < 50, so NO_ACTION
        assert signal == "NO_ACTION"


# ======================================================================
# signal_aggregator.py – SignalAggregator.generate_report (mocked)
# ======================================================================


class TestGenerateReport:
    @patch("src.scorer.signal_aggregator.analyze_sentiment")
    @patch("src.scorer.signal_aggregator.fetch_news")
    @patch("src.scorer.signal_aggregator.calculate_quick_score")
    @patch("src.scorer.signal_aggregator.get_earnings_date")
    @patch("src.scorer.signal_aggregator._get_price_history")
    @patch("src.scorer.signal_aggregator._get_stock_info")
    def test_full_report(
        self, mock_info, mock_history, mock_earnings_date,
        mock_quick_score, mock_fetch_news, mock_sentiment,
    ):
        mock_info.return_value = {
            "shortName": "Test Corp",
            "currentPrice": 55.0,
            "ipoDate": (date.today() - timedelta(days=60)).isoformat(),
            "ipoPrice": 25.0,
        }
        mock_history.return_value = pd.DataFrame({
            "Close": [25.0, 30.0, 35.0, 40.0, 50.0, 55.0],
            "High": [26.0, 32.0, 37.0, 42.0, 52.0, 56.0],
        })
        mock_earnings_date.return_value = None
        mock_quick_score.return_value = MagicMock(total_score=65)
        mock_fetch_news.return_value = []
        mock_sentiment.return_value = MagicMock(
            overall_score=0.2, buzz_level="low",
            positive_count=3, negative_count=1, method="keyword",
        )

        agg = SignalAggregator()
        report = agg.generate_report("TEST")

        assert report.ticker == "TEST"
        assert report.company == "Test Corp"
        assert report.current_price == 55.0
        assert report.ipo_price == 25.0
        assert report.price_vs_ipo == 2.2
        assert report.days_since_ipo == 60
        assert report.fundamental_score == 65
        assert "windows" in dir(report)
        assert report.overall_signal in (
            "STRONG_OPPORTUNITY", "OPPORTUNITY", "WATCH", "NO_ACTION",
        )

    @patch("src.scorer.signal_aggregator.analyze_sentiment")
    @patch("src.scorer.signal_aggregator.fetch_news")
    @patch("src.scorer.signal_aggregator.calculate_quick_score")
    @patch("src.scorer.signal_aggregator.get_earnings_date")
    @patch("src.scorer.signal_aggregator._get_price_history")
    @patch("src.scorer.signal_aggregator._get_stock_info")
    def test_minimal_info(
        self, mock_info, mock_history, mock_earnings_date,
        mock_quick_score, mock_fetch_news, mock_sentiment,
    ):
        mock_info.return_value = {}
        mock_history.return_value = None
        mock_earnings_date.return_value = None
        mock_quick_score.return_value = MagicMock(total_score=0)
        mock_fetch_news.return_value = []
        mock_sentiment.return_value = MagicMock(
            overall_score=0.0, buzz_level="low",
            positive_count=0, negative_count=0, method="keyword",
        )

        agg = SignalAggregator()
        report = agg.generate_report("UNKNOWN")

        assert report.ticker == "UNKNOWN"
        assert report.overall_signal == "NO_ACTION"


# ======================================================================
# signal_aggregator.py – AggregatedReport.to_dict
# ======================================================================


class TestAggregatedReportToDict:
    def test_to_dict(self):
        report = AggregatedReport(
            ticker="CAVA",
            company="CAVA Group",
            ipo_date=date(2023, 6, 15),
            days_since_ipo=300,
            current_price=80.0,
            ipo_price=22.0,
            price_vs_ipo=3.636,
            overall_signal="OPPORTUNITY",
            signal_reasons=["Base breakout"],
            risk_factors=["Lockup approaching"],
        )
        d = report.to_dict()
        assert d["ticker"] == "CAVA"
        assert d["ipo_date"] == "2023-06-15"
        assert d["overall_signal"] == "OPPORTUNITY"
        assert len(d["signal_reasons"]) == 1

    def test_to_dict_none_date(self):
        report = AggregatedReport(ticker="X")
        d = report.to_dict()
        assert d["ipo_date"] is None


# ======================================================================
# daily_scan.py – run_daily_scan (mocked)
# ======================================================================


class TestRunDailyScan:
    @patch("src.scorer.daily_scan.SignalAggregator")
    def test_scans_all_tickers(self, mock_agg_cls):
        mock_agg = MagicMock()

        def make_report(ticker):
            return AggregatedReport(
                ticker=ticker,
                overall_signal="NO_ACTION" if ticker == "BBB" else "OPPORTUNITY",
            )

        mock_agg.generate_report.side_effect = make_report
        mock_agg_cls.return_value = mock_agg

        reports = run_daily_scan(["AAA", "BBB", "CCC"])
        assert len(reports) == 3
        # OPPORTUNITY tickers should come before NO_ACTION
        assert reports[0].overall_signal == "OPPORTUNITY"
        assert reports[-1].overall_signal == "NO_ACTION"

    @patch("src.scorer.daily_scan.SignalAggregator")
    def test_handles_exceptions(self, mock_agg_cls):
        mock_agg = MagicMock()
        mock_agg.generate_report.side_effect = Exception("API error")
        mock_agg_cls.return_value = mock_agg

        reports = run_daily_scan(["FAIL"])
        assert len(reports) == 1
        assert reports[0].overall_signal == "NO_ACTION"
        assert any("error" in r.lower() for r in reports[0].risk_factors)

    def test_empty_watchlist(self):
        reports = run_daily_scan([])
        assert reports == []

    @patch("src.scorer.daily_scan.SignalAggregator")
    def test_sorted_by_priority(self, mock_agg_cls):
        mock_agg = MagicMock()
        signal_map = {
            "D": "NO_ACTION",
            "C": "WATCH",
            "B": "OPPORTUNITY",
            "A": "STRONG_OPPORTUNITY",
        }
        mock_agg.generate_report.side_effect = lambda t: AggregatedReport(
            ticker=t, overall_signal=signal_map[t],
        )
        mock_agg_cls.return_value = mock_agg

        reports = run_daily_scan(["D", "C", "B", "A"])
        signals = [r.overall_signal for r in reports]
        assert signals == [
            "STRONG_OPPORTUNITY", "OPPORTUNITY", "WATCH", "NO_ACTION",
        ]


# ======================================================================
# daily_scan.py – format functions
# ======================================================================


class TestFormatFunctions:
    def _make_reports(self) -> list[AggregatedReport]:
        return [
            AggregatedReport(
                ticker="CAVA",
                company="CAVA Group",
                current_price=80.0,
                ipo_price=22.0,
                price_vs_ipo=3.636,
                fundamental_score=70,
                sentiment={"score": 0.4, "buzz": "medium"},
                days_since_ipo=300,
                overall_signal="STRONG_OPPORTUNITY",
                signal_reasons=["Strong breakout"],
                risk_factors=[],
                windows={
                    "ipo_base_breakout": {
                        "active": True, "base_detected": True,
                        "breakout_signal": "strong", "base_details": {},
                    },
                    "lockup_expiry": {"status": "safe", "days_until": 100},
                },
            ),
            AggregatedReport(
                ticker="ARM",
                company="Arm Holdings",
                current_price=120.0,
                overall_signal="NO_ACTION",
                sentiment={"score": 0.0, "buzz": "low"},
                windows={},
            ),
        ]

    def test_format_scan_table(self):
        reports = self._make_reports()
        text = format_scan_table(reports)
        assert "CAVA" in text
        assert "ARM" in text
        assert "STRONG" in text
        assert "Ticker" in text
        assert "Daily Scan" in text

    def test_format_scan_table_empty(self):
        text = format_scan_table([])
        assert "No tickers" in text

    def test_format_scan_details(self):
        reports = self._make_reports()
        text = format_scan_details(reports)
        assert "CAVA" in text
        assert "Strong breakout" in text

    def test_format_scan_details_empty(self):
        text = format_scan_details([])
        assert text == ""

    def test_format_full_report(self):
        reports = self._make_reports()
        text = format_full_report(reports)
        assert "CAVA" in text
        assert "ARM" in text
        assert "Summary:" in text
        assert "STRONG_OPPORTUNITY" in text

    def test_format_details_all_no_action(self):
        reports = [
            AggregatedReport(ticker="A", overall_signal="NO_ACTION", windows={}),
            AggregatedReport(ticker="B", overall_signal="NO_ACTION", windows={}),
        ]
        text = format_scan_details(reports)
        # With <= 5 tickers, shows all
        assert "A" in text or "NO_ACTION" in text

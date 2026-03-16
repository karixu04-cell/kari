"""Tests for the earnings module (earnings_calendar, earnings_analyzer)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.earnings.earnings_calendar import (
    UpcomingEarnings,
    get_earnings_date,
    get_upcoming_earnings,
)
from src.earnings.earnings_analyzer import (
    EarningsAnalysis,
    _compute_eps_surprise,
    _compute_gross_margin,
    _compute_revenue_surprise,
    _compute_revenue_yoy_growth,
    _determine_guidance,
    _determine_signal,
    _determine_trajectory,
    _is_first_report,
    _pct_change,
    _safe_float,
    analyze_earnings,
    format_earnings_analysis,
)


# ======================================================================
# earnings_analyzer.py – helper functions
# ======================================================================


class TestSafeFloat:
    def test_normal_float(self):
        assert _safe_float(3.14) == 3.14

    def test_int(self):
        assert _safe_float(42) == 42.0

    def test_string_number(self):
        assert _safe_float("1.5") == 1.5

    def test_none(self):
        assert _safe_float(None) is None

    def test_nan(self):
        assert _safe_float(float("nan")) is None

    def test_invalid_string(self):
        assert _safe_float("abc") is None


class TestPctChange:
    def test_positive_change(self):
        assert _pct_change(120, 100) == 20.0

    def test_negative_change(self):
        assert _pct_change(80, 100) == -20.0

    def test_zero_previous(self):
        assert _pct_change(100, 0) is None

    def test_none_values(self):
        assert _pct_change(None, 100) is None
        assert _pct_change(100, None) is None


# ======================================================================
# earnings_analyzer.py – _determine_signal
# ======================================================================


class TestDetermineSignal:
    def test_strong_buy(self):
        """Both beat + guidance raised → strong_buy."""
        assert _determine_signal(5.0, 3.0, "raised") == "strong_buy"

    def test_buy_both_beat_no_guidance(self):
        """Both beat, guidance not raised → buy."""
        assert _determine_signal(2.0, 1.5, "maintained") == "buy"

    def test_buy_only_eps_beats(self):
        """Only EPS beats, revenue in line."""
        assert _determine_signal(3.0, None, "none") == "buy"

    def test_buy_only_revenue_beats(self):
        """Only revenue beats, EPS in line."""
        assert _determine_signal(None, 2.0, "none") == "buy"

    def test_neutral_in_line(self):
        """Both in line → neutral."""
        assert _determine_signal(None, None, "none") == "neutral"
        assert _determine_signal(0.0, 0.0, "maintained") == "neutral"

    def test_caution_eps_miss(self):
        """EPS miss → caution."""
        assert _determine_signal(-2.0, 1.0, "none") == "caution"

    def test_caution_revenue_miss(self):
        """Revenue miss → caution."""
        assert _determine_signal(1.0, -3.0, "none") == "caution"

    def test_caution_both_miss(self):
        """Both miss → caution."""
        assert _determine_signal(-5.0, -2.0, "lowered") == "caution"


# ======================================================================
# earnings_analyzer.py – _determine_guidance
# ======================================================================


class TestDetermineGuidance:
    def test_raised_from_target_upside(self):
        info = {"targetMeanPrice": 150, "currentPrice": 100}
        assert _determine_guidance(info) == "raised"

    def test_lowered_from_target_downside(self):
        info = {"targetMeanPrice": 90, "currentPrice": 100}
        assert _determine_guidance(info) == "lowered"

    def test_maintained(self):
        info = {"targetMeanPrice": 105, "currentPrice": 100}
        assert _determine_guidance(info) == "maintained"

    def test_raised_from_recommendation(self):
        info = {"recommendationKey": "strong_buy"}
        assert _determine_guidance(info) == "raised"

    def test_lowered_from_recommendation(self):
        info = {"recommendationKey": "sell"}
        assert _determine_guidance(info) == "lowered"

    def test_none_no_info(self):
        assert _determine_guidance({}) == "none"


# ======================================================================
# earnings_analyzer.py – _determine_trajectory
# ======================================================================


class TestDetermineTrajectory:
    def _make_qe(self, revenues: list[float]) -> pd.DataFrame:
        """Create a mock quarterly_earnings DataFrame with given revenues."""
        return pd.DataFrame({"Revenue": revenues, "Earnings": [0] * len(revenues)})

    def test_accelerating(self):
        # Growth rates: (120-100)/100=0.20, (100-90)/90=0.11 → delta=0.09 > 0.03
        qe = self._make_qe([120, 100, 90])
        assert _determine_trajectory(qe) == "accelerating"

    def test_decelerating(self):
        # Growth rates: (105-100)/100=0.05, (100-80)/80=0.25 → delta=-0.20 < -0.03
        qe = self._make_qe([105, 100, 80])
        assert _determine_trajectory(qe) == "decelerating"

    def test_stable(self):
        # Growth rates: (110-100)/100=0.10, (100-91)/91≈0.099 → delta≈0.001
        qe = self._make_qe([110, 100, 91])
        assert _determine_trajectory(qe) == "stable"

    def test_too_few_quarters(self):
        qe = self._make_qe([100, 90])
        assert _determine_trajectory(qe) == "stable"

    def test_none_input(self):
        assert _determine_trajectory(None) == "stable"


# ======================================================================
# earnings_analyzer.py – _is_first_report
# ======================================================================


class TestIsFirstReport:
    def test_single_quarter(self):
        qe = pd.DataFrame({"Revenue": [100], "Earnings": [5]})
        assert _is_first_report(qe, {}) is True

    def test_multiple_quarters(self):
        qe = pd.DataFrame({"Revenue": [100, 90, 80], "Earnings": [5, 4, 3]})
        assert _is_first_report(qe, {}) is False

    def test_recent_ipo_date(self):
        ipo_date = (date.today() - timedelta(days=60)).isoformat()
        qe = pd.DataFrame({"Revenue": [100, 90, 80], "Earnings": [5, 4, 3]})
        assert _is_first_report(qe, {"ipoDate": ipo_date}) is True

    def test_old_ipo_date(self):
        ipo_date = (date.today() - timedelta(days=365)).isoformat()
        qe = pd.DataFrame({"Revenue": [100, 90, 80], "Earnings": [5, 4, 3]})
        assert _is_first_report(qe, {"ipoDate": ipo_date}) is False


# ======================================================================
# earnings_analyzer.py – _compute_eps_surprise
# ======================================================================


class TestComputeEpsSurprise:
    def test_with_reported_data(self):
        dates_idx = pd.to_datetime(["2024-11-01", "2024-08-01"])
        df = pd.DataFrame(
            {
                "EPS Estimate": [0.50, 0.40],
                "Reported EPS": [0.55, 0.42],
                "Surprise(%)": [10.0, 5.0],
            },
            index=dates_idx,
        )
        eps, surprise = _compute_eps_surprise(df)
        assert eps == 0.55
        assert surprise == 10.0

    def test_no_reported(self):
        dates_idx = pd.to_datetime(["2024-11-01"])
        df = pd.DataFrame(
            {
                "EPS Estimate": [0.50],
                "Reported EPS": [None],
                "Surprise(%)": [None],
            },
            index=dates_idx,
        )
        eps, surprise = _compute_eps_surprise(df)
        assert eps is None
        assert surprise is None

    def test_none_input(self):
        assert _compute_eps_surprise(None) == (None, None)

    def test_empty_dataframe(self):
        df = pd.DataFrame(columns=["EPS Estimate", "Reported EPS", "Surprise(%)"])
        assert _compute_eps_surprise(df) == (None, None)


# ======================================================================
# earnings_analyzer.py – _compute_revenue_yoy_growth
# ======================================================================


class TestComputeRevenueYoyGrowth:
    def test_normal_growth(self):
        qe = pd.DataFrame({
            "Revenue": [120e6, 115e6, 110e6, 105e6, 100e6],
            "Earnings": [0] * 5,
        })
        growth = _compute_revenue_yoy_growth(qe)
        assert growth == 20.0  # (120-100)/100 * 100

    def test_too_few_quarters(self):
        qe = pd.DataFrame({"Revenue": [100, 90], "Earnings": [0, 0]})
        assert _compute_revenue_yoy_growth(qe) is None

    def test_none_input(self):
        assert _compute_revenue_yoy_growth(None) is None


# ======================================================================
# earnings_analyzer.py – _compute_gross_margin
# ======================================================================


class TestComputeGrossMargin:
    def test_normal_margin(self):
        data = {
            datetime(2024, 9, 30): [200e6, 60e6],
            datetime(2024, 6, 30): [180e6, 50e6],
        }
        df = pd.DataFrame(data, index=["Total Revenue", "Gross Profit"])
        margin, change = _compute_gross_margin(df)
        assert margin == 30.0  # 60/200 * 100
        expected_prior = 50 / 180 * 100
        assert change == pytest.approx(30.0 - expected_prior, abs=0.1)

    def test_none_input(self):
        assert _compute_gross_margin(None) == (None, None)

    def test_empty_dataframe(self):
        df = pd.DataFrame()
        assert _compute_gross_margin(df) == (None, None)


# ======================================================================
# earnings_analyzer.py – analyze_earnings (mocked)
# ======================================================================


class TestAnalyzeEarnings:
    @patch("src.earnings.earnings_analyzer._fetch_earnings_data")
    def test_full_analysis(self, mock_fetch):
        dates_idx = pd.to_datetime(["2024-11-01", "2024-08-01"])
        earnings_dates = pd.DataFrame(
            {
                "EPS Estimate": [0.50, 0.40],
                "Reported EPS": [0.60, 0.45],
                "Surprise(%)": [20.0, 12.5],
            },
            index=dates_idx,
        )
        quarterly_earnings = pd.DataFrame({
            "Revenue": [150e6, 140e6, 130e6, 120e6, 110e6],
            "Earnings": [10e6, 9e6, 8e6, 7e6, 6e6],
        })
        income_stmt = pd.DataFrame(
            {
                datetime(2024, 9, 30): [150e6, 45e6],
                datetime(2024, 6, 30): [140e6, 40e6],
            },
            index=["Total Revenue", "Gross Profit"],
        )
        mock_fetch.return_value = {
            "quarterly_earnings": quarterly_earnings,
            "quarterly_financials": None,
            "income_stmt": income_stmt,
            "earnings_dates": earnings_dates,
            "info": {
                "targetMeanPrice": 80,
                "currentPrice": 60,
                "recommendationKey": "buy",
            },
        }

        result = analyze_earnings("CAVA")
        assert result.ticker == "CAVA"
        assert result.eps == 0.60
        assert result.eps_surprise_pct == 20.0
        assert result.revenue is not None
        assert result.guidance == "raised"  # target 80 vs price 60 → >20% upside
        assert result.signal in ("strong_buy", "buy")

    @patch("src.earnings.earnings_analyzer._fetch_earnings_data")
    def test_missing_data_returns_neutral(self, mock_fetch):
        mock_fetch.return_value = {
            "quarterly_earnings": None,
            "quarterly_financials": None,
            "income_stmt": None,
            "earnings_dates": None,
            "info": {},
        }
        result = analyze_earnings("UNKNOWN")
        assert result.ticker == "UNKNOWN"
        assert result.signal == "neutral"

    @patch("src.earnings.earnings_analyzer._fetch_earnings_data")
    def test_exception_returns_neutral(self, mock_fetch):
        mock_fetch.side_effect = Exception("Network error")
        result = analyze_earnings("FAIL")
        assert result.signal == "neutral"
        assert "error" in result.details


# ======================================================================
# earnings_analyzer.py – format_earnings_analysis
# ======================================================================


class TestFormatEarningsAnalysis:
    def test_full_format(self):
        analysis = EarningsAnalysis(
            ticker="CAVA",
            report_date=date(2024, 11, 15),
            revenue=150e6,
            revenue_yoy_growth=25.5,
            eps=0.55,
            eps_surprise_pct=15.0,
            revenue_surprise_pct=8.2,
            guidance="raised",
            gross_margin=30.0,
            gross_margin_change=2.1,
            is_first_public_report=False,
            vs_s1_trajectory="accelerating",
            signal="strong_buy",
        )
        text = format_earnings_analysis(analysis)
        assert "CAVA" in text
        assert "STRONG BUY" in text
        assert "150.0M" in text
        assert "+25.5%" in text
        assert "+15.0%" in text
        assert "raised" in text
        assert "30.0%" in text
        assert "accelerating" in text

    def test_minimal_format(self):
        analysis = EarningsAnalysis(ticker="XYZ", signal="neutral")
        text = format_earnings_analysis(analysis)
        assert "XYZ" in text
        assert "NEUTRAL" in text

    def test_caution_format(self):
        analysis = EarningsAnalysis(ticker="BAD", signal="caution")
        text = format_earnings_analysis(analysis)
        assert "CAUTION" in text


# ======================================================================
# earnings_analyzer.py – EarningsAnalysis.to_dict
# ======================================================================


class TestEarningsAnalysisToDict:
    def test_to_dict(self):
        analysis = EarningsAnalysis(
            ticker="CAVA",
            report_date=date(2024, 11, 15),
            revenue=150e6,
            eps=0.55,
            signal="buy",
        )
        d = analysis.to_dict()
        assert d["ticker"] == "CAVA"
        assert d["report_date"] == "2024-11-15"
        assert d["revenue"] == 150e6
        assert d["signal"] == "buy"

    def test_to_dict_none_date(self):
        analysis = EarningsAnalysis(ticker="X")
        d = analysis.to_dict()
        assert d["report_date"] is None


# ======================================================================
# earnings_calendar.py – UpcomingEarnings
# ======================================================================


class TestUpcomingEarnings:
    def test_to_dict(self):
        ue = UpcomingEarnings(
            ticker="CAVA",
            earnings_date=date(2024, 11, 15),
            company_name="CAVA Group",
            days_until=10,
        )
        d = ue.to_dict()
        assert d["ticker"] == "CAVA"
        assert d["earnings_date"] == "2024-11-15"
        assert d["days_until"] == 10


# ======================================================================
# earnings_calendar.py – get_earnings_date (mocked)
# ======================================================================


class TestGetEarningsDate:
    @patch("src.earnings.earnings_calendar.yf.Ticker")
    def test_dict_calendar(self, mock_ticker_cls):
        mock_ticker = MagicMock()
        mock_ticker.calendar = {
            "Earnings Date": [datetime(2024, 11, 15, 16, 0)]
        }
        mock_ticker_cls.return_value = mock_ticker

        result = get_earnings_date("CAVA")
        assert result == date(2024, 11, 15)

    @patch("src.earnings.earnings_calendar.yf.Ticker")
    def test_dict_calendar_single_date(self, mock_ticker_cls):
        mock_ticker = MagicMock()
        mock_ticker.calendar = {
            "Earnings Date": datetime(2024, 11, 15, 16, 0)
        }
        mock_ticker_cls.return_value = mock_ticker

        result = get_earnings_date("CAVA")
        assert result == date(2024, 11, 15)

    @patch("src.earnings.earnings_calendar.yf.Ticker")
    def test_empty_calendar(self, mock_ticker_cls):
        mock_ticker = MagicMock()
        mock_ticker.calendar = {}
        mock_ticker_cls.return_value = mock_ticker

        result = get_earnings_date("CAVA")
        assert result is None

    @patch("src.earnings.earnings_calendar.yf.Ticker")
    def test_none_calendar(self, mock_ticker_cls):
        mock_ticker = MagicMock()
        mock_ticker.calendar = None
        mock_ticker_cls.return_value = mock_ticker

        result = get_earnings_date("CAVA")
        assert result is None

    @patch("src.earnings.earnings_calendar.yf.Ticker")
    def test_exception(self, mock_ticker_cls):
        mock_ticker_cls.side_effect = Exception("Network error")
        result = get_earnings_date("FAIL")
        assert result is None

    @patch("src.earnings.earnings_calendar.yf.Ticker")
    def test_dataframe_calendar(self, mock_ticker_cls):
        mock_ticker = MagicMock()
        cal_df = pd.DataFrame(
            {"0": [datetime(2024, 11, 15)]},
            index=["Earnings Date"],
        )
        mock_ticker.calendar = cal_df
        mock_ticker_cls.return_value = mock_ticker

        result = get_earnings_date("CAVA")
        assert result == date(2024, 11, 15)


# ======================================================================
# earnings_calendar.py – get_upcoming_earnings (mocked)
# ======================================================================


class TestGetUpcomingEarnings:
    @patch("src.earnings.earnings_calendar.yf.Ticker")
    @patch("src.earnings.earnings_calendar.get_earnings_date")
    def test_filters_within_window(self, mock_get_date, mock_ticker_cls):
        today = date.today()
        mock_get_date.side_effect = lambda t: {
            "AAA": today + timedelta(days=5),
            "BBB": today + timedelta(days=45),  # outside 30-day window
            "CCC": today + timedelta(days=20),
        }.get(t)

        mock_info = MagicMock()
        mock_info.info = {"shortName": "Test Co"}
        mock_ticker_cls.return_value = mock_info

        results = get_upcoming_earnings(["AAA", "BBB", "CCC"], days=30)
        tickers = [r.ticker for r in results]
        assert "AAA" in tickers
        assert "CCC" in tickers
        assert "BBB" not in tickers

    @patch("src.earnings.earnings_calendar.get_earnings_date")
    def test_empty_watchlist(self, mock_get_date):
        results = get_upcoming_earnings([], days=30)
        assert results == []

    @patch("src.earnings.earnings_calendar.get_earnings_date")
    def test_no_dates_found(self, mock_get_date):
        mock_get_date.return_value = None
        results = get_upcoming_earnings(["AAA", "BBB"], days=30)
        assert results == []

    @patch("src.earnings.earnings_calendar.yf.Ticker")
    @patch("src.earnings.earnings_calendar.get_earnings_date")
    def test_sorted_by_date(self, mock_get_date, mock_ticker_cls):
        today = date.today()
        mock_get_date.side_effect = lambda t: {
            "LATE": today + timedelta(days=20),
            "SOON": today + timedelta(days=3),
        }.get(t)

        mock_info = MagicMock()
        mock_info.info = {"shortName": ""}
        mock_ticker_cls.return_value = mock_info

        results = get_upcoming_earnings(["LATE", "SOON"], days=30)
        assert len(results) == 2
        assert results[0].ticker == "SOON"
        assert results[1].ticker == "LATE"

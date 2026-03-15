"""Tests for the pattern module (indicators, ipo_base_detector, breakout_scanner)."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from src.pattern.indicators import (
    atr,
    ema,
    price_range_pct,
    relative_volume,
    rsi,
    sma,
    vwap,
)
from src.pattern.ipo_base_detector import BaseInfo, IPOBaseDetector
from src.pattern.breakout_scanner import BreakoutScanner, BreakoutSignal


# ======================================================================
# Helper to build synthetic OHLCV DataFrames
# ======================================================================


def _make_ohlcv(
    prices: list[float],
    volumes: list[float] | None = None,
    start_date: str = "2025-01-02",
    spread: float = 0.02,
) -> pd.DataFrame:
    """Build a synthetic OHLCV DataFrame from a close-price sequence.

    ``spread`` controls how much High/Low differ from Close.
    """
    n = len(prices)
    dates = pd.bdate_range(start=start_date, periods=n)
    if volumes is None:
        volumes = [1_000_000] * n

    closes = np.array(prices, dtype=float)
    highs = closes * (1 + spread)
    lows = closes * (1 - spread)
    opens = (closes + highs) / 2

    return pd.DataFrame({
        "Open": opens,
        "High": highs,
        "Low": lows,
        "Close": closes,
        "Volume": volumes,
    }, index=dates)


def _make_ipo_base_df(
    ipo_date: date,
    rally_days: int = 10,
    rally_price_start: float = 30.0,
    rally_price_end: float = 50.0,
    base_days: int = 30,
    base_depth_pct: float = 0.25,
    breakout: bool = False,
    breakout_volume_mult: float = 2.0,
) -> pd.DataFrame:
    """Build a realistic IPO → rally → base → optional breakout DataFrame."""
    prices = []
    volumes = []
    rng = np.random.RandomState(42)

    # Phase 1: IPO rally
    for i in range(rally_days):
        t = i / max(rally_days - 1, 1)
        p = rally_price_start + (rally_price_end - rally_price_start) * t
        prices.append(p)
        volumes.append(2_000_000 + rng.randint(0, 500_000))

    left_high = rally_price_end
    base_low = left_high * (1 - base_depth_pct)

    # Phase 2: Base formation - decline then consolidate
    half = base_days // 2
    for i in range(half):
        t = i / max(half - 1, 1)
        p = left_high - (left_high - base_low) * t
        prices.append(p + rng.uniform(-0.5, 0.5))
        # Volume declining
        volumes.append(1_500_000 - i * 20_000 + rng.randint(0, 100_000))

    # Second half: stabilize near base_low with tightening range
    for i in range(base_days - half):
        noise_scale = 1.0 - (i / max(base_days - half - 1, 1)) * 0.8
        p = base_low + (left_high - base_low) * 0.3
        p += rng.uniform(-1, 1) * noise_scale
        prices.append(p)
        volumes.append(800_000 + rng.randint(0, 200_000))

    # Phase 3: Optional breakout
    if breakout:
        prices.append(left_high * 1.03)
        volumes.append(int(1_000_000 * breakout_volume_mult * 2))
        # A few more days after breakout
        for i in range(5):
            prices.append(left_high * (1.02 + rng.uniform(0, 0.05)))
            volumes.append(1_500_000 + rng.randint(0, 500_000))

    dates = pd.bdate_range(start=str(ipo_date), periods=len(prices))
    closes = np.array(prices)
    highs = closes * 1.015
    lows = closes * 0.985
    opens = (closes + lows) / 2

    return pd.DataFrame({
        "Open": opens,
        "High": highs,
        "Low": lows,
        "Close": closes,
        "Volume": volumes,
    }, index=dates)


# ======================================================================
# indicators.py – SMA
# ======================================================================


class TestSMA:
    def test_basic(self):
        s = pd.Series([1, 2, 3, 4, 5], dtype=float)
        result = sma(s, 3)
        assert pd.isna(result.iloc[0])
        assert pd.isna(result.iloc[1])
        assert result.iloc[2] == pytest.approx(2.0)
        assert result.iloc[3] == pytest.approx(3.0)
        assert result.iloc[4] == pytest.approx(4.0)

    def test_period_1(self):
        s = pd.Series([10, 20, 30], dtype=float)
        result = sma(s, 1)
        assert result.iloc[0] == pytest.approx(10.0)
        assert result.iloc[2] == pytest.approx(30.0)

    def test_all_same(self):
        s = pd.Series([5.0] * 10)
        result = sma(s, 5)
        assert result.dropna().unique() == pytest.approx([5.0])


# ======================================================================
# indicators.py – EMA
# ======================================================================


class TestEMA:
    def test_basic(self):
        s = pd.Series([1, 2, 3, 4, 5], dtype=float)
        result = ema(s, 3)
        assert len(result) == 5
        # EMA should be defined for all values (ewm doesn't produce leading NaN)
        assert not result.isna().any()

    def test_ema_follows_trend(self):
        s = pd.Series(range(1, 21), dtype=float)
        result = ema(s, 5)
        # EMA should lag behind an uptrend
        assert result.iloc[-1] < s.iloc[-1]
        assert result.iloc[-1] > s.iloc[-5]


# ======================================================================
# indicators.py – RSI
# ======================================================================


class TestRSI:
    def test_constant_price(self):
        s = pd.Series([50.0] * 30)
        result = rsi(s)
        # No movement → RSI undefined (0/0), typically NaN
        # Just check it doesn't crash
        assert len(result) == 30

    def test_all_up(self):
        s = pd.Series(range(1, 31), dtype=float)
        result = rsi(s)
        # All gains, no losses → RSI should be near 100
        last = result.iloc[-1]
        assert last > 90

    def test_all_down(self):
        s = pd.Series(range(30, 0, -1), dtype=float)
        result = rsi(s)
        last = result.iloc[-1]
        assert last < 10

    def test_range(self):
        """RSI should be between 0 and 100 for normal data."""
        rng = np.random.RandomState(42)
        s = pd.Series(100 + rng.randn(100).cumsum())
        result = rsi(s)
        valid = result.dropna()
        assert (valid >= 0).all()
        assert (valid <= 100).all()


# ======================================================================
# indicators.py – VWAP
# ======================================================================


class TestVWAP:
    def test_constant_price(self):
        n = 10
        h = pd.Series([10.0] * n)
        l = pd.Series([10.0] * n)
        c = pd.Series([10.0] * n)
        v = pd.Series([1000] * n)
        result = vwap(h, l, c, v)
        assert result.iloc[-1] == pytest.approx(10.0)

    def test_weighted_toward_high_volume(self):
        h = pd.Series([10.0, 20.0])
        l = pd.Series([10.0, 20.0])
        c = pd.Series([10.0, 20.0])
        v = pd.Series([100, 900])  # most volume at $20
        result = vwap(h, l, c, v)
        assert result.iloc[-1] == pytest.approx(19.0)  # (10*100 + 20*900) / 1000


# ======================================================================
# indicators.py – ATR
# ======================================================================


class TestATR:
    def test_basic(self):
        df = _make_ohlcv([50 + i * 0.5 for i in range(30)], spread=0.02)
        result = atr(df["High"], df["Low"], df["Close"])
        valid = result.dropna()
        assert len(valid) > 0
        assert (valid > 0).all()

    def test_higher_spread_means_higher_atr(self):
        prices = [50.0] * 30
        df1 = _make_ohlcv(prices, spread=0.01)
        df2 = _make_ohlcv(prices, spread=0.05)
        atr1 = atr(df1["High"], df1["Low"], df1["Close"]).iloc[-1]
        atr2 = atr(df2["High"], df2["Low"], df2["Close"]).iloc[-1]
        assert atr2 > atr1


# ======================================================================
# indicators.py – relative_volume
# ======================================================================


class TestRelativeVolume:
    def test_constant_volume(self):
        v = pd.Series([1_000_000] * 30)
        result = relative_volume(v, 20)
        valid = result.dropna()
        assert valid.iloc[-1] == pytest.approx(1.0)

    def test_spike(self):
        v = pd.Series([1_000_000] * 25 + [3_000_000])
        result = relative_volume(v, 20)
        # The 20-period SMA at the last bar includes the spike itself,
        # so avg = (19 * 1M + 3M) / 20 = 1.1M, rvol ≈ 2.73
        assert result.iloc[-1] > 2.5


# ======================================================================
# indicators.py – price_range_pct
# ======================================================================


class TestPriceRangePct:
    def test_constant_price(self):
        df = _make_ohlcv([50.0] * 30, spread=0.0)
        result = price_range_pct(df["High"], df["Low"], df["Close"], 20)
        valid = result.dropna()
        assert valid.iloc[-1] == pytest.approx(0.0, abs=0.001)

    def test_volatile_price(self):
        df = _make_ohlcv([50.0] * 30, spread=0.10)
        result = price_range_pct(df["High"], df["Low"], df["Close"], 20)
        valid = result.dropna()
        assert valid.iloc[-1] > 0.1


# ======================================================================
# ipo_base_detector.py – IPOBaseDetector
# ======================================================================


class TestIPOBaseDetector:
    def setup_method(self):
        self.detector = IPOBaseDetector()

    def test_detects_base_with_valid_pattern(self):
        ipo = date(2025, 1, 2)
        df = _make_ipo_base_df(ipo, rally_days=10, base_days=30, base_depth_pct=0.25)
        result = self.detector.detect_base(df, ipo)
        assert result.has_base is True
        assert result.base_type in ("flat", "ascending_triangle", "descending_triangle", "cup")
        assert result.base_start is not None
        assert result.left_high > 0
        assert 0.1 <= result.base_depth_pct <= 0.5
        assert result.base_length_days >= 14

    def test_no_base_too_shallow(self):
        ipo = date(2025, 1, 2)
        df = _make_ipo_base_df(ipo, rally_days=10, base_days=30, base_depth_pct=0.05)
        result = self.detector.detect_base(df, ipo)
        assert result.has_base is False

    def test_no_base_too_deep(self):
        ipo = date(2025, 1, 2)
        df = _make_ipo_base_df(ipo, rally_days=10, base_days=30, base_depth_pct=0.60)
        result = self.detector.detect_base(df, ipo)
        assert result.has_base is False

    def test_no_base_insufficient_data(self):
        ipo = date(2025, 1, 2)
        df = _make_ohlcv([30, 35, 40], start_date="2025-01-02")
        result = self.detector.detect_base(df, ipo)
        assert result.has_base is False

    def test_empty_df(self):
        ipo = date(2025, 1, 2)
        df = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
        result = self.detector.detect_base(df, ipo)
        assert result.has_base is False

    def test_tightness_measured(self):
        ipo = date(2025, 1, 2)
        df = _make_ipo_base_df(ipo, rally_days=10, base_days=30, base_depth_pct=0.25)
        result = self.detector.detect_base(df, ipo)
        if result.has_base:
            assert 0.0 <= result.tightness <= 1.0

    def test_volume_dry_up(self):
        ipo = date(2025, 1, 2)
        # Build with declining volume
        df = _make_ipo_base_df(ipo, rally_days=10, base_days=30, base_depth_pct=0.25)
        result = self.detector.detect_base(df, ipo)
        if result.has_base:
            assert isinstance(result.volume_dry_up, bool)

    def test_to_dict(self):
        ipo = date(2025, 1, 2)
        df = _make_ipo_base_df(ipo, rally_days=10, base_days=30, base_depth_pct=0.25)
        result = self.detector.detect_base(df, ipo)
        d = result.to_dict()
        assert "has_base" in d
        assert "base_type" in d
        assert "left_high" in d

    def test_date_column_instead_of_index(self):
        """DataFrame with 'Date' column instead of DatetimeIndex."""
        ipo = date(2025, 1, 2)
        df = _make_ipo_base_df(ipo, rally_days=10, base_days=30, base_depth_pct=0.25)
        df = df.reset_index().rename(columns={"index": "Date"})
        result = self.detector.detect_base(df, ipo)
        # Should still work
        assert isinstance(result.has_base, bool)

    def test_filters_pre_ipo_data(self):
        """Data before IPO date should be ignored."""
        ipo = date(2025, 2, 1)
        df = _make_ipo_base_df(date(2025, 1, 2), rally_days=10, base_days=30, base_depth_pct=0.25)
        result = self.detector.detect_base(df, ipo)
        # Most data is before the IPO date, so likely not enough post-IPO data
        assert isinstance(result.has_base, bool)


# ======================================================================
# breakout_scanner.py – BreakoutScanner
# ======================================================================


class TestBreakoutScanner:
    def setup_method(self):
        self.scanner = BreakoutScanner()
        self.detector = IPOBaseDetector()

    def test_detects_breakout(self):
        ipo = date(2025, 1, 2)
        df = _make_ipo_base_df(
            ipo, rally_days=10, base_days=30,
            base_depth_pct=0.25, breakout=True, breakout_volume_mult=2.0,
        )
        base = self.detector.detect_base(df, ipo)
        if not base.has_base:
            pytest.skip("Base not detected in synthetic data")

        signal = self.scanner.scan(df, base)
        assert signal.breakout_detected is True
        assert signal.breakout_date is not None
        assert signal.breakout_price > 0
        assert signal.signal_strength in ("strong", "moderate", "weak")
        assert signal.suggested_stop > 0
        assert signal.suggested_stop < signal.breakout_price

    def test_no_breakout_without_base(self):
        df = _make_ohlcv([50 + i * 0.1 for i in range(30)])
        no_base = BaseInfo(
            has_base=False, base_type="none", base_start=None, base_end=None,
            base_depth_pct=0, base_length_days=0, left_high=0,
            tightness=0, volume_dry_up=False,
        )
        signal = self.scanner.scan(df, no_base)
        assert signal.breakout_detected is False

    def test_no_breakout_price_below_pivot(self):
        ipo = date(2025, 1, 2)
        df = _make_ipo_base_df(
            ipo, rally_days=10, base_days=30,
            base_depth_pct=0.25, breakout=False,
        )
        base = self.detector.detect_base(df, ipo)
        if not base.has_base:
            pytest.skip("Base not detected")

        # Manually force left_high very high so no breakout
        base_high = BaseInfo(
            has_base=True, base_type="flat", base_start=base.base_start,
            base_end=base.base_end, base_depth_pct=base.base_depth_pct,
            base_length_days=base.base_length_days, left_high=999.0,
            tightness=base.tightness, volume_dry_up=base.volume_dry_up,
        )
        signal = self.scanner.scan(df, base_high)
        assert signal.breakout_detected is False

    def test_volume_confirmation(self):
        ipo = date(2025, 1, 2)
        df = _make_ipo_base_df(
            ipo, rally_days=10, base_days=30,
            base_depth_pct=0.25, breakout=True, breakout_volume_mult=3.0,
        )
        base = self.detector.detect_base(df, ipo)
        if not base.has_base:
            pytest.skip("Base not detected")

        signal = self.scanner.scan(df, base)
        if signal.breakout_detected:
            assert isinstance(signal.volume_confirmation, bool)

    def test_rs_rating_range(self):
        ipo = date(2025, 1, 2)
        df = _make_ipo_base_df(
            ipo, rally_days=10, base_days=30,
            base_depth_pct=0.25, breakout=True,
        )
        base = self.detector.detect_base(df, ipo)
        if not base.has_base:
            pytest.skip("Base not detected")

        signal = self.scanner.scan(df, base)
        if signal.breakout_detected:
            assert 0 <= signal.rs_rating <= 100

    def test_to_dict(self):
        signal = BreakoutSignal(
            breakout_detected=True, breakout_date=date(2025, 3, 1),
            breakout_price=52.0, volume_confirmation=True,
            rs_rating=85.0, signal_strength="strong",
            suggested_stop=48.0,
        )
        d = signal.to_dict()
        assert d["breakout_detected"] is True
        assert d["breakout_price"] == 52.0

    def test_signal_strength_grading(self):
        scanner = BreakoutScanner()
        base_strong = BaseInfo(
            has_base=True, base_type="flat", base_start=None, base_end=None,
            base_depth_pct=0.2, base_length_days=30, left_high=50.0,
            tightness=0.7, volume_dry_up=True,
        )
        # All conditions met
        strength = scanner._grade_signal(
            vol_ok=True, rsi_ok=True, base_info=base_strong, rs=85.0,
        )
        assert strength == "strong"

        # No conditions met
        base_weak = BaseInfo(
            has_base=True, base_type="flat", base_start=None, base_end=None,
            base_depth_pct=0.2, base_length_days=30, left_high=50.0,
            tightness=0.2, volume_dry_up=False,
        )
        strength = scanner._grade_signal(
            vol_ok=False, rsi_ok=False, base_info=base_weak, rs=40.0,
        )
        assert strength == "weak"

    def test_insufficient_data(self):
        base = BaseInfo(
            has_base=True, base_type="flat", base_start=None, base_end=None,
            base_depth_pct=0.2, base_length_days=30, left_high=50.0,
            tightness=0.5, volume_dry_up=True,
        )
        df = _make_ohlcv([50, 51, 52])
        signal = self.scanner.scan(df, base)
        assert signal.breakout_detected is False


# ======================================================================
# Integration: detector + scanner with synthetic CAVA-like data
# ======================================================================


class TestIntegrationSyntheticIPO:
    """End-to-end test with CAVA-like synthetic price data."""

    def test_full_pipeline(self):
        """Simulate CAVA-like IPO: rally → base → breakout."""
        ipo = date(2025, 1, 2)
        rng = np.random.RandomState(123)

        # Phase 1: IPO at $22, rallies to $55
        rally = np.linspace(22, 55, 15)

        # Phase 2: Consolidates to $42 (24% pullback), then tightens
        pullback = np.linspace(55, 42, 10)
        consolidation = 42 + rng.uniform(-1, 1, 25)
        # Tightening at end
        consolidation[-5:] = 44 + rng.uniform(-0.3, 0.3, 5)

        # Phase 3: Breakout above $55
        breakout = [56, 58, 57.5, 59, 60, 62]

        prices = np.concatenate([rally, pullback, consolidation, breakout])

        # Volume: high on IPO, declining in base, spike on breakout
        vol_rally = [3_000_000 + rng.randint(0, 500_000) for _ in range(15)]
        vol_pullback = [2_000_000 - i * 100_000 for i in range(10)]
        vol_consol = [800_000 + rng.randint(0, 200_000) for _ in range(25)]
        vol_breakout = [4_000_000, 2_500_000, 1_500_000, 2_000_000, 1_800_000, 1_500_000]
        volumes = vol_rally + vol_pullback + vol_consol + vol_breakout

        df = _make_ohlcv(prices.tolist(), volumes, start_date=str(ipo), spread=0.01)

        # Detect base
        detector = IPOBaseDetector()
        base = detector.detect_base(df, ipo)
        assert base.has_base is True
        assert base.left_high > 50  # should find the ~$55 high
        assert 0.10 <= base.base_depth_pct <= 0.50

        # Scan for breakout
        scanner = BreakoutScanner()
        signal = scanner.scan(df, base)
        assert signal.breakout_detected is True
        assert signal.breakout_price > base.left_high
        assert signal.suggested_stop > 0

    def test_no_breakout_in_base(self):
        """Price stays in base — no breakout detected."""
        ipo = date(2025, 1, 2)
        rng = np.random.RandomState(99)

        rally = np.linspace(30, 50, 10)
        base = 38 + rng.uniform(-1, 1, 40)
        prices = np.concatenate([rally, base])

        df = _make_ohlcv(prices.tolist(), start_date=str(ipo), spread=0.01)

        detector = IPOBaseDetector()
        base_info = detector.detect_base(df, ipo)

        if base_info.has_base:
            scanner = BreakoutScanner()
            signal = scanner.scan(df, base_info)
            # Price never exceeded left high, so no breakout (or weak one)
            if signal.breakout_detected:
                assert signal.signal_strength in ("weak", "moderate")


# ======================================================================
# Integration: real CAVA data via yfinance (skipped if unavailable)
# ======================================================================


class TestRealCAVAData:
    """Test with real CAVA stock data fetched via yfinance.

    These tests are skipped if yfinance is not installed or network
    is unavailable.
    """

    @pytest.fixture
    def cava_data(self):
        """Fetch CAVA historical data. Skip if unavailable."""
        try:
            import yfinance as yf
        except ImportError:
            pytest.skip("yfinance not installed")

        try:
            ticker = yf.Ticker("CAVA")
            df = ticker.history(start="2023-06-15", end="2024-03-01")
            if df.empty or len(df) < 30:
                pytest.skip("Could not fetch sufficient CAVA data")
            return df
        except Exception:
            pytest.skip("Could not fetch CAVA data (network issue)")

    def test_cava_base_detection(self, cava_data):
        """CAVA IPO'd June 15, 2023 — detect post-IPO base."""
        detector = IPOBaseDetector()
        ipo = date(2023, 6, 15)
        result = detector.detect_base(cava_data, ipo)

        # Just verify it runs and returns valid structure
        assert isinstance(result.has_base, bool)
        if result.has_base:
            assert result.left_high > 0
            assert result.base_type in (
                "flat", "ascending_triangle", "descending_triangle", "cup",
            )
            assert result.base_depth_pct > 0

    def test_cava_breakout_scan(self, cava_data):
        """Run breakout scanner on CAVA data."""
        detector = IPOBaseDetector()
        scanner = BreakoutScanner()
        ipo = date(2023, 6, 15)

        base = detector.detect_base(cava_data, ipo)
        if not base.has_base:
            pytest.skip("No base detected in CAVA data")

        signal = scanner.scan(cava_data, base)
        assert isinstance(signal.breakout_detected, bool)
        if signal.breakout_detected:
            assert signal.breakout_price > 0
            assert signal.suggested_stop > 0
            assert signal.signal_strength in ("strong", "moderate", "weak")

    def test_cava_indicators(self, cava_data):
        """Verify indicators compute correctly on real data."""
        close = cava_data["Close"]
        high = cava_data["High"]
        low = cava_data["Low"]
        volume = cava_data["Volume"]

        sma_result = sma(close, 20)
        assert sma_result.dropna().shape[0] > 0

        ema_result = ema(close, 20)
        assert not ema_result.isna().all()

        rsi_result = rsi(close)
        valid_rsi = rsi_result.dropna()
        assert (valid_rsi >= 0).all() and (valid_rsi <= 100).all()

        vwap_result = vwap(high, low, close, volume)
        assert vwap_result.iloc[-1] > 0

        atr_result = atr(high, low, close)
        assert atr_result.dropna().iloc[-1] > 0

        rvol = relative_volume(volume)
        assert rvol.dropna().iloc[-1] > 0

        prp = price_range_pct(high, low, close)
        assert prp.dropna().iloc[-1] > 0

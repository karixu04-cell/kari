"""IPO Base Detector - Identify consolidation base patterns after an IPO.

Detects flat bases, ascending/descending triangles, and cup formations
in post-IPO price action.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from src.pattern.indicators import atr, relative_volume, sma

logger = logging.getLogger(__name__)

# Base detection parameters
MIN_BASE_DAYS = 14      # minimum 2 weeks
MAX_BASE_DAYS = 84      # maximum 12 weeks
MIN_DEPTH_PCT = 0.10    # at least 10% pullback
MAX_DEPTH_PCT = 0.50    # no more than 50% pullback
TIGHTNESS_WINDOW = 5    # last N days for tightness measurement


@dataclass
class BaseInfo:
    """Detected base pattern information."""

    has_base: bool
    base_type: str          # 'flat' | 'ascending_triangle' | 'descending_triangle' | 'cup'
    base_start: date | None
    base_end: date | None
    base_depth_pct: float   # drawdown from left-side high
    base_length_days: int
    left_high: float        # breakout target price
    tightness: float        # 0-1, how tight the end of base is
    volume_dry_up: bool     # volume declining during consolidation

    def to_dict(self) -> dict:
        return {
            "has_base": self.has_base,
            "base_type": self.base_type,
            "base_start": self.base_start,
            "base_end": self.base_end,
            "base_depth_pct": self.base_depth_pct,
            "base_length_days": self.base_length_days,
            "left_high": self.left_high,
            "tightness": self.tightness,
            "volume_dry_up": self.volume_dry_up,
        }


_NO_BASE = BaseInfo(
    has_base=False,
    base_type="none",
    base_start=None,
    base_end=None,
    base_depth_pct=0.0,
    base_length_days=0,
    left_high=0.0,
    tightness=0.0,
    volume_dry_up=False,
)


class IPOBaseDetector:
    """Detects consolidation base patterns in post-IPO price data.

    Usage::

        detector = IPOBaseDetector()
        result = detector.detect_base(df, ipo_date=date(2023, 6, 15))
    """

    def __init__(
        self,
        min_base_days: int = MIN_BASE_DAYS,
        max_base_days: int = MAX_BASE_DAYS,
        min_depth_pct: float = MIN_DEPTH_PCT,
        max_depth_pct: float = MAX_DEPTH_PCT,
    ) -> None:
        self.min_base_days = min_base_days
        self.max_base_days = max_base_days
        self.min_depth_pct = min_depth_pct
        self.max_depth_pct = max_depth_pct

    def detect_base(self, df: pd.DataFrame, ipo_date: date) -> BaseInfo:
        """Detect a consolidation base pattern in post-IPO data.

        Parameters
        ----------
        df : pd.DataFrame
            OHLCV DataFrame with columns: Open, High, Low, Close, Volume.
            Index should be DatetimeIndex or have a 'Date' column.
        ipo_date : date
            The IPO listing date.

        Returns
        -------
        BaseInfo with detection results.
        """
        df = self._prepare_df(df, ipo_date)
        if df is None or len(df) < self.min_base_days + 5:
            return _NO_BASE

        # Step (a): Find the first significant high after IPO
        left_high_idx, left_high_price = self._find_left_high(df)
        if left_high_idx is None:
            return _NO_BASE

        # Step (b): Find the base low (pullback from left high)
        base_df = df.loc[left_high_idx:]
        if len(base_df) < self.min_base_days:
            return _NO_BASE

        base_low = base_df["Low"].min()
        depth_pct = (left_high_price - base_low) / left_high_price

        if depth_pct < self.min_depth_pct or depth_pct > self.max_depth_pct:
            return _NO_BASE

        # Step (c): Determine base boundaries
        base_start_date = base_df.index[0].date()
        base_end_date, base_length = self._find_base_end(base_df, left_high_price)

        if base_length < self.min_base_days or base_length > self.max_base_days:
            return _NO_BASE

        # Step (d): Classify the base pattern
        base_type = self._classify_base(base_df, left_high_price, base_low, base_length)

        # Step (e): Measure tightness (volatility contraction at end)
        tightness = self._measure_tightness(base_df, left_high_price)

        # Step (f): Check volume dry-up during consolidation
        vol_dry_up = self._check_volume_dry_up(base_df)

        return BaseInfo(
            has_base=True,
            base_type=base_type,
            base_start=base_start_date,
            base_end=base_end_date,
            base_depth_pct=round(depth_pct, 4),
            base_length_days=base_length,
            left_high=round(left_high_price, 2),
            tightness=round(tightness, 4),
            volume_dry_up=vol_dry_up,
        )

    def _prepare_df(self, df: pd.DataFrame, ipo_date: date) -> pd.DataFrame | None:
        """Normalize the DataFrame: ensure DatetimeIndex, filter post-IPO."""
        df = df.copy()
        if not isinstance(df.index, pd.DatetimeIndex):
            if "Date" in df.columns:
                df["Date"] = pd.to_datetime(df["Date"])
                df = df.set_index("Date")
            else:
                return None

        df = df.sort_index()
        # Filter to post-IPO data
        ipo_ts = pd.Timestamp(ipo_date)
        df = df[df.index >= ipo_ts]
        if df.empty:
            return None

        required = {"Open", "High", "Low", "Close", "Volume"}
        if not required.issubset(df.columns):
            return None

        return df

    def _find_left_high(self, df: pd.DataFrame) -> tuple:
        """Find the first significant high after IPO.

        We look for the highest closing price in the first portion
        of the data (first 1/3 or first 30 days, whichever is larger).
        """
        window = max(len(df) // 3, min(30, len(df)))
        early_df = df.iloc[:window]
        high_idx = early_df["High"].idxmax()
        high_price = early_df.loc[high_idx, "High"]
        return high_idx, high_price

    def _find_base_end(
        self, base_df: pd.DataFrame, left_high: float
    ) -> tuple[date | None, int]:
        """Find where the base ends.

        The base ends when price closes above the left-side high,
        or at the last available bar.
        """
        breakout_mask = base_df["Close"] >= left_high
        if breakout_mask.any():
            breakout_idx = breakout_mask.idxmax()
            end_date = breakout_idx.date()
            length = (breakout_idx - base_df.index[0]).days
        else:
            end_date = base_df.index[-1].date()
            length = (base_df.index[-1] - base_df.index[0]).days

        return end_date, max(length, len(base_df))

    def _classify_base(
        self,
        base_df: pd.DataFrame,
        left_high: float,
        base_low: float,
        base_length: int,
    ) -> str:
        """Classify the base pattern type."""
        if len(base_df) < 4:
            return "flat"

        # Split into halves for trend analysis
        mid = len(base_df) // 2
        first_half = base_df.iloc[:mid]
        second_half = base_df.iloc[mid:]

        first_lows = first_half["Low"].mean()
        second_lows = second_half["Low"].mean()
        first_highs = first_half["High"].mean()
        second_highs = second_half["High"].mean()

        depth = left_high - base_low
        low_trend = (second_lows - first_lows) / depth if depth > 0 else 0
        high_trend = (second_highs - first_highs) / depth if depth > 0 else 0

        # Cup: lows dip then recover (U-shape)
        if len(base_df) >= 20:
            third = len(base_df) // 3
            lows_1 = base_df.iloc[:third]["Low"].mean()
            lows_2 = base_df.iloc[third:2 * third]["Low"].mean()
            lows_3 = base_df.iloc[2 * third:]["Low"].mean()
            if lows_2 < lows_1 and lows_3 > lows_2:
                return "cup"

        # Ascending triangle: rising lows, flat highs
        if low_trend > 0.15 and abs(high_trend) < 0.15:
            return "ascending_triangle"

        # Descending triangle: flat lows, declining highs
        if abs(low_trend) < 0.15 and high_trend < -0.15:
            return "descending_triangle"

        # Flat base: both relatively flat
        return "flat"

    def _measure_tightness(self, base_df: pd.DataFrame, left_high: float) -> float:
        """Measure price tightness at the end of the base (0-1).

        Compares the range of the last TIGHTNESS_WINDOW bars to the
        overall base range. Lower end-range → tighter (closer to 1.0).
        """
        if len(base_df) < TIGHTNESS_WINDOW + 1:
            return 0.0

        overall_range = base_df["High"].max() - base_df["Low"].min()
        if overall_range <= 0:
            return 1.0

        tail = base_df.iloc[-TIGHTNESS_WINDOW:]
        tail_range = tail["High"].max() - tail["Low"].min()
        tightness = 1.0 - (tail_range / overall_range)
        return max(0.0, min(1.0, tightness))

    def _check_volume_dry_up(self, base_df: pd.DataFrame) -> bool:
        """Check if volume is declining during the base formation.

        Compares average volume in the second half to the first half.
        Volume dry-up = second half volume < 70% of first half.
        """
        if len(base_df) < 4:
            return False

        mid = len(base_df) // 2
        first_vol = base_df.iloc[:mid]["Volume"].mean()
        second_vol = base_df.iloc[mid:]["Volume"].mean()

        if first_vol <= 0:
            return False

        return bool(second_vol < first_vol * 0.7)

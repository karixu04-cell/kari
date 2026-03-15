"""Breakout Scanner - Detect breakout and pullback-to-pivot signals.

Works in conjunction with IPOBaseDetector: once a base is identified,
the scanner monitors for a confirmed breakout above the left-side high
and subsequent pullback re-entry opportunities.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

import pandas as pd

from src.pattern.indicators import atr, relative_volume, rsi, sma
from src.pattern.ipo_base_detector import BaseInfo

logger = logging.getLogger(__name__)

# Breakout confirmation thresholds
VOLUME_MULTIPLIER = 1.5     # volume must exceed 1.5x 20-day average
RSI_LOW = 50                # RSI floor for healthy breakout
RSI_HIGH = 70               # RSI ceiling (avoid overbought)
STOP_ATR_MULTIPLIER = 2.0   # stop-loss = breakout price - 2 * ATR


@dataclass
class BreakoutSignal:
    """Detected breakout or pullback signal."""

    breakout_detected: bool
    breakout_date: date | None
    breakout_price: float
    volume_confirmation: bool   # volume > 1.5x 20-day avg
    rs_rating: float            # relative strength 0-100
    signal_strength: str        # 'strong' | 'moderate' | 'weak'
    suggested_stop: float       # suggested stop-loss level

    # Pullback re-entry
    pullback_entry: bool = False
    pullback_date: date | None = None
    pullback_price: float = 0.0

    def to_dict(self) -> dict:
        return {
            "breakout_detected": self.breakout_detected,
            "breakout_date": self.breakout_date,
            "breakout_price": self.breakout_price,
            "volume_confirmation": self.volume_confirmation,
            "rs_rating": self.rs_rating,
            "signal_strength": self.signal_strength,
            "suggested_stop": self.suggested_stop,
            "pullback_entry": self.pullback_entry,
            "pullback_date": self.pullback_date,
            "pullback_price": self.pullback_price,
        }


_NO_BREAKOUT = BreakoutSignal(
    breakout_detected=False,
    breakout_date=None,
    breakout_price=0.0,
    volume_confirmation=False,
    rs_rating=0.0,
    signal_strength="weak",
    suggested_stop=0.0,
)


class BreakoutScanner:
    """Scan for breakout signals above a previously detected base.

    Usage::

        scanner = BreakoutScanner()
        signal = scanner.scan(df, base_info)
    """

    def __init__(
        self,
        volume_multiplier: float = VOLUME_MULTIPLIER,
        rsi_low: int = RSI_LOW,
        rsi_high: int = RSI_HIGH,
        stop_atr_mult: float = STOP_ATR_MULTIPLIER,
    ) -> None:
        self.volume_multiplier = volume_multiplier
        self.rsi_low = rsi_low
        self.rsi_high = rsi_high
        self.stop_atr_mult = stop_atr_mult

    def scan(self, df: pd.DataFrame, base_info: BaseInfo) -> BreakoutSignal:
        """Scan for breakout signals given OHLCV data and a detected base.

        Parameters
        ----------
        df : pd.DataFrame
            OHLCV DataFrame with DatetimeIndex.
        base_info : BaseInfo
            Output from IPOBaseDetector.detect_base().

        Returns
        -------
        BreakoutSignal with detection results.
        """
        if not base_info.has_base or base_info.left_high <= 0:
            return _NO_BREAKOUT

        df = self._prepare_df(df)
        if df is None or len(df) < 20:
            return _NO_BREAKOUT

        pivot = base_info.left_high

        # Compute indicators
        df = df.copy()
        df["rsi"] = rsi(df["Close"])
        df["rvol"] = relative_volume(df["Volume"])
        df["sma20_vol"] = sma(df["Volume"], 20)
        df["atr14"] = atr(df["High"], df["Low"], df["Close"])

        # Find breakout bar: first day close > pivot
        breakout_mask = df["Close"] > pivot
        if not breakout_mask.any():
            return _NO_BREAKOUT

        bo_idx = breakout_mask.idxmax()
        bo_bar = df.loc[bo_idx]
        bo_date = bo_idx.date() if hasattr(bo_idx, "date") else bo_idx

        # Volume confirmation
        vol_ok = False
        sma20_vol_val = bo_bar.get("sma20_vol")
        if pd.notna(sma20_vol_val) and sma20_vol_val > 0:
            vol_ok = bool(bo_bar["Volume"] > sma20_vol_val * self.volume_multiplier)

        # RSI check
        rsi_val = bo_bar.get("rsi", 50.0)
        if pd.isna(rsi_val):
            rsi_val = 50.0
        rsi_ok = self.rsi_low <= rsi_val <= self.rsi_high

        # Relative strength rating (simplified: price position in 52w range)
        rs = self._compute_rs_rating(df, bo_idx)

        # Signal strength
        strength = self._grade_signal(vol_ok, rsi_ok, base_info, rs)

        # Suggested stop-loss
        atr_val = bo_bar.get("atr14", 0.0)
        if pd.isna(atr_val):
            atr_val = 0.0
        stop = round(bo_bar["Close"] - self.stop_atr_mult * atr_val, 2)
        stop = max(stop, 0.01)

        signal = BreakoutSignal(
            breakout_detected=True,
            breakout_date=bo_date,
            breakout_price=round(bo_bar["Close"], 2),
            volume_confirmation=vol_ok,
            rs_rating=round(rs, 1),
            signal_strength=strength,
            suggested_stop=stop,
        )

        # Check for pullback entry after breakout
        self._detect_pullback(df, bo_idx, pivot, signal)

        return signal

    def _prepare_df(self, df: pd.DataFrame) -> pd.DataFrame | None:
        """Ensure DataFrame has DatetimeIndex and required columns."""
        df = df.copy()
        if not isinstance(df.index, pd.DatetimeIndex):
            if "Date" in df.columns:
                df["Date"] = pd.to_datetime(df["Date"])
                df = df.set_index("Date")
            else:
                return None
        df = df.sort_index()
        required = {"Open", "High", "Low", "Close", "Volume"}
        if not required.issubset(df.columns):
            return None
        return df

    def _compute_rs_rating(self, df: pd.DataFrame, as_of_idx) -> float:
        """Compute a simplified relative strength rating (0-100).

        Measures where the current price sits within the 52-week
        (or available) range.
        """
        # Use data up to the breakout bar
        hist = df.loc[:as_of_idx]
        if len(hist) < 2:
            return 50.0

        current = hist["Close"].iloc[-1]
        high_52w = hist["High"].max()
        low_52w = hist["Low"].min()

        if high_52w == low_52w:
            return 50.0

        return ((current - low_52w) / (high_52w - low_52w)) * 100

    def _grade_signal(
        self,
        vol_ok: bool,
        rsi_ok: bool,
        base_info: BaseInfo,
        rs: float,
    ) -> str:
        """Grade the breakout signal strength."""
        score = 0

        if vol_ok:
            score += 2
        if rsi_ok:
            score += 1
        if base_info.tightness >= 0.5:
            score += 1
        if base_info.volume_dry_up:
            score += 1
        if rs >= 80:
            score += 1

        if score >= 4:
            return "strong"
        if score >= 2:
            return "moderate"
        return "weak"

    def _detect_pullback(
        self,
        df: pd.DataFrame,
        bo_idx,
        pivot: float,
        signal: BreakoutSignal,
    ) -> None:
        """Detect a pullback-to-pivot re-entry after the initial breakout.

        A pullback entry occurs when:
        1. Price pulls back to within 3% of the pivot level
        2. Price holds above the pivot (close >= pivot * 0.97)
        3. Occurs within 10 trading days of the breakout
        """
        post_bo = df.loc[bo_idx:].iloc[1:]  # exclude breakout day itself
        if post_bo.empty:
            return

        lookback = post_bo.iloc[:10]  # 10 trading days
        pivot_zone_low = pivot * 0.97

        for idx, row in lookback.iterrows():
            # Price dipped toward pivot and closed above it
            if row["Low"] <= pivot * 1.03 and row["Close"] >= pivot_zone_low:
                signal.pullback_entry = True
                signal.pullback_date = idx.date() if hasattr(idx, "date") else idx
                signal.pullback_price = round(row["Close"], 2)
                break

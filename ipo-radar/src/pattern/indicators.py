"""Technical indicators for IPO pattern analysis.

Pure-pandas implementations — no external TA library dependencies.
All functions accept pandas Series/DataFrames and return pandas Series.
"""

from __future__ import annotations

import pandas as pd


def sma(series: pd.Series, period: int) -> pd.Series:
    """Simple Moving Average.

    Parameters
    ----------
    series : pd.Series
        Price or volume series.
    period : int
        Lookback window (number of bars).

    Returns
    -------
    pd.Series with SMA values. First ``period - 1`` values are NaN.
    """
    return series.rolling(window=period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average.

    Parameters
    ----------
    series : pd.Series
        Price or volume series.
    period : int
        Span for the EMA calculation.

    Returns
    -------
    pd.Series with EMA values.
    """
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index (Wilder's smoothing).

    Parameters
    ----------
    series : pd.Series
        Typically the close price series.
    period : int
        RSI lookback period (default 14).

    Returns
    -------
    pd.Series with RSI values in [0, 100].
    """
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def vwap(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
    """Volume-Weighted Average Price (cumulative intraday-style).

    Uses the typical price ``(high + low + close) / 3`` weighted by volume.

    Parameters
    ----------
    high, low, close : pd.Series
        OHLC price columns.
    volume : pd.Series
        Volume column.

    Returns
    -------
    pd.Series with cumulative VWAP values.
    """
    typical_price = (high + low + close) / 3
    cum_tp_vol = (typical_price * volume).cumsum()
    cum_vol = volume.cumsum()
    return cum_tp_vol / cum_vol


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average True Range.

    Parameters
    ----------
    high, low, close : pd.Series
        OHLC price columns.
    period : int
        Smoothing period (default 14).

    Returns
    -------
    pd.Series with ATR values.
    """
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def relative_volume(volume: pd.Series, period: int = 20) -> pd.Series:
    """Relative volume: current volume / average volume over past N days.

    Parameters
    ----------
    volume : pd.Series
        Volume column.
    period : int
        Lookback period for the average (default 20).

    Returns
    -------
    pd.Series with relative volume ratios. Values > 1 indicate
    above-average volume.
    """
    avg_vol = sma(volume, period)
    return volume / avg_vol


def price_range_pct(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 20) -> pd.Series:
    """Price range as percentage of close over the past N days.

    Measures volatility: ``(rolling_max(high) - rolling_min(low)) / close``.

    Parameters
    ----------
    high, low, close : pd.Series
        OHLC price columns.
    period : int
        Lookback period (default 20).

    Returns
    -------
    pd.Series with range-as-percent values (e.g. 0.15 = 15%).
    """
    rolling_high = high.rolling(window=period, min_periods=period).max()
    rolling_low = low.rolling(window=period, min_periods=period).min()
    return (rolling_high - rolling_low) / close

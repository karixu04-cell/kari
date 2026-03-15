"""形态识别模块 - Pattern Recognition: Identify chart patterns in IPO stocks."""

from dataclasses import dataclass
from enum import Enum


class PatternType(Enum):
    BREAKOUT = "breakout"
    CONSOLIDATION = "consolidation"
    VCP = "volatility_contraction"
    BASE = "base_formation"
    GAP_UP = "gap_up"
    GAP_DOWN = "gap_down"


@dataclass
class PatternMatch:
    """A detected chart pattern."""

    ticker: str
    pattern_type: PatternType
    confidence: float  # 0.0 - 1.0
    start_date: str
    end_date: str
    description: str = ""


class PatternRecognizer:
    """Identifies technical chart patterns in price data."""

    def detect(self, ticker: str, lookback_days: int = 90) -> list[PatternMatch]:
        """Detect patterns for a given ticker."""
        raise NotImplementedError

    def scan(self, tickers: list[str]) -> dict[str, list[PatternMatch]]:
        """Scan multiple tickers for patterns."""
        raise NotImplementedError

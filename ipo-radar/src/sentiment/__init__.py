"""情绪分析模块 - Sentiment Analysis: Analyze market sentiment for IPO stocks."""

from dataclasses import dataclass
from enum import Enum


class SentimentLevel(Enum):
    VERY_BEARISH = -2
    BEARISH = -1
    NEUTRAL = 0
    BULLISH = 1
    VERY_BULLISH = 2


@dataclass
class SentimentResult:
    """Sentiment analysis result for a ticker."""

    ticker: str
    overall: SentimentLevel
    score: float  # -1.0 to 1.0
    news_count: int = 0
    social_mentions: int = 0
    summary: str = ""


class SentimentAnalyzer:
    """Analyzes news and social sentiment for IPO stocks."""

    def analyze(self, ticker: str) -> SentimentResult:
        """Analyze sentiment for a given ticker."""
        raise NotImplementedError

    def batch_analyze(self, tickers: list[str]) -> list[SentimentResult]:
        """Analyze sentiment for multiple tickers."""
        raise NotImplementedError

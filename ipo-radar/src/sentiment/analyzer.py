"""情绪分析模块 - 分析市场对IPO的情绪倾向。"""

from dataclasses import dataclass
from enum import Enum


class Sentiment(Enum):
    """情绪类型。"""

    BULLISH = "bullish"
    NEUTRAL = "neutral"
    BEARISH = "bearish"


@dataclass
class SentimentResult:
    """情绪分析结果。"""

    ticker: str
    sentiment: Sentiment
    score: float  # -1.0 to 1.0
    source_count: int
    summary: str


class SentimentAnalyzer:
    """市场情绪分析器。"""

    def analyze(self, ticker: str) -> SentimentResult:
        """分析指定股票的市场情绪。"""
        raise NotImplementedError

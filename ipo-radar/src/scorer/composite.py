"""综合评分模块 - 多维度综合评估IPO投资价值。"""

from dataclasses import dataclass


@dataclass
class ScoreBreakdown:
    """评分明细。"""

    ticker: str
    fundamental_score: float  # 0-100
    pattern_score: float  # 0-100
    sentiment_score: float  # 0-100
    lockup_risk: float  # 0-100 (higher = riskier)
    earnings_score: float  # 0-100

    @property
    def total_score(self) -> float:
        """加权综合评分。"""
        return (
            self.fundamental_score * 0.30
            + self.pattern_score * 0.20
            + self.sentiment_score * 0.15
            + (100 - self.lockup_risk) * 0.15
            + self.earnings_score * 0.20
        )


class CompositeScorer:
    """综合评分器。"""

    def score(self, ticker: str) -> ScoreBreakdown:
        """对指定股票进行综合评分。"""
        raise NotImplementedError

    def rank(self, tickers: list[str]) -> list[ScoreBreakdown]:
        """对多只股票排名。"""
        results = [self.score(t) for t in tickers]
        return sorted(results, key=lambda s: s.total_score, reverse=True)

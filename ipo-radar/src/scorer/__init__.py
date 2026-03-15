"""综合评分模块 - Composite Scorer: Generate overall IPO investment scores."""

from dataclasses import dataclass, field


@dataclass
class ScoreBreakdown:
    """Breakdown of the composite score by category."""

    fundamentals: float = 0.0
    technicals: float = 0.0
    sentiment: float = 0.0
    lockup_risk: float = 0.0
    earnings_momentum: float = 0.0


@dataclass
class CompositeScore:
    """Final composite score for an IPO stock."""

    ticker: str
    total_score: float  # 0 - 100
    grade: str  # A, B, C, D, F
    breakdown: ScoreBreakdown = field(default_factory=ScoreBreakdown)
    summary: str = ""


class IPOScorer:
    """Combines all analysis modules into a single composite score."""

    WEIGHTS: dict[str, float] = {
        "fundamentals": 0.30,
        "technicals": 0.20,
        "sentiment": 0.15,
        "lockup_risk": 0.15,
        "earnings_momentum": 0.20,
    }

    def score(self, ticker: str) -> CompositeScore:
        """Generate a composite score for a given ticker."""
        raise NotImplementedError

    def rank(self, tickers: list[str]) -> list[CompositeScore]:
        """Score and rank multiple tickers."""
        raise NotImplementedError

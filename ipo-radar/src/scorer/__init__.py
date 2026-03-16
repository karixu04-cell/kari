"""综合评分模块 - Composite Scorer: Generate overall IPO investment scores."""

from dataclasses import dataclass, field

from src.scorer.daily_scan import format_full_report, run_daily_scan
from src.scorer.signal_aggregator import AggregatedReport, SignalAggregator


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


__all__ = [
    "AggregatedReport",
    "CompositeScore",
    "ScoreBreakdown",
    "SignalAggregator",
    "format_full_report",
    "run_daily_scan",
]

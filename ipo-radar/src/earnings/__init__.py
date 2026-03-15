"""业绩追踪模块 - Earnings Tracker: Track post-IPO earnings performance."""

from dataclasses import dataclass
from datetime import date


@dataclass
class EarningsReport:
    """A single earnings report."""

    ticker: str
    report_date: date
    quarter: str
    revenue: float | None = None
    eps: float | None = None
    revenue_estimate: float | None = None
    eps_estimate: float | None = None
    revenue_surprise: float | None = None
    eps_surprise: float | None = None


class EarningsTracker:
    """Tracks earnings reports and surprises for IPO stocks."""

    def get_history(self, ticker: str) -> list[EarningsReport]:
        """Get earnings history for a ticker."""
        raise NotImplementedError

    def get_upcoming(self, tickers: list[str], days: int = 30) -> list[EarningsReport]:
        """Get upcoming earnings dates."""
        raise NotImplementedError

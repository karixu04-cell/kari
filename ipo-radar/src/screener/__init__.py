"""基本面筛选模块 - Fundamental Screener: Filter IPOs by financial metrics."""

from dataclasses import dataclass


@dataclass
class FundamentalMetrics:
    """Key financial metrics for screening."""

    revenue: float | None = None
    revenue_growth: float | None = None
    net_income: float | None = None
    gross_margin: float | None = None
    debt_to_equity: float | None = None
    pe_ratio: float | None = None
    market_cap: float | None = None


class FundamentalScreener:
    """Screens IPOs based on fundamental financial criteria."""

    def __init__(self, min_revenue: float | None = None, min_margin: float | None = None):
        self.min_revenue = min_revenue
        self.min_margin = min_margin

    def get_metrics(self, ticker: str) -> FundamentalMetrics:
        """Retrieve fundamental metrics for a given ticker."""
        raise NotImplementedError

    def screen(self, tickers: list[str]) -> list[str]:
        """Return tickers that pass the screening criteria."""
        raise NotImplementedError

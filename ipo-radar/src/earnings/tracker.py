"""业绩追踪模块 - 跟踪IPO公司上市后的财务表现。"""

from dataclasses import dataclass
from datetime import date


@dataclass
class EarningsReport:
    """财报数据。"""

    ticker: str
    report_date: date
    revenue: float
    net_income: float
    eps: float
    eps_estimate: float | None = None
    revenue_estimate: float | None = None

    @property
    def eps_surprise(self) -> float | None:
        if self.eps_estimate is None:
            return None
        return self.eps - self.eps_estimate


class EarningsTracker:
    """业绩追踪器。"""

    def get_reports(self, ticker: str) -> list[EarningsReport]:
        """获取指定股票的历史财报。"""
        raise NotImplementedError

    def get_upcoming(self, days_ahead: int = 30) -> list[tuple[str, date]]:
        """获取即将发布财报的IPO公司。"""
        raise NotImplementedError

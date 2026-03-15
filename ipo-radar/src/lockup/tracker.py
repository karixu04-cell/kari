"""禁售期跟踪模块 - 监控内部人士和机构的禁售期到期日。"""

from dataclasses import dataclass
from datetime import date


@dataclass
class LockupEvent:
    """禁售期事件。"""

    ticker: str
    expiry_date: date
    shares_locked: int
    holder_type: str  # e.g. "insider", "institution", "vc"
    pct_of_float: float


class LockupTracker:
    """禁售期跟踪器。"""

    def get_upcoming_expirations(self, days_ahead: int = 30) -> list[LockupEvent]:
        """获取即将到期的禁售期事件。"""
        raise NotImplementedError

    def get_by_ticker(self, ticker: str) -> list[LockupEvent]:
        """获取指定股票的禁售期信息。"""
        raise NotImplementedError

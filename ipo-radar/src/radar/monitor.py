"""IPO监控模块 - 追踪即将上市和近期上市的IPO。"""

from dataclasses import dataclass, field
from datetime import date


@dataclass
class IPOListing:
    """IPO上市信息。"""

    ticker: str
    company_name: str
    exchange: str
    ipo_date: date
    offer_price: float
    shares_offered: int
    industry: str = ""
    underwriters: list[str] = field(default_factory=list)


class IPOMonitor:
    """新股监控器，获取和追踪IPO信息。"""

    def __init__(self):
        self._listings: list[IPOListing] = []

    def fetch_upcoming(self) -> list[IPOListing]:
        """获取即将上市的IPO列表。"""
        raise NotImplementedError

    def fetch_recent(self, days: int = 30) -> list[IPOListing]:
        """获取近期上市的IPO列表。"""
        raise NotImplementedError

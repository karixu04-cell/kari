"""新股监控模块 - IPO Radar: Monitor upcoming and recent IPOs."""

from dataclasses import dataclass, field
from datetime import date


@dataclass
class IPOEntry:
    """Represents a single IPO listing."""

    ticker: str
    company_name: str
    exchange: str
    ipo_date: date | None = None
    price_range: tuple[float, float] | None = None
    offer_price: float | None = None
    shares_offered: int | None = None
    status: str = "upcoming"  # upcoming | priced | trading | withdrawn
    metadata: dict = field(default_factory=dict)


class IPORadar:
    """Fetches and tracks upcoming / recent IPO filings."""

    def __init__(self):
        self._entries: list[IPOEntry] = []

    def fetch_upcoming(self) -> list[IPOEntry]:
        """Fetch upcoming IPOs from data sources."""
        raise NotImplementedError

    def fetch_recent(self, days: int = 30) -> list[IPOEntry]:
        """Fetch recently listed IPOs."""
        raise NotImplementedError

    @property
    def entries(self) -> list[IPOEntry]:
        return list(self._entries)

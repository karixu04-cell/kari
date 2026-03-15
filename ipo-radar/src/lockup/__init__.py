"""禁售期跟踪模块 - Lockup Tracker: Track insider lockup expiration dates."""

from dataclasses import dataclass
from datetime import date


@dataclass
class LockupInfo:
    """Lockup period information for an IPO."""

    ticker: str
    ipo_date: date
    lockup_expiry: date
    shares_locked: int | None = None
    percent_of_float: float | None = None
    days_remaining: int = 0


class LockupTracker:
    """Tracks lockup period expirations for IPO stocks."""

    def __init__(self):
        self._lockups: list[LockupInfo] = []

    def get_lockup(self, ticker: str) -> LockupInfo | None:
        """Get lockup info for a specific ticker."""
        raise NotImplementedError

    def get_upcoming_expirations(self, days: int = 30) -> list[LockupInfo]:
        """Get lockups expiring within the given number of days."""
        raise NotImplementedError

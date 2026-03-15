"""Lockup Calendar - Track and query lockup expiration dates across IPOs."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum

logger = logging.getLogger(__name__)


class LockupUrgency(str, Enum):
    """Urgency level based on proximity to lockup expiry."""

    IMMINENT = "imminent"    # ≤3 days to expiry
    WARNING = "warning"      # ≤14 days to expiry
    UPCOMING = "upcoming"    # ≤30 days to expiry
    SAFE = "safe"            # >30 days to expiry
    EXPIRED = "expired"      # already past


@dataclass
class LockupEntry:
    """A single IPO lockup record in the calendar."""

    ticker: str
    company_name: str
    ipo_date: date
    lockup_days: int
    lockup_expiry_date: date
    shares_locked: int | None = None
    shares_outstanding: int | None = None
    current_float: int | None = None
    locked_holders: list[str] | None = None

    @property
    def days_remaining(self) -> int:
        """Days until lockup expiry (negative if already expired)."""
        return (self.lockup_expiry_date - date.today()).days

    @property
    def urgency(self) -> LockupUrgency:
        """Urgency level based on days remaining."""
        d = self.days_remaining
        if d < 0:
            return LockupUrgency.EXPIRED
        if d <= 3:
            return LockupUrgency.IMMINENT
        if d <= 14:
            return LockupUrgency.WARNING
        if d <= 30:
            return LockupUrgency.UPCOMING
        return LockupUrgency.SAFE

    @property
    def supply_impact_ratio(self) -> float | None:
        """Ratio of locked shares to current float.

        A higher ratio means more potential selling pressure when
        the lockup expires.
        """
        if self.shares_locked and self.current_float and self.current_float > 0:
            return self.shares_locked / self.current_float
        return None


class LockupCalendar:
    """Maintains a calendar of lockup expirations for tracked IPOs.

    Usage::

        cal = LockupCalendar()
        cal.add("ACME", "Acme Corp", date(2025, 1, 15), 180,
                shares_locked=50_000_000, current_float=20_000_000)
        upcoming = cal.get_upcoming_expiries(days=30)
        impact = cal.get_supply_impact("ACME")
    """

    def __init__(self) -> None:
        self._entries: dict[str, LockupEntry] = {}

    # -- Mutators --

    def add(
        self,
        ticker: str,
        company_name: str,
        ipo_date: date,
        lockup_days: int,
        *,
        shares_locked: int | None = None,
        shares_outstanding: int | None = None,
        current_float: int | None = None,
        locked_holders: list[str] | None = None,
    ) -> LockupEntry:
        """Add or update a lockup entry."""
        expiry = ipo_date + timedelta(days=lockup_days)
        entry = LockupEntry(
            ticker=ticker.upper(),
            company_name=company_name,
            ipo_date=ipo_date,
            lockup_days=lockup_days,
            lockup_expiry_date=expiry,
            shares_locked=shares_locked,
            shares_outstanding=shares_outstanding,
            current_float=current_float,
            locked_holders=locked_holders,
        )
        self._entries[entry.ticker] = entry
        return entry

    def remove(self, ticker: str) -> bool:
        """Remove a ticker from the calendar. Returns True if found."""
        return self._entries.pop(ticker.upper(), None) is not None

    # -- Queries --

    @property
    def all_entries(self) -> list[LockupEntry]:
        """All entries sorted by expiry date."""
        return sorted(self._entries.values(), key=lambda e: e.lockup_expiry_date)

    def get(self, ticker: str) -> LockupEntry | None:
        """Get a specific ticker's lockup entry."""
        return self._entries.get(ticker.upper())

    def get_upcoming_expiries(self, days: int = 30) -> list[LockupEntry]:
        """Get entries expiring within *days* from today.

        Returns entries sorted by expiry date (soonest first).
        Includes entries that have already expired (negative days_remaining).
        """
        cutoff = date.today() + timedelta(days=days)
        results = [
            e for e in self._entries.values()
            if e.lockup_expiry_date <= cutoff
        ]
        return sorted(results, key=lambda e: e.lockup_expiry_date)

    def get_by_urgency(self, urgency: LockupUrgency) -> list[LockupEntry]:
        """Get all entries matching a specific urgency level."""
        return sorted(
            [e for e in self._entries.values() if e.urgency == urgency],
            key=lambda e: e.lockup_expiry_date,
        )

    def get_supply_impact(self, ticker: str) -> dict:
        """Calculate the supply impact of a lockup expiry for a ticker.

        Returns a dict with:
        - ``ticker``: the ticker symbol
        - ``ratio``: locked_shares / current_float (or None)
        - ``locked_shares``: number of locked shares
        - ``current_float``: current float
        - ``severity``: 'high' (>1.0), 'medium' (0.5-1.0), 'low' (<0.5), or 'unknown'
        - ``urgency``: the LockupUrgency level
        - ``days_remaining``: days until expiry
        """
        entry = self._entries.get(ticker.upper())
        if entry is None:
            return {"ticker": ticker.upper(), "error": "not found"}

        ratio = entry.supply_impact_ratio
        if ratio is None:
            severity = "unknown"
        elif ratio > 1.0:
            severity = "high"
        elif ratio >= 0.5:
            severity = "medium"
        else:
            severity = "low"

        return {
            "ticker": entry.ticker,
            "ratio": ratio,
            "locked_shares": entry.shares_locked,
            "current_float": entry.current_float,
            "severity": severity,
            "urgency": entry.urgency.value,
            "days_remaining": entry.days_remaining,
        }


def format_calendar_report(calendar: LockupCalendar, days: int = 30) -> str:
    """Format a human-readable report of upcoming lockup expirations."""
    upcoming = calendar.get_upcoming_expiries(days=days)
    if not upcoming:
        return f"No lockup expirations in the next {days} days."

    lines = [
        f"{'='*60}",
        f"  Lockup Expiration Calendar (next {days} days)",
        f"{'='*60}",
        "",
    ]

    urgency_icons = {
        LockupUrgency.IMMINENT: "[!!!]",
        LockupUrgency.WARNING: "[!! ]",
        LockupUrgency.UPCOMING: "[!  ]",
        LockupUrgency.EXPIRED: "[EXP]",
        LockupUrgency.SAFE: "[   ]",
    }

    for entry in upcoming:
        icon = urgency_icons.get(entry.urgency, "[   ]")
        days_str = f"{entry.days_remaining}d" if entry.days_remaining >= 0 else "EXPIRED"

        line = f"  {icon} {entry.ticker:<8} {entry.company_name:<25} "
        line += f"Expiry: {entry.lockup_expiry_date.isoformat()}  ({days_str})"
        lines.append(line)

        # Supply impact
        impact = entry.supply_impact_ratio
        if impact is not None:
            lines.append(f"         Supply impact: {impact:.1%} of float")
            if entry.shares_locked:
                lines.append(f"         Locked shares: {entry.shares_locked:,}")
        lines.append("")

    lines.append(f"{'='*60}")
    return "\n".join(lines)

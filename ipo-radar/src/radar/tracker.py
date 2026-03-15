"""IPO Tracker - Persist and manage tracked IPOs in SQLite."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import (
    Column,
    Date,
    Float,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import Session, declarative_base, sessionmaker

logger = logging.getLogger(__name__)

Base = declarative_base()

_DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "ipo_radar.db"


class IPORecord(Base):
    """SQLAlchemy model for tracked IPOs."""

    __tablename__ = "ipo_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(16), nullable=False, index=True)
    company_name = Column(String(256), nullable=False)
    expected_date = Column(Date, nullable=True)
    exchange = Column(String(32), default="")
    price_low = Column(Float, nullable=True)
    price_high = Column(Float, nullable=True)
    offer_price = Column(Float, nullable=True)
    shares_offered = Column(Integer, nullable=True)
    lead_underwriter = Column(String(256), default="")
    status = Column(String(32), default="upcoming")  # upcoming|priced|trading|withdrawn
    notes = Column(Text, default="")
    created_at = Column(Date, default=date.today)
    updated_at = Column(Date, default=date.today, onupdate=date.today)


class IPOTracker:
    """Track IPOs in a local SQLite database.

    Usage::

        tracker = IPOTracker()            # uses default data/ipo_radar.db
        tracker = IPOTracker("custom.db") # custom path

        tracker.add_ipo(ticker="ACME", company_name="Acme Corp",
                        expected_date=date(2026, 4, 1))
        upcoming = tracker.get_upcoming(days=14)
    """

    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            db_path = _DEFAULT_DB_PATH
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        self._engine = create_engine(f"sqlite:///{db_path}", echo=False)
        Base.metadata.create_all(self._engine)
        self._session_factory = sessionmaker(bind=self._engine)

    def _session(self) -> Session:
        return self._session_factory()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add_ipo(
        self,
        ticker: str,
        company_name: str,
        expected_date: date | None = None,
        exchange: str = "",
        price_range: tuple[float, float] | None = None,
        offer_price: float | None = None,
        shares_offered: int | None = None,
        lead_underwriter: str = "",
        status: str = "upcoming",
        notes: str = "",
    ) -> IPORecord:
        """Insert a new IPO into the database. Returns the created record."""
        record = IPORecord(
            ticker=ticker.upper(),
            company_name=company_name,
            expected_date=expected_date,
            exchange=exchange,
            price_low=price_range[0] if price_range else None,
            price_high=price_range[1] if price_range else None,
            offer_price=offer_price,
            shares_offered=shares_offered,
            lead_underwriter=lead_underwriter,
            status=status,
            notes=notes,
        )
        with self._session() as session:
            session.add(record)
            session.commit()
            session.refresh(record)
            # Detach from session so caller can use it freely
            session.expunge(record)
        return record

    def update_status(self, ticker: str, status: str, offer_price: float | None = None) -> bool:
        """Update the status (and optionally the offer price) of a tracked IPO.

        Returns True if a matching record was found and updated.
        """
        with self._session() as session:
            record = (
                session.query(IPORecord)
                .filter(IPORecord.ticker == ticker.upper())
                .first()
            )
            if record is None:
                return False
            record.status = status
            if offer_price is not None:
                record.offer_price = offer_price
            record.updated_at = date.today()
            session.commit()
        return True

    def get_watchlist(self, statuses: tuple[str, ...] = ("upcoming", "priced")) -> list[IPORecord]:
        """Return all records whose status is in *statuses*."""
        with self._session() as session:
            records = (
                session.query(IPORecord)
                .filter(IPORecord.status.in_(statuses))
                .order_by(IPORecord.expected_date)
                .all()
            )
            session.expunge_all()
        return records

    def get_upcoming(self, days: int = 14) -> list[IPORecord]:
        """Return IPOs expected within the next *days* days."""
        today = date.today()
        end = today + timedelta(days=days)
        with self._session() as session:
            records = (
                session.query(IPORecord)
                .filter(
                    IPORecord.expected_date >= today,
                    IPORecord.expected_date <= end,
                    IPORecord.status.in_(("upcoming", "priced")),
                )
                .order_by(IPORecord.expected_date)
                .all()
            )
            session.expunge_all()
        return records

    def get_by_ticker(self, ticker: str) -> IPORecord | None:
        """Look up a single IPO by ticker."""
        with self._session() as session:
            record = (
                session.query(IPORecord)
                .filter(IPORecord.ticker == ticker.upper())
                .first()
            )
            if record:
                session.expunge(record)
        return record

    def import_events(self, events: list) -> int:
        """Bulk-import a list of :class:`~src.radar.ipo_calendar.IPOEvent`.

        Skips duplicates (same ticker already in DB). Returns the count of
        newly inserted records.
        """
        inserted = 0
        with self._session() as session:
            existing_tickers = {
                r.ticker
                for r in session.query(IPORecord.ticker).all()
            }
            for ev in events:
                ticker = (ev.ticker or "").upper()
                if not ticker or ticker in existing_tickers:
                    continue
                record = IPORecord(
                    ticker=ticker,
                    company_name=ev.company_name,
                    expected_date=ev.expected_date,
                    exchange=getattr(ev, "exchange", ""),
                    price_low=ev.price_range[0] if ev.price_range else None,
                    price_high=ev.price_range[1] if ev.price_range else None,
                    shares_offered=ev.shares_offered,
                    lead_underwriter=getattr(ev, "lead_underwriter", ""),
                    status=ev.status,
                )
                session.add(record)
                existing_tickers.add(ticker)
                inserted += 1
            session.commit()
        return inserted

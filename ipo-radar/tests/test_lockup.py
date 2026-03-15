"""Tests for the lockup module (lockup_parser + lockup_calendar)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.lockup.lockup_parser import LockupDetail, extract_lockup_info
from src.lockup.lockup_calendar import (
    LockupCalendar,
    LockupEntry,
    LockupUrgency,
    format_calendar_report,
)


# ======================================================================
# lockup_parser – extract_lockup_info
# ======================================================================


class TestExtractLockupInfo:

    def test_180_day_lockup(self):
        text = (
            "The holders have agreed to a 180-day lock-up period "
            "following the date of this prospectus, during which they "
            "may not sell any shares."
        )
        detail = extract_lockup_info(text)
        assert detail.lockup_days == 180

    def test_90_day_lockup(self):
        text = "Subject to a 90-day lock-up agreement with the underwriters."
        detail = extract_lockup_info(text)
        assert detail.lockup_days == 90

    def test_lockup_period_of_pattern(self):
        text = "The lock-up period of 180 days commences on the closing date."
        detail = extract_lockup_info(text)
        assert detail.lockup_days == 180

    def test_lockup_agreement_pattern(self):
        text = (
            "Pursuant to the lock-up agreements entered into with the "
            "underwriters, insiders will be restricted for 180 days."
        )
        detail = extract_lockup_info(text)
        assert detail.lockup_days == 180

    def test_days_after_prospectus_pattern(self):
        text = "No sales permitted for 180 days after the date of this prospectus."
        detail = extract_lockup_info(text)
        assert detail.lockup_days == 180

    def test_expiry_date_calculation(self):
        text = "The 180-day lock-up period begins on the IPO date."
        ipo = date(2025, 6, 15)
        detail = extract_lockup_info(text, ipo_date=ipo)
        assert detail.lockup_days == 180
        assert detail.lockup_expiry_date == date(2025, 12, 12)

    def test_no_expiry_without_ipo_date(self):
        text = "The 180-day lock-up period."
        detail = extract_lockup_info(text)
        assert detail.lockup_days == 180
        assert detail.lockup_expiry_date is None

    def test_shares_locked_extraction(self):
        text = (
            "Lock-up agreements covering approximately 50,000,000 shares "
            "of our common stock. The 180-day lock-up period."
        )
        detail = extract_lockup_info(text)
        assert detail.shares_locked == 50_000_000

    def test_shares_subject_to_lockup(self):
        text = (
            "Approximately 35,000,000 shares will be subject to lock-up "
            "agreements for a period of 180 days."
        )
        detail = extract_lockup_info(text)
        assert detail.shares_locked == 35_000_000

    def test_holder_types_founders(self):
        text = (
            "Our founders and officers have entered into lock-up agreements "
            "for 180 days following the offering."
        )
        detail = extract_lockup_info(text)
        assert "founders" in detail.locked_holders
        assert "management" in detail.locked_holders

    def test_holder_types_pe_vc(self):
        text = (
            "Venture capital investors and private equity holders are "
            "subject to a 180-day lock-up period."
        )
        detail = extract_lockup_info(text)
        assert "PE_VC" in detail.locked_holders

    def test_holder_types_employees(self):
        text = (
            "All employees holding shares are bound by the 180-day "
            "lock-up agreement."
        )
        detail = extract_lockup_info(text)
        assert "employees" in detail.locked_holders

    def test_early_release_detected(self):
        text = (
            "The underwriters may waive the lock-up restrictions at their "
            "discretion. The 180-day lock-up period."
        )
        detail = extract_lockup_info(text)
        assert detail.early_release_provisions is True

    def test_no_early_release(self):
        text = "A strict 180-day lock-up period applies to all insiders."
        detail = extract_lockup_info(text)
        assert detail.early_release_provisions is False

    def test_total_shares_outstanding(self):
        text = (
            "There will be 100,000,000 shares outstanding after this "
            "offering. The 180-day lock-up period covers insiders."
        )
        detail = extract_lockup_info(text)
        assert detail.total_shares_outstanding == 100_000_000

    def test_float_after_lockup(self):
        text = (
            "There will be 100,000,000 shares outstanding after this "
            "offering. Approximately 60,000,000 shares will be subject "
            "to lock-up agreements for 180 days."
        )
        detail = extract_lockup_info(text)
        assert detail.total_shares_outstanding == 100_000_000
        assert detail.shares_locked == 60_000_000
        assert detail.float_after_lockup == 100_000_000

    def test_empty_text(self):
        detail = extract_lockup_info("")
        assert detail.lockup_days is None
        assert detail.shares_locked is None
        assert detail.locked_holders == []

    def test_no_lockup_info(self):
        text = "This company sells widgets. Revenue was $50 million."
        detail = extract_lockup_info(text)
        assert detail.lockup_days is None

    def test_ignores_unreasonable_days(self):
        """Days outside 30-730 range should be ignored."""
        text = "After just 5 days the lock-up period would end."
        detail = extract_lockup_info(text)
        assert detail.lockup_days is None


# ======================================================================
# lockup_calendar – LockupEntry
# ======================================================================


class TestLockupEntry:
    def _make_entry(self, days_ago: int, lockup_days: int = 180, **kw) -> LockupEntry:
        today = date.today()
        ipo = today - timedelta(days=days_ago)
        return LockupEntry(
            ticker="TEST",
            company_name="Test Corp",
            ipo_date=ipo,
            lockup_days=lockup_days,
            lockup_expiry_date=ipo + timedelta(days=lockup_days),
            **kw,
        )

    def test_days_remaining_future(self):
        entry = self._make_entry(days_ago=90, lockup_days=180)
        assert entry.days_remaining == 90

    def test_days_remaining_expired(self):
        entry = self._make_entry(days_ago=200, lockup_days=180)
        assert entry.days_remaining < 0

    def test_urgency_safe(self):
        entry = self._make_entry(days_ago=90, lockup_days=180)
        assert entry.urgency == LockupUrgency.SAFE

    def test_urgency_upcoming(self):
        entry = self._make_entry(days_ago=160, lockup_days=180)
        assert entry.urgency == LockupUrgency.UPCOMING

    def test_urgency_warning(self):
        entry = self._make_entry(days_ago=170, lockup_days=180)
        assert entry.urgency == LockupUrgency.WARNING

    def test_urgency_imminent(self):
        entry = self._make_entry(days_ago=178, lockup_days=180)
        assert entry.urgency == LockupUrgency.IMMINENT

    def test_urgency_expired(self):
        entry = self._make_entry(days_ago=200, lockup_days=180)
        assert entry.urgency == LockupUrgency.EXPIRED

    def test_supply_impact_ratio(self):
        entry = self._make_entry(
            days_ago=90,
            shares_locked=50_000_000,
            current_float=20_000_000,
        )
        assert entry.supply_impact_ratio == pytest.approx(2.5)

    def test_supply_impact_none(self):
        entry = self._make_entry(days_ago=90)
        assert entry.supply_impact_ratio is None


# ======================================================================
# lockup_calendar – LockupCalendar
# ======================================================================


class TestLockupCalendar:
    def _build_calendar(self) -> LockupCalendar:
        cal = LockupCalendar()
        today = date.today()
        # Expires in 5 days (warning)
        cal.add("WARN", "Warning Corp", today - timedelta(days=175), 180,
                shares_locked=30_000_000, current_float=20_000_000)
        # Expires in 2 days (imminent)
        cal.add("IMM", "Imminent Inc", today - timedelta(days=178), 180,
                shares_locked=50_000_000, current_float=15_000_000)
        # Expires in 90 days (safe)
        cal.add("SAFE", "Safe Ltd", today - timedelta(days=90), 180,
                shares_locked=10_000_000, current_float=40_000_000)
        # Already expired
        cal.add("EXP", "Expired Co", today - timedelta(days=200), 180)
        return cal

    def test_add_and_get(self):
        cal = LockupCalendar()
        entry = cal.add("TEST", "Test", date(2025, 1, 1), 180)
        assert cal.get("TEST") is entry
        assert cal.get("test") is entry  # case-insensitive

    def test_get_nonexistent(self):
        cal = LockupCalendar()
        assert cal.get("NOPE") is None

    def test_remove(self):
        cal = LockupCalendar()
        cal.add("TEST", "Test", date(2025, 1, 1), 180)
        assert cal.remove("TEST") is True
        assert cal.get("TEST") is None
        assert cal.remove("TEST") is False

    def test_all_entries_sorted(self):
        cal = self._build_calendar()
        entries = cal.all_entries
        for i in range(len(entries) - 1):
            assert entries[i].lockup_expiry_date <= entries[i + 1].lockup_expiry_date

    def test_upcoming_expiries_30_days(self):
        cal = self._build_calendar()
        upcoming = cal.get_upcoming_expiries(days=30)
        tickers = [e.ticker for e in upcoming]
        assert "IMM" in tickers
        assert "WARN" in tickers
        assert "EXP" in tickers
        assert "SAFE" not in tickers

    def test_upcoming_expiries_3_days(self):
        cal = self._build_calendar()
        upcoming = cal.get_upcoming_expiries(days=3)
        tickers = [e.ticker for e in upcoming]
        assert "IMM" in tickers
        assert "EXP" in tickers
        assert "WARN" not in tickers

    def test_get_by_urgency(self):
        cal = self._build_calendar()
        imminent = cal.get_by_urgency(LockupUrgency.IMMINENT)
        assert len(imminent) == 1
        assert imminent[0].ticker == "IMM"

    def test_supply_impact_high(self):
        cal = self._build_calendar()
        impact = cal.get_supply_impact("IMM")
        assert impact["severity"] == "high"
        assert impact["ratio"] == pytest.approx(50_000_000 / 15_000_000)

    def test_supply_impact_medium(self):
        cal = self._build_calendar()
        impact = cal.get_supply_impact("WARN")
        assert impact["severity"] == "high"  # 30M/20M = 1.5 > 1.0

    def test_supply_impact_not_found(self):
        cal = LockupCalendar()
        result = cal.get_supply_impact("NOPE")
        assert "error" in result


# ======================================================================
# lockup_calendar – format_calendar_report
# ======================================================================


class TestFormatCalendarReport:
    def test_report_contains_tickers(self):
        cal = LockupCalendar()
        today = date.today()
        cal.add("ABC", "ABC Corp", today - timedelta(days=175), 180,
                shares_locked=20_000_000, current_float=10_000_000)
        report = format_calendar_report(cal, days=30)
        assert "ABC" in report
        assert "ABC Corp" in report

    def test_report_empty(self):
        cal = LockupCalendar()
        report = format_calendar_report(cal, days=30)
        assert "No lockup expirations" in report

    def test_report_shows_urgency_markers(self):
        cal = LockupCalendar()
        today = date.today()
        cal.add("IMM", "Imminent Inc", today - timedelta(days=178), 180)
        report = format_calendar_report(cal, days=30)
        assert "[!!!]" in report


# ======================================================================
# Integration: parser -> calendar
# ======================================================================


class TestParserCalendarIntegration:
    def test_parsed_lockup_feeds_calendar(self):
        """Parse lockup info and add to calendar."""
        s1_text = (
            "UNDERWRITING\n"
            "The 180-day lock-up period applies to all insiders.\n"
            "Our founders and directors are subject to the lock-up agreement.\n"
            "Approximately 75,000,000 shares will be subject to lock-up.\n"
            "There will be 120,000,000 shares of common stock outstanding "
            "after this offering.\n"
        )
        ipo_date = date(2025, 3, 1)
        detail = extract_lockup_info(s1_text, ipo_date=ipo_date)

        assert detail.lockup_days == 180
        assert detail.lockup_expiry_date == date(2025, 8, 28)
        assert detail.shares_locked == 75_000_000

        # Feed into calendar
        cal = LockupCalendar()
        cal.add(
            "NEWIPO",
            "New IPO Corp",
            ipo_date,
            detail.lockup_days,
            shares_locked=detail.shares_locked,
            shares_outstanding=detail.total_shares_outstanding,
            current_float=(
                detail.total_shares_outstanding - detail.shares_locked
                if detail.total_shares_outstanding and detail.shares_locked
                else None
            ),
        )

        entry = cal.get("NEWIPO")
        assert entry is not None
        assert entry.lockup_expiry_date == date(2025, 8, 28)
        assert entry.current_float == 45_000_000

        impact = cal.get_supply_impact("NEWIPO")
        # 75M locked / 45M float = 1.67
        assert impact["ratio"] == pytest.approx(75_000_000 / 45_000_000, rel=0.01)
        assert impact["severity"] == "high"

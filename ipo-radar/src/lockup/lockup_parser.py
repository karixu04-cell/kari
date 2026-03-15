"""Lockup Parser - Extract lockup period information from S-1 filing text."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta


@dataclass
class LockupDetail:
    """Structured lockup information extracted from an S-1 filing."""

    lockup_days: int | None = None
    lockup_expiry_date: date | None = None
    shares_locked: int | None = None
    locked_holders: list[str] = field(default_factory=list)
    early_release_provisions: bool | None = None
    total_shares_outstanding: int | None = None
    float_after_lockup: int | None = None

    # Raw snippets for debugging
    raw_snippets: list[str] = field(default_factory=list)


# Patterns for lockup period duration
_LOCKUP_DAYS_PATTERNS = [
    # "180-day lock-up period"
    re.compile(r"(\d+)[- ]?day\s+lock[- ]?up", re.IGNORECASE),
    # "lock-up period of 180 days"
    re.compile(r"lock[- ]?up\s+period\s+of\s+(\d+)\s+days?", re.IGNORECASE),
    # "lock-up agreements ... for a period of 180 days"
    re.compile(r"lock[- ]?up\s+agreement[s]?\s+[^.]{0,80}?(\d+)\s+days?", re.IGNORECASE),
    # "restricted from selling ... for 180 days"
    re.compile(r"restricted\s+from\s+(?:selling|transferring)[^.]{0,80}?(\d+)\s+days?", re.IGNORECASE),
    # "180 days after the date of this prospectus"
    re.compile(r"(\d+)\s+days?\s+after\s+the\s+date\s+of\s+this\s+prospectus", re.IGNORECASE),
]

# Patterns for locked share counts
_SHARES_LOCKED_PATTERNS = [
    # "approximately 50,000,000 shares ... subject to lock-up"
    re.compile(
        r"(?:approximately|about|a\s+total\s+of)?\s*([\d,]+)\s+shares?\s+[^.]{0,60}?"
        r"(?:subject\s+to|covered\s+by|under)\s+(?:the\s+)?lock[- ]?up",
        re.IGNORECASE,
    ),
    # "lock-up agreements covering 50,000,000 shares"
    re.compile(
        r"lock[- ]?up\s+agreement[s]?\s+(?:covering|relating\s+to|with\s+respect\s+to)"
        r"\s+(?:approximately\s+|about\s+)?([\d,]+)\s+shares?",
        re.IGNORECASE,
    ),
    # "X shares will be subject to lock-up" (subject before lockup)
    re.compile(
        r"([\d,]+)\s+shares?\s+(?:will\s+be\s+|are\s+)?subject\s+to\s+(?:the\s+)?lock[- ]?up",
        re.IGNORECASE,
    ),
]

# Holder type keywords
_HOLDER_KEYWORDS = {
    "founders": re.compile(r"\bfounder[s]?\b", re.IGNORECASE),
    "management": re.compile(r"\b(?:officer[s]?|director[s]?|executive[s]?|management)\b", re.IGNORECASE),
    "PE_VC": re.compile(
        r"\b(?:venture\s+capital|private\s+equity|PE|VC|"
        r"institutional\s+(?:investor|stockholder)|"
        r"investment\s+fund|capital\s+partners)\b",
        re.IGNORECASE,
    ),
    "employees": re.compile(r"\b(?:employee[s]?|staff|team\s+member[s]?)\b", re.IGNORECASE),
}

# Early release / waiver patterns
_EARLY_RELEASE_PATTERNS = [
    re.compile(r"(?:early|prior)\s+release", re.IGNORECASE),
    re.compile(r"waiv(?:e|er)\s+(?:of\s+)?(?:the\s+)?lock[- ]?up", re.IGNORECASE),
    re.compile(r"lock[- ]?up\s+[^.]{0,40}?(?:waiv|releas|terminat)", re.IGNORECASE),
    re.compile(r"release\s+[^.]{0,40}?prior\s+to\s+(?:the\s+)?expiration", re.IGNORECASE),
]

# Total shares outstanding
_TOTAL_SHARES_PATTERNS = [
    re.compile(
        r"([\d,]+)\s+shares?\s+(?:of\s+(?:common\s+stock|our\s+common)\s+)?"
        r"(?:will\s+be\s+)?outstanding\s+(?:immediately\s+)?after",
        re.IGNORECASE,
    ),
    re.compile(
        r"total\s+(?:shares?|number\s+of\s+shares?)\s+(?:of\s+common\s+stock\s+)?"
        r"outstanding[^.]{0,40}?([\d,]+)",
        re.IGNORECASE,
    ),
]


def _extract_lockup_section(s1_text: str) -> str:
    """Extract the lockup-related section(s) from the S-1 text."""
    # Try to find a dedicated lockup section
    lockup_section = re.search(
        r"(?i)(lock[- ]?up\s+agreement[s]?)(.*?)(?=legal\s+matters|experts|additional|$)",
        s1_text,
        re.DOTALL,
    )
    if lockup_section:
        return lockup_section.group(0)[:20000]

    # Fall back to underwriting section which often contains lockup details
    underwriting = re.search(
        r"(?i)(underwriting|plan\s+of\s+distribution)(.*?)(?=legal\s+matters|experts|$)",
        s1_text,
        re.DOTALL,
    )
    if underwriting:
        return underwriting.group(0)[:20000]

    # Last resort: search entire text (capped)
    return s1_text[:50000]


def _parse_int(s: str) -> int | None:
    """Parse a string like '50,000,000' into an integer."""
    try:
        return int(s.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def extract_lockup_info(
    s1_text: str,
    ipo_date: date | None = None,
) -> LockupDetail:
    """Extract lockup period information from S-1 filing text.

    Parameters
    ----------
    s1_text:
        Plain text (HTML-stripped) content of the S-1 filing.
    ipo_date:
        The IPO pricing/listing date. If provided, used to compute
        ``lockup_expiry_date`` from ``lockup_days``.

    Returns
    -------
    LockupDetail with extracted fields. Fields that cannot be determined
    are left as ``None`` or empty.
    """
    detail = LockupDetail()

    if not s1_text:
        return detail

    section = _extract_lockup_section(s1_text)

    # --- Lockup days ---
    # Search both extracted section and full text (section extraction may
    # consume the lockup keyword as a heading, losing the days pattern)
    for search_text in (section, s1_text):
        if detail.lockup_days is not None:
            break
        for pat in _LOCKUP_DAYS_PATTERNS:
            m = pat.search(search_text)
            if m:
                days = int(m.group(1))
                if 30 <= days <= 730:  # sanity check
                    detail.lockup_days = days
                    detail.raw_snippets.append(m.group(0))
                    break

    # --- Lockup expiry date ---
    if detail.lockup_days and ipo_date:
        detail.lockup_expiry_date = ipo_date + timedelta(days=detail.lockup_days)

    # --- Shares locked ---
    for search_text in (section, s1_text):
        if detail.shares_locked is not None:
            break
        for pat in _SHARES_LOCKED_PATTERNS:
            m = pat.search(search_text)
            if m:
                val = _parse_int(m.group(1))
                if val and val > 0:
                    detail.shares_locked = val
                    break

    # --- Locked holder types ---
    holders = []
    # Build context: text near any "lock-up" mention (200 chars each side)
    lockup_context = re.findall(
        r"(?i)(?:.{0,200}lock[- ]?up.{0,200})", s1_text,
    )
    context_text = " ".join(lockup_context) if lockup_context else s1_text
    for holder_type, pat in _HOLDER_KEYWORDS.items():
        if pat.search(context_text):
            holders.append(holder_type)
    detail.locked_holders = holders

    # --- Early release provisions ---
    detail.early_release_provisions = False
    for pat in _EARLY_RELEASE_PATTERNS:
        if pat.search(section):
            detail.early_release_provisions = True
            break

    # --- Total shares outstanding ---
    for pat in _TOTAL_SHARES_PATTERNS:
        m = pat.search(s1_text)  # search full text, not just lockup section
        if m:
            val = _parse_int(m.group(1))
            if val and val > 0:
                detail.total_shares_outstanding = val
                break

    # --- Float after lockup ---
    if detail.total_shares_outstanding and detail.shares_locked:
        # Shares NOT locked = current float; after lockup all become tradable
        detail.float_after_lockup = detail.total_shares_outstanding

    return detail

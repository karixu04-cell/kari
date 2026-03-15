"""S-1 Parser - Extract key financial metrics from SEC S-1 filings."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import requests

logger = logging.getLogger(__name__)

_EDGAR_FILING_URL = "https://www.sec.gov/cgi-bin/browse-edgar"
_EDGAR_FULL_TEXT = "https://efts.sec.gov/LATEST/search-index"
_SEC_HEADERS = {"User-Agent": "IPORadar/0.1 (research tool)", "Accept": "text/html,application/json"}

# Top-tier underwriters for scoring
TOP_UNDERWRITERS = frozenset({
    "goldman sachs", "morgan stanley", "j.p. morgan", "jp morgan",
    "bofa securities", "bank of america", "citigroup", "barclays",
    "credit suisse", "ubs", "deutsche bank",
})


@dataclass
class S1Metrics:
    """Financial metrics extracted from an S-1 filing."""

    company_name: str = ""
    cik: str = ""
    ticker: str = ""

    # Revenue (most recent 3 years, newest first)
    revenues: list[float] = field(default_factory=list)
    revenue_yoy_growth: list[float] = field(default_factory=list)

    gross_margin: float | None = None
    net_income: float | None = None
    cash_and_equivalents: float | None = None
    total_debt: float | None = None
    total_assets: float | None = None
    debt_to_assets: float | None = None

    # Operational
    burn_rate_monthly: float | None = None
    cash_runway_months: float | None = None

    # Offering details
    shares_offered: int | None = None
    price_range: tuple[float, float] | None = None
    implied_market_cap: float | None = None
    lead_underwriter: str = ""
    is_top_underwriter: bool = False

    # Qualitative
    customer_concentration: str = ""
    use_of_proceeds: str = ""

    # Raw source for debugging
    raw_sections: dict[str, str] = field(default_factory=dict)


def extract_key_metrics(
    s1_url: str | None = None,
    *,
    cik: str = "",
    ticker: str = "",
    timeout: int = 20,
) -> S1Metrics:
    """Extract key financial metrics from an S-1 filing.

    Provide either *s1_url* (direct link to the filing) or *cik*/*ticker*
    to look up the latest S-1 on EDGAR.

    Tries sec-api ExtractorApi first; falls back to direct HTML parsing.
    """
    metrics = S1Metrics(cik=cik, ticker=ticker)

    html = _fetch_filing_html(s1_url=s1_url, cik=cik, ticker=ticker, timeout=timeout)
    if not html:
        logger.warning("Could not retrieve S-1 filing content")
        return metrics

    # Try sec-api extractor first, fall back to HTML parsing
    sections = _extract_sections_secapi(html)
    if not sections:
        sections = _extract_sections_html(html)

    metrics.raw_sections = sections
    _parse_financials(metrics, sections)
    _parse_offering_details(metrics, sections)
    _parse_qualitative(metrics, sections)
    _compute_derived(metrics)

    return metrics


# ---------------------------------------------------------------------------
# Filing retrieval
# ---------------------------------------------------------------------------


def _fetch_filing_html(
    s1_url: str | None, cik: str, ticker: str, timeout: int
) -> str:
    """Fetch the S-1 filing HTML from EDGAR or a direct URL."""
    if s1_url:
        try:
            resp = requests.get(s1_url, headers=_SEC_HEADERS, timeout=timeout)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:
            logger.warning("Failed to fetch S-1 from URL %s: %s", s1_url, exc)
            return ""

    # Look up by CIK or ticker via EDGAR full-text search
    query = cik or ticker
    if not query:
        return ""

    params = {
        "q": f'"{query}"',
        "forms": "S-1",
        "dateRange": "custom",
    }
    try:
        resp = requests.get(_EDGAR_FULL_TEXT, params=params, headers=_SEC_HEADERS, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        hits = data.get("hits", {}).get("hits", [])
        if not hits:
            return ""
        # Get the first filing URL
        source = hits[0].get("_source", {})
        file_url = source.get("file_url", "")
        if not file_url:
            return ""
        if not file_url.startswith("http"):
            file_url = f"https://www.sec.gov{file_url}"
        resp2 = requests.get(file_url, headers=_SEC_HEADERS, timeout=timeout)
        resp2.raise_for_status()
        return resp2.text
    except requests.RequestException as exc:
        logger.warning("EDGAR search failed for %s: %s", query, exc)
        return ""


# ---------------------------------------------------------------------------
# Section extraction
# ---------------------------------------------------------------------------


def _extract_sections_secapi(html: str) -> dict[str, str]:
    """Try to use sec-api ExtractorApi to parse the S-1 into sections."""
    try:
        import os
        from sec_api import ExtractorApi

        api_key = os.environ.get("SEC_API_KEY", "")
        if not api_key:
            return {}

        extractor = ExtractorApi(api_key)
        # ExtractorApi works with URLs; since we already have HTML,
        # this path is only viable if we have the original URL.
        # Fall back to HTML parsing.
        return {}
    except (ImportError, Exception):
        return {}


def _extract_sections_html(html: str) -> dict[str, str]:
    """Parse S-1 HTML into logical sections by heading patterns."""
    sections: dict[str, str] = {}
    text = _strip_html_tags(html)

    section_patterns = {
        "prospectus_summary": r"(?i)(prospectus\s+summary)(.*?)(?=risk\s+factors|use\s+of\s+proceeds|$)",
        "risk_factors": r"(?i)(risk\s+factors)(.*?)(?=use\s+of\s+proceeds|forward[- ]looking|$)",
        "use_of_proceeds": r"(?i)(use\s+of\s+proceeds)(.*?)(?=dividend|capitalization|dilution|$)",
        "capitalization": r"(?i)(capitalization)(.*?)(?=dilution|selected|management|$)",
        "financial_data": r"(?i)(selected\s+(?:consolidated\s+)?financial\s+data|summary.*?financial)(.*?)(?=management.s?\s+discussion|$)",
        "md_and_a": r"(?i)(management.s?\s+discussion\s+and\s+analysis)(.*?)(?=business|quantitative|$)",
        "business": r"(?i)(\bbusiness\b)(.*?)(?=management|certain\s+relationships|$)",
        "underwriting": r"(?i)(underwriting|plan\s+of\s+distribution)(.*?)(?=legal\s+matters|experts|$)",
    }

    for key, pattern in section_patterns.items():
        match = re.search(pattern, text, re.DOTALL)
        if match:
            sections[key] = match.group(2)[:50000]  # cap at 50k chars

    return sections


def _strip_html_tags(html: str) -> str:
    """Remove HTML tags, keeping text content."""
    text = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

_MONEY_RE = re.compile(
    r"\$?\s*([\d,]+(?:\.\d+)?)\s*(?:(million|billion|thousand|M|B|K))?",
    re.IGNORECASE,
)

_MULTIPLIERS = {
    "thousand": 1e3, "k": 1e3,
    "million": 1e6, "m": 1e6,
    "billion": 1e9, "b": 1e9,
}


def parse_money(text: str) -> float | None:
    """Parse a monetary value string into a float (in dollars)."""
    if not text:
        return None
    match = _MONEY_RE.search(text.replace(",", ""))
    if not match:
        return None
    value = float(match.group(1).replace(",", ""))
    unit = (match.group(2) or "").lower()
    multiplier = _MULTIPLIERS.get(unit, 1.0)
    return value * multiplier


def _find_monetary_values(text: str, keyword: str, count: int = 3) -> list[float]:
    """Find up to *count* monetary values near a keyword in text."""
    if not text:
        return []
    # Find all dollar values that appear after the keyword (within a window)
    # First, locate the keyword, then extract all $ values from surrounding text
    kw_pattern = re.compile(rf"(?i){re.escape(keyword)}")
    kw_match = kw_pattern.search(text)
    if not kw_match:
        return []

    # Search from keyword position onwards (up to 1000 chars)
    search_text = text[kw_match.start():kw_match.start() + 1000]
    dollar_pattern = re.compile(
        r"\$\s*([\d,]+(?:\.\d+)?)\s*(?:(million|billion|thousand|M|B|K))?",
        re.IGNORECASE,
    )
    values = []
    for match in dollar_pattern.finditer(search_text):
        raw = match.group(1).replace(",", "")
        try:
            val = float(raw)
        except ValueError:
            continue
        unit = (match.group(2) or "").lower()
        multiplier = _MULTIPLIERS.get(unit, 1.0)
        values.append(val * multiplier)
        if len(values) >= count:
            break
    return values


def _parse_financials(metrics: S1Metrics, sections: dict[str, str]) -> None:
    """Extract revenue, margins, cash, debt from financial sections."""
    fin_text = sections.get("financial_data", "") + sections.get("md_and_a", "")

    # Revenue
    revenues = _find_monetary_values(fin_text, "revenue", count=3)
    if not revenues:
        revenues = _find_monetary_values(fin_text, "net revenue", count=3)
    if not revenues:
        revenues = _find_monetary_values(fin_text, "total revenue", count=3)
    metrics.revenues = revenues

    # YoY growth
    if len(revenues) >= 2:
        growths = []
        for i in range(len(revenues) - 1):
            older = revenues[i + 1]
            if older and older > 0:
                growths.append((revenues[i] - older) / older)
            else:
                growths.append(0.0)
        metrics.revenue_yoy_growth = growths

    # Gross margin
    gross_profits = _find_monetary_values(fin_text, "gross profit", count=1)
    if gross_profits and revenues:
        metrics.gross_margin = gross_profits[0] / revenues[0] if revenues[0] > 0 else None

    # Net income
    net_vals = _find_monetary_values(fin_text, "net income", count=1)
    if not net_vals:
        net_vals = _find_monetary_values(fin_text, "net loss", count=1)
        if net_vals:
            net_vals = [-v for v in net_vals]
    if net_vals:
        metrics.net_income = net_vals[0]

    # Cash
    cash_vals = _find_monetary_values(fin_text, "cash and cash equivalents", count=1)
    if not cash_vals:
        cash_vals = _find_monetary_values(fin_text, "cash, cash equivalents", count=1)
    if cash_vals:
        metrics.cash_and_equivalents = cash_vals[0]

    # Debt
    debt_vals = _find_monetary_values(fin_text, "total debt", count=1)
    if not debt_vals:
        debt_vals = _find_monetary_values(fin_text, "total liabilities", count=1)
    if debt_vals:
        metrics.total_debt = debt_vals[0]

    # Total assets
    asset_vals = _find_monetary_values(fin_text, "total assets", count=1)
    if asset_vals:
        metrics.total_assets = asset_vals[0]


def _parse_offering_details(metrics: S1Metrics, sections: dict[str, str]) -> None:
    """Extract offering size, price range, underwriter from relevant sections."""
    summary = sections.get("prospectus_summary", "")
    underwriting = sections.get("underwriting", "")

    # Shares offered
    shares_match = re.search(
        r"(?i)(?:offering|selling)\s+([\d,]+)\s+shares",
        summary,
    )
    if shares_match:
        try:
            metrics.shares_offered = int(shares_match.group(1).replace(",", ""))
        except ValueError:
            pass

    # Price range
    price_match = re.search(
        r"\$\s*([\d.]+)\s*(?:and|to|-)\s*\$\s*([\d.]+)\s*per\s+share",
        summary, re.IGNORECASE,
    )
    if price_match:
        try:
            metrics.price_range = (float(price_match.group(1)), float(price_match.group(2)))
        except ValueError:
            pass

    # Lead underwriter
    for text in (underwriting, summary):
        uw_match = re.search(
            r"(?i)(?:lead\s+)?(?:book[- ]running\s+)?(?:manager|underwriter)[s:]?\s+(?:is\s+|are\s+)?([A-Z][\w\s&,.]+?)(?:\.|;|\n)",
            text,
        )
        if uw_match:
            metrics.lead_underwriter = uw_match.group(1).strip()
            metrics.is_top_underwriter = metrics.lead_underwriter.lower() in TOP_UNDERWRITERS
            break


def _parse_qualitative(metrics: S1Metrics, sections: dict[str, str]) -> None:
    """Extract customer concentration and use of proceeds."""
    # Use of proceeds
    uop = sections.get("use_of_proceeds", "")
    if uop:
        # Take first 500 chars as summary
        metrics.use_of_proceeds = uop.strip()[:500]

    # Customer concentration
    risk_text = sections.get("risk_factors", "") + sections.get("business", "")
    conc_match = re.search(
        r"(?i)((?:one|single|largest|major)\s+customer[^.]*(?:account|represent|comprise)[^.]*\.)",
        risk_text,
    )
    if conc_match:
        metrics.customer_concentration = conc_match.group(1).strip()


def _compute_derived(metrics: S1Metrics) -> None:
    """Compute derived metrics from parsed data."""
    # Debt-to-assets ratio
    if metrics.total_debt and metrics.total_assets and metrics.total_assets > 0:
        metrics.debt_to_assets = metrics.total_debt / metrics.total_assets

    # Cash runway
    if metrics.cash_and_equivalents and metrics.net_income and metrics.net_income < 0:
        monthly_burn = abs(metrics.net_income) / 12
        if monthly_burn > 0:
            metrics.burn_rate_monthly = monthly_burn
            metrics.cash_runway_months = metrics.cash_and_equivalents / monthly_burn

    # Implied market cap
    if metrics.shares_offered and metrics.price_range:
        mid_price = (metrics.price_range[0] + metrics.price_range[1]) / 2
        # Rough estimate: offered shares are typically 10-20% of total
        # Use 15% as default assumption
        estimated_total_shares = metrics.shares_offered / 0.15
        metrics.implied_market_cap = estimated_total_shares * mid_price

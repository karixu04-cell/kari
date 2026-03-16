"""Earnings Analyzer - Analyze post-IPO earnings performance.

Uses yfinance to fetch earnings history, estimates, and financials,
then produces a structured analysis with buy/caution signals.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime

import yfinance as yf

logger = logging.getLogger(__name__)


@dataclass
class EarningsAnalysis:
    """Structured earnings analysis result."""

    ticker: str
    report_date: date | None = None
    revenue: float | None = None
    revenue_yoy_growth: float | None = None
    eps: float | None = None
    eps_surprise_pct: float | None = None
    revenue_surprise_pct: float | None = None
    guidance: str = "none"  # 'raised' | 'maintained' | 'lowered' | 'none'
    gross_margin: float | None = None
    gross_margin_change: float | None = None  # vs prior quarter
    is_first_public_report: bool = False
    vs_s1_trajectory: str = "stable"  # 'accelerating' | 'stable' | 'decelerating'
    signal: str = "neutral"  # 'strong_buy' | 'buy' | 'neutral' | 'caution'
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "report_date": self.report_date.isoformat() if self.report_date else None,
            "revenue": self.revenue,
            "revenue_yoy_growth": self.revenue_yoy_growth,
            "eps": self.eps,
            "eps_surprise_pct": self.eps_surprise_pct,
            "revenue_surprise_pct": self.revenue_surprise_pct,
            "guidance": self.guidance,
            "gross_margin": self.gross_margin,
            "gross_margin_change": self.gross_margin_change,
            "is_first_public_report": self.is_first_public_report,
            "vs_s1_trajectory": self.vs_s1_trajectory,
            "signal": self.signal,
            "details": self.details,
        }


# ---------------------------------------------------------------------------
# Data fetching helpers
# ---------------------------------------------------------------------------


def _safe_float(val) -> float | None:
    """Convert a value to float safely."""
    if val is None:
        return None
    try:
        f = float(val)
        if f != f:  # NaN check
            return None
        return f
    except (ValueError, TypeError):
        return None


def _pct_change(current: float | None, previous: float | None) -> float | None:
    """Compute percentage change: (current - previous) / |previous| * 100."""
    if current is None or previous is None or previous == 0:
        return None
    return round((current - previous) / abs(previous) * 100, 2)


def _fetch_earnings_data(ticker: str) -> dict:
    """Fetch raw earnings data from yfinance.

    Returns a dict with keys: quarterly_earnings, quarterly_financials,
    income_stmt, earnings_dates, info.
    """
    stock = yf.Ticker(ticker)

    data: dict = {
        "quarterly_earnings": None,
        "quarterly_financials": None,
        "income_stmt": None,
        "earnings_dates": None,
        "info": {},
    }

    try:
        data["info"] = stock.info or {}
    except Exception:
        pass

    try:
        qe = stock.quarterly_earnings
        if qe is not None and not qe.empty:
            data["quarterly_earnings"] = qe
    except Exception as exc:
        logger.debug("quarterly_earnings failed for %s: %s", ticker, exc)

    try:
        qf = stock.quarterly_financials
        if qf is not None and not qf.empty:
            data["quarterly_financials"] = qf
    except Exception as exc:
        logger.debug("quarterly_financials failed for %s: %s", ticker, exc)

    try:
        inc = stock.quarterly_income_stmt
        if inc is not None and not inc.empty:
            data["income_stmt"] = inc
    except Exception as exc:
        logger.debug("quarterly_income_stmt failed for %s: %s", ticker, exc)

    try:
        ed = stock.earnings_dates
        if ed is not None and not ed.empty:
            data["earnings_dates"] = ed
    except Exception as exc:
        logger.debug("earnings_dates failed for %s: %s", ticker, exc)

    return data


# ---------------------------------------------------------------------------
# Analysis logic
# ---------------------------------------------------------------------------


def _compute_eps_surprise(earnings_dates) -> tuple[float | None, float | None]:
    """Extract latest EPS actual and surprise % from earnings_dates DataFrame.

    Returns (eps_actual, eps_surprise_pct).
    """
    if earnings_dates is None or earnings_dates.empty:
        return None, None

    # earnings_dates columns: 'EPS Estimate', 'Reported EPS', 'Surprise(%)'
    # Filter to rows with reported data (past earnings)
    reported = earnings_dates.dropna(subset=["Reported EPS"])
    if reported.empty:
        return None, None

    latest = reported.iloc[0]
    eps = _safe_float(latest.get("Reported EPS"))
    surprise = _safe_float(latest.get("Surprise(%)"))

    return eps, surprise


def _compute_revenue_surprise(earnings_dates, quarterly_earnings) -> tuple[float | None, float | None]:
    """Compute revenue and revenue surprise %.

    Returns (revenue, revenue_surprise_pct).
    """
    if quarterly_earnings is None or quarterly_earnings.empty:
        return None, None

    # quarterly_earnings has columns: 'Revenue', 'Earnings'
    latest_rev = _safe_float(quarterly_earnings.iloc[0].get("Revenue"))

    # yfinance earnings_dates may have 'Revenue Estimate' in some versions
    if earnings_dates is not None and not earnings_dates.empty:
        reported = earnings_dates.dropna(subset=["Reported EPS"])
        if not reported.empty:
            rev_est = _safe_float(reported.iloc[0].get("Revenue Estimate"))
            if latest_rev is not None and rev_est is not None and rev_est != 0:
                rev_surprise = round((latest_rev - rev_est) / abs(rev_est) * 100, 2)
                return latest_rev, rev_surprise

    return latest_rev, None


def _compute_revenue_yoy_growth(quarterly_earnings) -> float | None:
    """Compute YoY revenue growth from quarterly data.

    Compares latest quarter to same quarter last year (4 quarters ago).
    """
    if quarterly_earnings is None or len(quarterly_earnings) < 5:
        return None

    current = _safe_float(quarterly_earnings.iloc[0].get("Revenue"))
    year_ago = _safe_float(quarterly_earnings.iloc[4].get("Revenue"))

    return _pct_change(current, year_ago)


def _compute_gross_margin(income_stmt) -> tuple[float | None, float | None]:
    """Compute gross margin and change from prior quarter.

    Returns (gross_margin, gross_margin_change).
    """
    if income_stmt is None or income_stmt.empty:
        return None, None

    # income_stmt columns are dates, rows are line items
    # Look for 'Gross Profit' and 'Total Revenue'
    cols = income_stmt.columns.tolist()
    if len(cols) < 1:
        return None, None

    def _get_margin(col_idx: int) -> float | None:
        if col_idx >= len(cols):
            return None
        col = cols[col_idx]
        gross_profit = None
        total_revenue = None

        for row_name in income_stmt.index:
            row_lower = str(row_name).lower().replace("_", " ")
            if "gross profit" in row_lower:
                gross_profit = _safe_float(income_stmt.loc[row_name, col])
            if "total revenue" in row_lower or row_lower == "revenue":
                total_revenue = _safe_float(income_stmt.loc[row_name, col])

        if gross_profit is not None and total_revenue and total_revenue != 0:
            return round(gross_profit / total_revenue * 100, 2)
        return None

    current_margin = _get_margin(0)
    prior_margin = _get_margin(1)

    margin_change = None
    if current_margin is not None and prior_margin is not None:
        margin_change = round(current_margin - prior_margin, 2)

    return current_margin, margin_change


def _determine_guidance(info: dict) -> str:
    """Determine guidance direction from available info.

    yfinance doesn't directly provide guidance, so we infer from
    analyst revisions and target price changes.
    """
    # Check recommendation changes
    rec = info.get("recommendationKey", "")
    target_mean = _safe_float(info.get("targetMeanPrice"))
    current_price = _safe_float(info.get("currentPrice"))

    # If target is significantly above current price → likely raised guidance
    if target_mean and current_price and current_price > 0:
        upside = (target_mean - current_price) / current_price
        if upside > 0.20:
            return "raised"
        if upside < -0.05:
            return "lowered"
        return "maintained"

    if rec in ("strong_buy", "buy"):
        return "raised"
    if rec in ("sell", "strong_sell"):
        return "lowered"

    return "none"


def _determine_trajectory(quarterly_earnings) -> str:
    """Determine revenue growth trajectory: accelerating, stable, or decelerating.

    Compares recent quarters' sequential growth rates.
    """
    if quarterly_earnings is None or len(quarterly_earnings) < 3:
        return "stable"

    revenues = []
    for i in range(min(4, len(quarterly_earnings))):
        rev = _safe_float(quarterly_earnings.iloc[i].get("Revenue"))
        if rev is not None:
            revenues.append(rev)

    if len(revenues) < 3:
        return "stable"

    # revenues[0] = most recent, revenues[1] = prior, etc.
    # Growth rate: (recent - prior) / |prior|
    growth_rates = []
    for i in range(len(revenues) - 1):
        if revenues[i + 1] != 0:
            rate = (revenues[i] - revenues[i + 1]) / abs(revenues[i + 1])
            growth_rates.append(rate)

    if len(growth_rates) < 2:
        return "stable"

    # Compare most recent growth to prior growth
    # growth_rates[0] = latest, growth_rates[1] = prior
    delta = growth_rates[0] - growth_rates[1]

    if delta > 0.03:  # 3pp acceleration threshold
        return "accelerating"
    if delta < -0.03:
        return "decelerating"
    return "stable"


def _is_first_report(quarterly_earnings, info: dict) -> bool:
    """Check if this is likely the first public earnings report.

    Heuristic: fewer than 2 quarterly reports available,
    or IPO date is within last 6 months.
    """
    if quarterly_earnings is not None and len(quarterly_earnings) <= 1:
        return True

    # Check if IPO date is recent (yfinance sometimes has this)
    ipo_date_str = info.get("ipoDate", "")
    if ipo_date_str:
        try:
            ipo_date = datetime.strptime(str(ipo_date_str), "%Y-%m-%d").date()
            days_since_ipo = (date.today() - ipo_date).days
            if days_since_ipo < 180:
                return True
        except (ValueError, TypeError):
            pass

    return False


def _determine_signal(
    eps_surprise_pct: float | None,
    revenue_surprise_pct: float | None,
    guidance: str,
) -> str:
    """Determine trading signal based on earnings results.

    Signal logic:
    - EPS + revenue both beat + guidance raised → strong_buy
    - Only revenue beats OR only EPS beats → buy
    - In line with estimates → neutral
    - Below estimates → caution
    """
    eps_beat = eps_surprise_pct is not None and eps_surprise_pct > 0
    rev_beat = revenue_surprise_pct is not None and revenue_surprise_pct > 0
    eps_miss = eps_surprise_pct is not None and eps_surprise_pct < 0
    rev_miss = revenue_surprise_pct is not None and revenue_surprise_pct < 0

    # strong_buy: both beat + guidance raised
    if eps_beat and rev_beat and guidance == "raised":
        return "strong_buy"

    # buy: at least one beat (and no miss on the other)
    if (eps_beat or rev_beat) and not eps_miss and not rev_miss:
        return "buy"

    # Also buy: both beat even without raised guidance
    if eps_beat and rev_beat:
        return "buy"

    # caution: any miss
    if eps_miss or rev_miss:
        return "caution"

    # neutral: everything else
    return "neutral"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyze_earnings(ticker: str) -> EarningsAnalysis:
    """Analyze the latest earnings for a ticker.

    Fetches data from yfinance, computes surprises, margins, trajectory,
    and generates a signal.

    Parameters
    ----------
    ticker : str
        Stock ticker symbol (e.g. "CAVA").

    Returns
    -------
    EarningsAnalysis with all computed fields.
    """
    ticker = ticker.upper().strip()
    result = EarningsAnalysis(ticker=ticker)

    try:
        data = _fetch_earnings_data(ticker)
    except Exception as exc:
        logger.error("Failed to fetch earnings data for %s: %s", ticker, exc)
        result.signal = "neutral"
        result.details = {"error": str(exc)}
        return result

    quarterly_earnings = data["quarterly_earnings"]
    income_stmt = data["income_stmt"]
    earnings_dates = data["earnings_dates"]
    info = data["info"]

    # Report date
    if earnings_dates is not None and not earnings_dates.empty:
        reported = earnings_dates.dropna(subset=["Reported EPS"])
        if not reported.empty:
            idx = reported.index[0]
            if hasattr(idx, "date"):
                result.report_date = idx.date()
            elif isinstance(idx, date):
                result.report_date = idx

    # EPS and surprise
    eps, eps_surprise = _compute_eps_surprise(earnings_dates)
    result.eps = eps
    result.eps_surprise_pct = eps_surprise

    # Revenue and surprise
    revenue, rev_surprise = _compute_revenue_surprise(earnings_dates, quarterly_earnings)
    result.revenue = revenue
    result.revenue_surprise_pct = rev_surprise

    # Revenue YoY growth
    result.revenue_yoy_growth = _compute_revenue_yoy_growth(quarterly_earnings)

    # Gross margin
    gross_margin, margin_change = _compute_gross_margin(income_stmt)
    result.gross_margin = gross_margin
    result.gross_margin_change = margin_change

    # Guidance (inferred)
    result.guidance = _determine_guidance(info)

    # First public report?
    result.is_first_public_report = _is_first_report(quarterly_earnings, info)

    # Growth trajectory
    result.vs_s1_trajectory = _determine_trajectory(quarterly_earnings)

    # Signal
    result.signal = _determine_signal(
        result.eps_surprise_pct,
        result.revenue_surprise_pct,
        result.guidance,
    )

    return result


def format_earnings_analysis(analysis: EarningsAnalysis) -> str:
    """Format a human-readable earnings analysis report."""
    lines = [
        f"{'=' * 55}",
        f"  Earnings Analysis: {analysis.ticker}",
        f"{'=' * 55}",
        "",
    ]

    if analysis.report_date:
        lines.append(f"  Report date:        {analysis.report_date}")

    if analysis.revenue is not None:
        rev_str = f"${analysis.revenue / 1e6:,.1f}M" if analysis.revenue > 1e6 else f"${analysis.revenue:,.0f}"
        lines.append(f"  Revenue:            {rev_str}")

    if analysis.revenue_yoy_growth is not None:
        lines.append(f"  Revenue YoY growth: {analysis.revenue_yoy_growth:+.1f}%")

    if analysis.eps is not None:
        lines.append(f"  EPS:                ${analysis.eps:.2f}")

    if analysis.eps_surprise_pct is not None:
        emoji = "+" if analysis.eps_surprise_pct > 0 else ""
        lines.append(f"  EPS surprise:       {emoji}{analysis.eps_surprise_pct:.1f}%")

    if analysis.revenue_surprise_pct is not None:
        emoji = "+" if analysis.revenue_surprise_pct > 0 else ""
        lines.append(f"  Revenue surprise:   {emoji}{analysis.revenue_surprise_pct:.1f}%")

    lines.append(f"  Guidance:           {analysis.guidance}")

    if analysis.gross_margin is not None:
        lines.append(f"  Gross margin:       {analysis.gross_margin:.1f}%")
        if analysis.gross_margin_change is not None:
            lines.append(f"  Margin change (QoQ):{analysis.gross_margin_change:+.1f}pp")

    lines.append(f"  First public report:{' Yes' if analysis.is_first_public_report else ' No'}")
    lines.append(f"  Growth trajectory:  {analysis.vs_s1_trajectory}")
    lines.append("")

    # Signal with visual indicator
    signal_map = {
        "strong_buy": "STRONG BUY  >>>",
        "buy": "BUY         >>",
        "neutral": "NEUTRAL     --",
        "caution": "CAUTION     !!",
    }
    sig_text = signal_map.get(analysis.signal, analysis.signal)
    lines.append(f"  Signal:  [{sig_text}]")
    lines.append("")
    lines.append(f"{'=' * 55}")

    return "\n".join(lines)

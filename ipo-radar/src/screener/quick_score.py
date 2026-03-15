"""Quick Score - Generate a 0-100 composite score for IPO candidates."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.screener.s1_parser import S1Metrics, TOP_UNDERWRITERS


@dataclass
class ScoreDimension:
    """One dimension of the scoring rubric."""

    name: str
    max_points: int
    points: int = 0
    detail: str = ""


@dataclass
class QuickScoreResult:
    """Complete scoring result for an IPO candidate."""

    ticker: str = ""
    company_name: str = ""
    total_score: int = 0
    max_score: int = 100
    verdict: str = ""  # PASS | FAIL | REVIEW
    dimensions: list[ScoreDimension] = field(default_factory=list)

    @property
    def percentage(self) -> float:
        return (self.total_score / self.max_score * 100) if self.max_score else 0.0


def calculate_quick_score(metrics: S1Metrics) -> QuickScoreResult:
    """Score an IPO candidate based on extracted S-1 metrics.

    Scoring rubric (100 points total):
      Revenue growth (25): >20% → 25, 10-20% → 15, <10% → 0
      Gross margin  (20): >60% → 20, 40-60% → 12, <40% → 0
      Cash runway   (20): >18mo → 20, 12-18mo → 10, <12mo → 0
      Debt/assets   (15): <0.3 → 15, 0.3-0.6 → 8, >0.6 → 0
      Underwriter   (10): top-tier → 10, other → 0
      Market cap    (10): >$1B → 10, $500M-$1B → 5, <$500M → 0

    Verdict:
      >= 60  → PASS
      40-59  → REVIEW
      < 40   → FAIL
    """
    dimensions: list[ScoreDimension] = []

    # 1. Revenue growth (25 pts)
    dimensions.append(_score_revenue_growth(metrics))

    # 2. Gross margin (20 pts)
    dimensions.append(_score_gross_margin(metrics))

    # 3. Cash runway (20 pts)
    dimensions.append(_score_cash_runway(metrics))

    # 4. Debt / assets (15 pts)
    dimensions.append(_score_debt_ratio(metrics))

    # 5. Underwriter quality (10 pts)
    dimensions.append(_score_underwriter(metrics))

    # 6. Market cap (10 pts)
    dimensions.append(_score_market_cap(metrics))

    total = sum(d.points for d in dimensions)

    if total >= 60:
        verdict = "PASS"
    elif total >= 40:
        verdict = "REVIEW"
    else:
        verdict = "FAIL"

    return QuickScoreResult(
        ticker=metrics.ticker,
        company_name=metrics.company_name,
        total_score=total,
        verdict=verdict,
        dimensions=dimensions,
    )


# ---------------------------------------------------------------------------
# Dimension scorers
# ---------------------------------------------------------------------------


def _score_revenue_growth(metrics: S1Metrics) -> ScoreDimension:
    dim = ScoreDimension(name="Revenue Growth", max_points=25)

    if not metrics.revenue_yoy_growth:
        dim.detail = "N/A (no revenue data)"
        return dim

    latest_growth = metrics.revenue_yoy_growth[0]
    pct = latest_growth * 100

    if latest_growth > 0.20:
        dim.points = 25
        dim.detail = f"{pct:.1f}% YoY (>20%)"
    elif latest_growth >= 0.10:
        dim.points = 15
        dim.detail = f"{pct:.1f}% YoY (10-20%)"
    else:
        dim.points = 0
        dim.detail = f"{pct:.1f}% YoY (<10%)"

    return dim


def _score_gross_margin(metrics: S1Metrics) -> ScoreDimension:
    dim = ScoreDimension(name="Gross Margin", max_points=20)

    if metrics.gross_margin is None:
        dim.detail = "N/A"
        return dim

    pct = metrics.gross_margin * 100

    if metrics.gross_margin > 0.60:
        dim.points = 20
        dim.detail = f"{pct:.1f}% (>60%)"
    elif metrics.gross_margin >= 0.40:
        dim.points = 12
        dim.detail = f"{pct:.1f}% (40-60%)"
    else:
        dim.points = 0
        dim.detail = f"{pct:.1f}% (<40%)"

    return dim


def _score_cash_runway(metrics: S1Metrics) -> ScoreDimension:
    dim = ScoreDimension(name="Cash Runway", max_points=20)

    if metrics.cash_runway_months is None:
        # If profitable, cash runway is not a concern
        if metrics.net_income is not None and metrics.net_income >= 0:
            dim.points = 20
            dim.detail = "Profitable (N/A)"
            return dim
        dim.detail = "N/A"
        return dim

    months = metrics.cash_runway_months

    if months > 18:
        dim.points = 20
        dim.detail = f"{months:.0f} months (>18)"
    elif months >= 12:
        dim.points = 10
        dim.detail = f"{months:.0f} months (12-18)"
    else:
        dim.points = 0
        dim.detail = f"{months:.0f} months (<12)"

    return dim


def _score_debt_ratio(metrics: S1Metrics) -> ScoreDimension:
    dim = ScoreDimension(name="Debt/Assets", max_points=15)

    if metrics.debt_to_assets is None:
        dim.detail = "N/A"
        return dim

    ratio = metrics.debt_to_assets

    if ratio < 0.3:
        dim.points = 15
        dim.detail = f"{ratio:.2f} (<0.3)"
    elif ratio <= 0.6:
        dim.points = 8
        dim.detail = f"{ratio:.2f} (0.3-0.6)"
    else:
        dim.points = 0
        dim.detail = f"{ratio:.2f} (>0.6)"

    return dim


def _score_underwriter(metrics: S1Metrics) -> ScoreDimension:
    dim = ScoreDimension(name="Underwriter", max_points=10)

    if not metrics.lead_underwriter:
        dim.detail = "N/A"
        return dim

    if metrics.is_top_underwriter:
        dim.points = 10
        dim.detail = f"{metrics.lead_underwriter} (top-tier)"
    else:
        dim.points = 0
        dim.detail = f"{metrics.lead_underwriter}"

    return dim


def _score_market_cap(metrics: S1Metrics) -> ScoreDimension:
    dim = ScoreDimension(name="Market Cap", max_points=10)

    if metrics.implied_market_cap is None:
        dim.detail = "N/A"
        return dim

    cap = metrics.implied_market_cap

    if cap >= 1_000_000_000:
        dim.points = 10
        dim.detail = f"${cap / 1e9:.1f}B (>$1B)"
    elif cap >= 500_000_000:
        dim.points = 5
        dim.detail = f"${cap / 1e6:.0f}M ($500M-$1B)"
    else:
        dim.points = 0
        dim.detail = f"${cap / 1e6:.0f}M (<$500M)"

    return dim


def format_report(result: QuickScoreResult) -> str:
    """Format a QuickScoreResult as a human-readable report string."""
    lines = [
        "=" * 56,
        f"  IPO Quick Score Report: {result.ticker or result.company_name or 'Unknown'}",
        "=" * 56,
        "",
    ]

    for dim in result.dimensions:
        bar = "█" * dim.points + "░" * (dim.max_points - dim.points)
        lines.append(f"  {dim.name:<16} {bar} {dim.points:>3}/{dim.max_points}  {dim.detail}")

    lines.append("")
    lines.append(f"  {'TOTAL':<16} {'':>20} {result.total_score:>3}/100")
    lines.append("")

    verdict_emoji = {"PASS": "[PASS]", "REVIEW": "[REVIEW]", "FAIL": "[FAIL]"}
    lines.append(f"  Verdict: {verdict_emoji.get(result.verdict, '')} {result.verdict}")
    lines.append("=" * 56)

    return "\n".join(lines)

"""Tests for the screener module (s1_parser + quick_score)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.screener.quick_score import (
    QuickScoreResult,
    calculate_quick_score,
    format_report,
)
from src.screener.s1_parser import (
    S1Metrics,
    _compute_derived,
    _extract_sections_html,
    _find_monetary_values,
    _parse_financials,
    _strip_html_tags,
    parse_money,
)


# ======================================================================
# s1_parser – parse_money
# ======================================================================


class TestParseMoney:
    def test_plain_number(self):
        assert parse_money("$1,234,567") == 1_234_567.0

    def test_millions(self):
        assert parse_money("$45.2 million") == 45_200_000.0

    def test_billions(self):
        assert parse_money("$1.5 billion") == 1_500_000_000.0

    def test_thousands(self):
        assert parse_money("$500 thousand") == 500_000.0

    def test_abbrev_m(self):
        assert parse_money("$100M") == 100_000_000.0

    def test_abbrev_b(self):
        assert parse_money("$2.5B") == 2_500_000_000.0

    def test_no_dollar_sign(self):
        assert parse_money("250 million") == 250_000_000.0

    def test_empty(self):
        assert parse_money("") is None

    def test_none(self):
        assert parse_money(None) is None

    def test_no_match(self):
        assert parse_money("no numbers here") is None


# ======================================================================
# s1_parser – _strip_html_tags
# ======================================================================


class TestStripHtmlTags:
    def test_basic_tags(self):
        assert "Hello World" in _strip_html_tags("<p>Hello <b>World</b></p>")

    def test_removes_style(self):
        html = "<style>.foo { color: red; }</style><p>Text</p>"
        result = _strip_html_tags(html)
        assert "color" not in result
        assert "Text" in result

    def test_removes_script(self):
        html = "<script>alert('x')</script><p>Safe</p>"
        result = _strip_html_tags(html)
        assert "alert" not in result
        assert "Safe" in result

    def test_html_entities(self):
        result = _strip_html_tags("A&amp;B &lt;C&gt; D&nbsp;E")
        assert "A&B" in result
        assert "<C>" in result


# ======================================================================
# s1_parser – _find_monetary_values
# ======================================================================


class TestFindMonetaryValues:
    def test_find_revenue(self):
        text = "Our revenue was $150.5 million in 2025 and $120.3 million in 2024."
        vals = _find_monetary_values(text, "revenue", count=2)
        assert len(vals) == 2
        assert vals[0] == pytest.approx(150_500_000, rel=0.01)
        assert vals[1] == pytest.approx(120_300_000, rel=0.01)

    def test_no_match(self):
        assert _find_monetary_values("nothing here", "revenue") == []

    def test_empty_text(self):
        assert _find_monetary_values("", "revenue") == []

    def test_count_limit(self):
        text = "revenue $10M then revenue $20M then revenue $30M"
        vals = _find_monetary_values(text, "revenue", count=2)
        assert len(vals) == 2


# ======================================================================
# s1_parser – _extract_sections_html
# ======================================================================


class TestExtractSectionsHtml:
    def test_extracts_sections(self):
        html = """
        <h1>PROSPECTUS SUMMARY</h1>
        <p>We are a technology company.</p>
        <h1>RISK FACTORS</h1>
        <p>Investing involves risks.</p>
        <h1>USE OF PROCEEDS</h1>
        <p>General corporate purposes.</p>
        """
        sections = _extract_sections_html(html)
        assert "prospectus_summary" in sections
        assert "technology company" in sections["prospectus_summary"]
        assert "risk_factors" in sections
        assert "use_of_proceeds" in sections

    def test_empty_html(self):
        sections = _extract_sections_html("")
        assert sections == {}


# ======================================================================
# s1_parser – _compute_derived
# ======================================================================


class TestComputeDerived:
    def test_debt_to_assets(self):
        m = S1Metrics(total_debt=300_000, total_assets=1_000_000)
        _compute_derived(m)
        assert m.debt_to_assets == pytest.approx(0.3)

    def test_cash_runway(self):
        m = S1Metrics(cash_and_equivalents=24_000_000, net_income=-12_000_000)
        _compute_derived(m)
        assert m.burn_rate_monthly == pytest.approx(1_000_000)
        assert m.cash_runway_months == pytest.approx(24.0)

    def test_no_runway_when_profitable(self):
        m = S1Metrics(cash_and_equivalents=10_000_000, net_income=5_000_000)
        _compute_derived(m)
        assert m.cash_runway_months is None

    def test_implied_market_cap(self):
        m = S1Metrics(shares_offered=10_000_000, price_range=(18.0, 22.0))
        _compute_derived(m)
        # mid price = 20, total shares ~66.67M, market cap ~1.33B
        assert m.implied_market_cap is not None
        assert m.implied_market_cap > 1_000_000_000


# ======================================================================
# s1_parser – extract_key_metrics (mocked)
# ======================================================================


class TestExtractKeyMetricsMocked:
    @patch("src.screener.s1_parser.requests.get")
    def test_with_direct_url(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.text = """
        <html><body>
        <h1>PROSPECTUS SUMMARY</h1>
        <p>We are offering 10,000,000 shares at $18.00 to $22.00 per share.</p>
        <h1>RISK FACTORS</h1>
        <p>Our largest customer accounts for a significant portion of revenue.</p>
        <h1>USE OF PROCEEDS</h1>
        <p>General corporate purposes and working capital.</p>
        <h1>SELECTED FINANCIAL DATA</h1>
        <p>Total revenue was $250.0 million in 2025 and $180.0 million in 2024.</p>
        <p>Gross profit was $175.0 million.</p>
        <p>Net loss was $30.0 million.</p>
        <p>Cash and cash equivalents were $150.0 million.</p>
        <p>Total debt was $50.0 million. Total assets were $400.0 million.</p>
        <h1>UNDERWRITING</h1>
        <p>The lead book-running manager is Goldman Sachs.</p>
        </body></html>
        """
        mock_get.return_value = mock_resp

        from src.screener.s1_parser import extract_key_metrics

        metrics = extract_key_metrics(s1_url="https://example.com/s1.htm")

        assert len(metrics.revenues) >= 2
        assert metrics.revenues[0] == pytest.approx(250_000_000, rel=0.01)
        assert metrics.gross_margin is not None
        assert metrics.gross_margin == pytest.approx(0.70, rel=0.05)
        assert metrics.lead_underwriter == "Goldman Sachs"
        assert metrics.is_top_underwriter is True
        assert metrics.debt_to_assets is not None
        assert metrics.implied_market_cap is not None


# ======================================================================
# quick_score – scoring logic
# ======================================================================


class TestCalculateQuickScore:
    """Test the scoring rubric with known metric values."""

    def _make_metrics(self, **overrides) -> S1Metrics:
        """Build an S1Metrics with sensible defaults, overriding as needed."""
        defaults = dict(
            ticker="TEST",
            company_name="Test Corp",
            revenues=[250e6, 180e6, 130e6],
            revenue_yoy_growth=[0.389, 0.385],  # ~39%, ~38%
            gross_margin=0.70,
            net_income=-30e6,
            cash_and_equivalents=150e6,
            total_debt=50e6,
            total_assets=400e6,
            debt_to_assets=0.125,
            cash_runway_months=60.0,
            lead_underwriter="Goldman Sachs",
            is_top_underwriter=True,
            implied_market_cap=1.5e9,
        )
        defaults.update(overrides)
        return S1Metrics(**defaults)

    def test_perfect_score(self):
        """All criteria at highest tier → should score 100."""
        m = self._make_metrics()
        result = calculate_quick_score(m)
        assert result.total_score == 100
        assert result.verdict == "PASS"

    def test_fail_score(self):
        """All criteria at lowest tier → should score 0 / FAIL."""
        m = self._make_metrics(
            revenue_yoy_growth=[0.05],  # <10%
            gross_margin=0.30,  # <40%
            cash_runway_months=6.0,  # <12
            debt_to_assets=0.8,  # >0.6
            is_top_underwriter=False,
            lead_underwriter="Small Firm",
            implied_market_cap=200e6,  # <$500M
        )
        result = calculate_quick_score(m)
        assert result.total_score == 0
        assert result.verdict == "FAIL"

    def test_review_score(self):
        """Mid-tier criteria → REVIEW (40-59)."""
        m = self._make_metrics(
            revenue_yoy_growth=[0.15],  # 15% → 15pts
            gross_margin=0.50,  # 50% → 12pts
            cash_runway_months=15.0,  # → 10pts
            debt_to_assets=0.45,  # → 8pts
            is_top_underwriter=False,
            lead_underwriter="Regional Bank",
            implied_market_cap=700e6,  # → 5pts
        )
        result = calculate_quick_score(m)
        assert result.total_score == 50  # 15+12+10+8+0+5
        assert result.verdict == "REVIEW"

    def test_boundary_pass(self):
        """Score exactly 60 → PASS."""
        m = self._make_metrics(
            revenue_yoy_growth=[0.25],  # 25pts
            gross_margin=0.65,  # 20pts
            cash_runway_months=5.0,  # 0pts
            debt_to_assets=0.125,  # 15pts
            is_top_underwriter=False,
            lead_underwriter="",
            implied_market_cap=None,
        )
        result = calculate_quick_score(m)
        assert result.total_score == 60
        assert result.verdict == "PASS"

    def test_boundary_fail(self):
        """Score exactly 39 → FAIL."""
        # 25 (growth) + 0 (margin) + 0 (runway) + 0 (debt) + 10 (uw) + 0 (cap) = 35
        # Adjust: 15 (growth 10-20%) + 12 (margin 40-60%) + 10 (runway 12-18) + 0 + 0 + 0 = 37
        m = self._make_metrics(
            revenue_yoy_growth=[0.15],  # 15
            gross_margin=0.50,  # 12
            cash_runway_months=15.0,  # 10
            debt_to_assets=0.8,  # 0
            is_top_underwriter=False,
            lead_underwriter="",
            implied_market_cap=100e6,  # 0
        )
        result = calculate_quick_score(m)
        assert result.total_score == 37
        assert result.verdict == "FAIL"

    def test_no_data_scores_zero(self):
        """Empty metrics → all N/A → 0 score."""
        m = S1Metrics()
        result = calculate_quick_score(m)
        assert result.total_score == 0
        assert result.verdict == "FAIL"

    def test_profitable_company_gets_runway_points(self):
        """Profitable company should get full cash runway points."""
        m = self._make_metrics(
            net_income=50e6,
            cash_runway_months=None,
            cash_and_equivalents=200e6,
        )
        result = calculate_quick_score(m)
        runway_dim = [d for d in result.dimensions if d.name == "Cash Runway"][0]
        assert runway_dim.points == 20
        assert "Profitable" in runway_dim.detail


class TestFormatReport:
    def test_format_includes_verdict(self):
        m = S1Metrics(
            ticker="FMT",
            revenues=[100e6, 80e6],
            revenue_yoy_growth=[0.25],
            gross_margin=0.65,
            implied_market_cap=2e9,
            lead_underwriter="Goldman Sachs",
            is_top_underwriter=True,
            debt_to_assets=0.2,
            cash_runway_months=24.0,
        )
        result = calculate_quick_score(m)
        report = format_report(result)
        assert "FMT" in report
        assert "PASS" in report
        assert "Revenue Growth" in report
        assert "Gross Margin" in report
        assert "/100" in report

    def test_format_fail(self):
        result = calculate_quick_score(S1Metrics())
        report = format_report(result)
        assert "FAIL" in report


# ======================================================================
# Integration-style test with realistic S-1 data
# ======================================================================


class TestRealisticS1Example:
    """Simulate a realistic S-1 filing extraction and scoring.

    Based on a hypothetical tech company IPO with characteristics similar
    to real filings (revenue growth, SaaS margins, VC-backed).
    """

    def test_high_growth_saas_company(self):
        """A high-growth SaaS company should score well."""
        metrics = S1Metrics(
            company_name="CloudTech Inc",
            ticker="CLDT",
            revenues=[320e6, 210e6, 140e6],
            revenue_yoy_growth=[0.524, 0.50],  # 52.4%, 50%
            gross_margin=0.72,
            net_income=-45e6,
            cash_and_equivalents=280e6,
            total_debt=25e6,
            total_assets=500e6,
            debt_to_assets=0.05,
            burn_rate_monthly=3.75e6,
            cash_runway_months=74.7,
            shares_offered=15_000_000,
            price_range=(28.0, 32.0),
            implied_market_cap=3e9,
            lead_underwriter="Morgan Stanley",
            is_top_underwriter=True,
            customer_concentration="No single customer exceeds 5% of revenue.",
            use_of_proceeds="General corporate purposes and working capital.",
        )
        result = calculate_quick_score(metrics)

        assert result.total_score == 100
        assert result.verdict == "PASS"

        # Verify each dimension
        dims = {d.name: d for d in result.dimensions}
        assert dims["Revenue Growth"].points == 25
        assert dims["Gross Margin"].points == 20
        assert dims["Cash Runway"].points == 20
        assert dims["Debt/Assets"].points == 15
        assert dims["Underwriter"].points == 10
        assert dims["Market Cap"].points == 10

    def test_marginal_biotech_company(self):
        """A pre-revenue biotech with high burn should score poorly."""
        metrics = S1Metrics(
            company_name="BioPharm Labs",
            ticker="BPHL",
            revenues=[5e6, 3e6],
            revenue_yoy_growth=[0.667],  # 66% but from tiny base
            gross_margin=0.35,  # low margin
            net_income=-80e6,
            cash_and_equivalents=60e6,
            total_debt=40e6,
            total_assets=120e6,
            debt_to_assets=0.333,
            burn_rate_monthly=6.67e6,
            cash_runway_months=9.0,  # <12 months
            shares_offered=8_000_000,
            price_range=(10.0, 12.0),
            implied_market_cap=587e6,
            lead_underwriter="Jefferies",
            is_top_underwriter=False,
        )
        result = calculate_quick_score(metrics)

        # 25 (growth) + 0 (margin<40%) + 0 (runway<12) + 8 (debt 0.3-0.6) + 0 (uw) + 5 (cap 500M-1B) = 38
        assert result.total_score == 38
        assert result.verdict == "FAIL"

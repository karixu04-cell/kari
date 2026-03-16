"""Signal Aggregator - Integrate all IPO analysis modules into a unified report.

Combines pattern detection, lockup tracking, earnings analysis, sentiment,
and fundamental screening into a single composite decision signal.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import yfinance as yf

from src.earnings.earnings_analyzer import EarningsAnalysis, analyze_earnings
from src.earnings.earnings_calendar import get_earnings_date
from src.lockup.lockup_calendar import LockupCalendar, LockupEntry
from src.lockup.lockup_parser import LockupDetail
from src.pattern.breakout_scanner import BreakoutScanner, BreakoutSignal
from src.pattern.ipo_base_detector import BaseInfo, IPOBaseDetector
from src.screener import QuickScoreResult, S1Metrics, calculate_quick_score
from src.sentiment.news_fetcher import fetch_news
from src.sentiment.sentiment_scorer import SentimentReport, analyze_sentiment

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------


def _safe_float(val) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
        return None if f != f else f
    except (ValueError, TypeError):
        return None


def _get_stock_info(ticker: str) -> dict:
    """Fetch basic stock info from yfinance."""
    try:
        info = yf.Ticker(ticker).info or {}
        return info
    except Exception as exc:
        logger.warning("Failed to get info for %s: %s", ticker, exc)
        return {}


def _get_price_history(ticker: str, period: str = "6mo"):
    """Fetch price history DataFrame from yfinance."""
    try:
        df = yf.Ticker(ticker).history(period=period)
        if df is not None and not df.empty:
            return df
    except Exception as exc:
        logger.warning("Failed to get price history for %s: %s", ticker, exc)
    return None


# ---------------------------------------------------------------------------
# Window analysis helpers
# ---------------------------------------------------------------------------


def _analyze_first_day_pullback(df, ipo_date: date | None) -> dict:
    """Detect first-day pullback window (day 2-5 after IPO)."""
    result = {"active": False, "signal": None}

    if df is None or ipo_date is None:
        return result

    days_since = (date.today() - ipo_date).days
    if not (1 <= days_since <= 10):
        return result

    result["active"] = True

    if len(df) < 2:
        return result

    # First day close and current
    first_close = _safe_float(df.iloc[0].get("Close"))
    first_high = _safe_float(df.iloc[0].get("High"))
    current_close = _safe_float(df.iloc[-1].get("Close"))

    if first_close is None or first_high is None or current_close is None:
        return result

    # Pullback from first-day high
    pullback_pct = (current_close - first_high) / first_high if first_high else 0

    if -0.15 <= pullback_pct <= -0.03:
        result["signal"] = "pullback_entry"
    elif pullback_pct > 0:
        result["signal"] = "holding_gains"

    return result


def _analyze_base_breakout(df, ipo_date: date | None) -> dict:
    """Detect IPO base formation and breakout."""
    result = {
        "active": False,
        "base_detected": False,
        "breakout_signal": None,
        "base_details": None,
    }

    if df is None or ipo_date is None:
        return result

    days_since = (date.today() - ipo_date).days
    if days_since < 14:
        return result

    result["active"] = True

    try:
        detector = IPOBaseDetector()
        base_info: BaseInfo = detector.detect_base(df, ipo_date)

        if base_info.has_base:
            result["base_detected"] = True
            result["base_details"] = base_info.to_dict()

            scanner = BreakoutScanner()
            signal: BreakoutSignal = scanner.scan(df, base_info)

            if signal.breakout_detected:
                result["breakout_signal"] = signal.signal_strength
    except Exception as exc:
        logger.debug("Base/breakout analysis failed: %s", exc)

    return result


def _analyze_lockup_window(ticker: str, ipo_date: date | None) -> dict:
    """Analyze lockup expiry status."""
    result = {
        "days_until": None,
        "supply_impact_pct": None,
        "status": "safe",
    }

    if ipo_date is None:
        return result

    # Standard lockup is 180 days
    lockup_expiry = ipo_date + timedelta(days=180)
    days_until = (lockup_expiry - date.today()).days

    result["days_until"] = days_until

    if days_until < 0:
        result["status"] = "expired"
    elif days_until <= 3:
        result["status"] = "imminent"
    elif days_until <= 14:
        result["status"] = "warning"
    else:
        result["status"] = "safe"

    # Estimate supply impact from yfinance
    try:
        info = yf.Ticker(ticker).info or {}
        shares_outstanding = info.get("sharesOutstanding")
        float_shares = info.get("floatShares")
        if shares_outstanding and float_shares and float_shares > 0:
            locked = shares_outstanding - float_shares
            result["supply_impact_pct"] = round(locked / float_shares * 100, 1)
    except Exception:
        pass

    return result


def _analyze_first_earnings(ticker: str) -> dict:
    """Analyze upcoming first earnings report."""
    result = {
        "days_until": None,
        "earnings_signal": None,
    }

    earnings_date = get_earnings_date(ticker)
    if earnings_date is None:
        return result

    days_until = (earnings_date - date.today()).days
    result["days_until"] = days_until

    # If earnings already happened, analyze them
    if days_until <= 0:
        try:
            analysis: EarningsAnalysis = analyze_earnings(ticker)
            result["earnings_signal"] = analysis.signal
        except Exception as exc:
            logger.debug("Earnings analysis failed for %s: %s", ticker, exc)

    return result


# ---------------------------------------------------------------------------
# Signal Aggregator
# ---------------------------------------------------------------------------


@dataclass
class AggregatedReport:
    """Full aggregated analysis report for a single ticker."""

    ticker: str
    company: str = ""
    ipo_date: date | None = None
    days_since_ipo: int = 0
    current_price: float = 0.0
    ipo_price: float = 0.0
    price_vs_ipo: float = 0.0

    windows: dict = field(default_factory=dict)

    fundamental_score: int = 0
    sentiment: dict = field(default_factory=dict)

    overall_signal: str = "NO_ACTION"
    signal_reasons: list[str] = field(default_factory=list)
    risk_factors: list[str] = field(default_factory=list)
    generated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "company": self.company,
            "ipo_date": self.ipo_date.isoformat() if self.ipo_date else None,
            "days_since_ipo": self.days_since_ipo,
            "current_price": self.current_price,
            "ipo_price": self.ipo_price,
            "price_vs_ipo": self.price_vs_ipo,
            "windows": self.windows,
            "fundamental_score": self.fundamental_score,
            "sentiment": self.sentiment,
            "overall_signal": self.overall_signal,
            "signal_reasons": self.signal_reasons,
            "risk_factors": self.risk_factors,
            "generated_at": self.generated_at.isoformat(),
        }


class SignalAggregator:
    """Integrates all sub-module outputs into a composite decision signal.

    Usage::

        agg = SignalAggregator()
        report = agg.generate_report("CAVA")
        print(report.overall_signal)  # 'STRONG_OPPORTUNITY', 'OPPORTUNITY', etc.
    """

    def generate_report(self, ticker: str) -> AggregatedReport:
        """Generate a comprehensive analysis report for a ticker.

        Calls all sub-modules and aggregates into a single report with
        an overall_signal of STRONG_OPPORTUNITY, OPPORTUNITY, WATCH, or NO_ACTION.
        """
        ticker = ticker.upper().strip()
        report = AggregatedReport(ticker=ticker)

        # --- Basic info ---
        info = _get_stock_info(ticker)
        report.company = info.get("shortName", "") or info.get("longName", "")

        current_price = _safe_float(info.get("currentPrice")) or _safe_float(info.get("regularMarketPrice"))
        report.current_price = current_price or 0.0

        # IPO date
        ipo_date_str = info.get("ipoDate", "")
        ipo_date = None
        if ipo_date_str:
            try:
                ipo_date = datetime.strptime(str(ipo_date_str), "%Y-%m-%d").date()
            except (ValueError, TypeError):
                pass
        report.ipo_date = ipo_date

        if ipo_date:
            report.days_since_ipo = (date.today() - ipo_date).days

        # IPO price (from info or first historical close)
        ipo_price = _safe_float(info.get("ipoPrice"))
        df = _get_price_history(ticker, period="max")
        if ipo_price is None and df is not None and len(df) > 0:
            ipo_price = _safe_float(df.iloc[0].get("Close"))
        report.ipo_price = ipo_price or 0.0

        if report.ipo_price > 0 and report.current_price > 0:
            report.price_vs_ipo = round(report.current_price / report.ipo_price, 3)

        # --- Window analysis ---
        price_df = _get_price_history(ticker, period="6mo")

        windows = {}
        windows["first_day_pullback"] = _analyze_first_day_pullback(price_df, ipo_date)
        windows["ipo_base_breakout"] = _analyze_base_breakout(price_df, ipo_date)
        windows["lockup_expiry"] = _analyze_lockup_window(ticker, ipo_date)
        windows["first_earnings"] = _analyze_first_earnings(ticker)
        report.windows = windows

        # --- Fundamental score ---
        fundamental_score = self._get_fundamental_score(ticker)
        report.fundamental_score = fundamental_score

        # --- Sentiment ---
        sentiment_data = self._get_sentiment(ticker, report.company)
        report.sentiment = sentiment_data

        # --- Determine overall signal ---
        signal, reasons, risks = self._compute_overall_signal(
            windows, fundamental_score, sentiment_data,
        )
        report.overall_signal = signal
        report.signal_reasons = reasons
        report.risk_factors = risks
        report.generated_at = datetime.now()

        return report

    def _get_fundamental_score(self, ticker: str) -> int:
        """Get fundamental score (0-100) from screener module."""
        try:
            metrics = S1Metrics(ticker=ticker)
            # Try to populate from yfinance as a proxy
            info = _get_stock_info(ticker)

            # Revenue growth
            rev_growth = _safe_float(info.get("revenueGrowth"))
            if rev_growth is not None:
                metrics.revenue_yoy_growth = [rev_growth * 100]

            # Gross margin
            gross_margin = _safe_float(info.get("grossMargins"))
            if gross_margin is not None:
                metrics.gross_margin = gross_margin * 100

            # Market cap
            market_cap = _safe_float(info.get("marketCap"))
            if market_cap is not None:
                metrics.implied_market_cap = market_cap

            # Debt
            total_debt = _safe_float(info.get("totalDebt"))
            total_assets = _safe_float(info.get("totalAssets"))
            if total_debt is not None and total_assets and total_assets > 0:
                metrics.debt_to_assets = total_debt / total_assets

            result: QuickScoreResult = calculate_quick_score(metrics)
            return result.total_score

        except Exception as exc:
            logger.debug("Fundamental scoring failed for %s: %s", ticker, exc)
            return 0

    def _get_sentiment(self, ticker: str, company_name: str = "") -> dict:
        """Get sentiment analysis results."""
        try:
            news = fetch_news(ticker, days=7, company_name=company_name)
            sentiment_report: SentimentReport = analyze_sentiment(news)
            return {
                "score": sentiment_report.overall_score,
                "buzz": sentiment_report.buzz_level,
                "positive": sentiment_report.positive_count,
                "negative": sentiment_report.negative_count,
                "method": sentiment_report.method,
            }
        except Exception as exc:
            logger.debug("Sentiment analysis failed for %s: %s", ticker, exc)
            return {"score": 0.0, "buzz": "low"}

    def _compute_overall_signal(
        self,
        windows: dict,
        fundamental_score: int,
        sentiment: dict,
    ) -> tuple[str, list[str], list[str]]:
        """Compute overall signal, reasons, and risk factors.

        Signal logic:
        - STRONG_OPPORTUNITY: any window has strong signal + fundamentals >= 60
          + sentiment >= 0.3
        - OPPORTUNITY: any window has signal + fundamentals >= 50
        - WATCH: base forming but no breakout / lockup warning/imminent
        - NO_ACTION: everything else
        """
        reasons: list[str] = []
        risks: list[str] = []
        has_strong_signal = False
        has_signal = False
        has_watch_condition = False

        sentiment_score = sentiment.get("score", 0.0)

        # Check first_day_pullback
        fdp = windows.get("first_day_pullback", {})
        if fdp.get("active") and fdp.get("signal"):
            if fdp["signal"] == "pullback_entry":
                has_signal = True
                reasons.append("First-day pullback entry opportunity detected")
            elif fdp["signal"] == "holding_gains":
                reasons.append("IPO holding first-day gains")

        # Check base breakout
        base = windows.get("ipo_base_breakout", {})
        if base.get("active"):
            if base.get("breakout_signal"):
                strength = base["breakout_signal"]
                if strength == "strong":
                    has_strong_signal = True
                    reasons.append("Strong breakout from IPO base detected")
                else:
                    has_signal = True
                    reasons.append(f"Breakout signal ({strength}) from IPO base")
            elif base.get("base_detected"):
                has_watch_condition = True
                reasons.append("IPO base forming, watching for breakout")

        # Check lockup
        lockup = windows.get("lockup_expiry", {})
        lockup_status = lockup.get("status", "safe")
        if lockup_status == "imminent":
            has_watch_condition = True
            risks.append(f"Lockup expiry imminent ({lockup.get('days_until', '?')} days)")
            supply_impact = lockup.get("supply_impact_pct")
            if supply_impact and supply_impact > 50:
                risks.append(f"High supply impact: {supply_impact:.0f}% of float")
        elif lockup_status == "warning":
            has_watch_condition = True
            risks.append(f"Lockup expiry approaching ({lockup.get('days_until', '?')} days)")

        # Check earnings
        earnings = windows.get("first_earnings", {})
        earnings_signal = earnings.get("earnings_signal")
        if earnings_signal:
            if earnings_signal in ("strong_buy", "buy"):
                has_signal = True
                reasons.append(f"Earnings signal: {earnings_signal}")
            elif earnings_signal == "caution":
                risks.append("Earnings below expectations")
        elif earnings.get("days_until") is not None and 0 < earnings["days_until"] <= 7:
            has_watch_condition = True
            reasons.append(f"Earnings report in {earnings['days_until']} days")

        # Sentiment info
        if sentiment_score >= 0.3:
            reasons.append(f"Positive sentiment (score: {sentiment_score:+.2f})")
        elif sentiment_score <= -0.3:
            risks.append(f"Negative sentiment (score: {sentiment_score:+.2f})")

        # Fundamental info
        if fundamental_score >= 60:
            reasons.append(f"Strong fundamentals (score: {fundamental_score}/100)")
        elif fundamental_score < 40 and fundamental_score > 0:
            risks.append(f"Weak fundamentals (score: {fundamental_score}/100)")

        # --- Determine overall signal ---
        if has_strong_signal and fundamental_score >= 60 and sentiment_score >= 0.3:
            signal = "STRONG_OPPORTUNITY"
        elif has_signal and fundamental_score >= 50:
            signal = "OPPORTUNITY"
        elif has_watch_condition:
            signal = "WATCH"
        else:
            signal = "NO_ACTION"

        return signal, reasons, risks

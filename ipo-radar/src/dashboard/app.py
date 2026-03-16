"""IPO Radar Dashboard - Streamlit-based interactive dashboard.

Launch: streamlit run src/dashboard/app.py
"""

from __future__ import annotations

import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ---------------------------------------------------------------------------
# Ensure project root is importable
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.earnings.earnings_calendar import get_earnings_date, get_upcoming_earnings
from src.lockup.lockup_calendar import LockupCalendar, LockupEntry
from src.scorer.daily_scan import run_daily_scan
from src.scorer.signal_aggregator import AggregatedReport, SignalAggregator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Color scheme
# ---------------------------------------------------------------------------

COLORS = {
    "bg": "#0f1117",
    "STRONG_OPPORTUNITY": "#00ff88",
    "OPPORTUNITY": "#3b82f6",
    "WATCH": "#f59e0b",
    "NO_ACTION": "#64748b",
    "text": "#e2e8f0",
    "card_bg": "#1e293b",
    "border": "#334155",
    "positive": "#00ff88",
    "negative": "#ef4444",
    "neutral": "#94a3b8",
}


# ---------------------------------------------------------------------------
# Session state initialization
# ---------------------------------------------------------------------------


def _init_state() -> None:
    """Initialize session state with defaults."""
    if "watchlist" not in st.session_state:
        st.session_state.watchlist = ["CAVA", "ARM", "BIRK", "CART", "KPLT"]
    if "scan_results" not in st.session_state:
        st.session_state.scan_results = []
    if "last_scan" not in st.session_state:
        st.session_state.last_scan = None
    if "selected_ticker" not in st.session_state:
        st.session_state.selected_ticker = None
    if "lockup_calendar" not in st.session_state:
        st.session_state.lockup_calendar = LockupCalendar()


# ---------------------------------------------------------------------------
# Custom CSS for dark theme
# ---------------------------------------------------------------------------

_CUSTOM_CSS = """
<style>
    .signal-strong { color: #00ff88; font-weight: bold; }
    .signal-opportunity { color: #3b82f6; font-weight: bold; }
    .signal-watch { color: #f59e0b; font-weight: bold; }
    .signal-noaction { color: #64748b; }

    .metric-card {
        background: #1e293b;
        border: 1px solid #334155;
        border-radius: 8px;
        padding: 16px;
        text-align: center;
    }
    .metric-card h3 { margin: 0; font-size: 14px; color: #94a3b8; }
    .metric-card .value { font-size: 36px; font-weight: bold; margin: 8px 0; }

    .window-card {
        background: #1e293b;
        border: 1px solid #334155;
        border-radius: 8px;
        padding: 12px;
        margin: 4px 0;
    }
    .window-active { border-left: 3px solid #00ff88; }
    .window-inactive { border-left: 3px solid #64748b; }
</style>
"""


def _signal_color(signal: str) -> str:
    return COLORS.get(signal, COLORS["NO_ACTION"])


def _signal_badge(signal: str) -> str:
    color = _signal_color(signal)
    return f'<span style="color:{color}; font-weight:bold;">{signal}</span>'


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------


def _render_sidebar() -> str:
    """Render sidebar with watchlist management and controls. Returns active page."""
    with st.sidebar:
        st.markdown("## IPO Radar")
        st.markdown("---")

        # Navigation
        page = st.radio(
            "Navigate",
            ["Signal Overview", "Stock Detail", "IPO Calendar"],
            label_visibility="collapsed",
        )

        st.markdown("---")

        # Watchlist management
        st.markdown("### Watchlist")

        # Display current watchlist
        for i, ticker in enumerate(st.session_state.watchlist):
            col1, col2 = st.columns([3, 1])
            with col1:
                st.text(ticker)
            with col2:
                if st.button("x", key=f"rm_{i}_{ticker}"):
                    st.session_state.watchlist.remove(ticker)
                    st.rerun()

        # Add ticker
        col_add, col_btn = st.columns([3, 1])
        with col_add:
            new_ticker = st.text_input(
                "Add ticker",
                placeholder="e.g. CAVA",
                label_visibility="collapsed",
            )
        with col_btn:
            if st.button("+") and new_ticker:
                t = new_ticker.upper().strip()
                if t and t not in st.session_state.watchlist:
                    st.session_state.watchlist.append(t)
                    st.rerun()

        st.markdown("---")

        # Scan button
        if st.button("Run Scan", type="primary", use_container_width=True):
            _run_scan()

        # Last scan time
        if st.session_state.last_scan:
            st.caption(f"Last scan: {st.session_state.last_scan.strftime('%H:%M:%S')}")
        else:
            st.caption("No scan yet — click 'Run Scan'")

    return page


def _run_scan() -> None:
    """Execute the daily scan on the watchlist."""
    with st.spinner("Scanning..."):
        results = run_daily_scan(st.session_state.watchlist)
        st.session_state.scan_results = results
        st.session_state.last_scan = datetime.now()


# ---------------------------------------------------------------------------
# Page 1: Signal Overview
# ---------------------------------------------------------------------------


def _render_overview() -> None:
    """Render the main signal overview page."""
    st.markdown("# Signal Overview")

    reports: list[AggregatedReport] = st.session_state.scan_results

    if not reports:
        st.info("No scan results yet. Click **Run Scan** in the sidebar to start.")
        return

    # --- Top metric cards ---
    strong_count = sum(1 for r in reports if r.overall_signal == "STRONG_OPPORTUNITY")
    opp_count = sum(1 for r in reports if r.overall_signal == "OPPORTUNITY")
    lockup_soon = sum(
        1 for r in reports
        if r.windows.get("lockup_expiry", {}).get("status") in ("warning", "imminent")
    )
    watch_count = sum(1 for r in reports if r.overall_signal == "WATCH")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Strong Opportunities", strong_count)
    with c2:
        st.metric("Opportunities", opp_count)
    with c3:
        st.metric("Watch", watch_count)
    with c4:
        st.metric("Lockup Alerts", lockup_soon)

    st.markdown("---")

    # --- Signal table ---
    st.markdown("### Signal Table")

    rows = []
    for r in reports:
        active_windows = _get_active_windows(r)
        sentiment_score = r.sentiment.get("score", 0.0) if r.sentiment else 0.0

        rows.append({
            "Ticker": r.ticker,
            "Company": r.company or "N/A",
            "Days Since IPO": r.days_since_ipo,
            "Price": f"${r.current_price:.2f}" if r.current_price else "N/A",
            "vs IPO": f"{r.price_vs_ipo:.2f}x" if r.price_vs_ipo else "N/A",
            "Active Windows": active_windows,
            "Signal": r.overall_signal,
            "Fundamentals": r.fundamental_score,
            "Sentiment": f"{sentiment_score:+.2f}",
        })

    if rows:
        df = pd.DataFrame(rows)
        # Style the dataframe
        st.dataframe(
            df,
            use_container_width=True,
            column_config={
                "Ticker": st.column_config.TextColumn("Ticker", width="small"),
                "Signal": st.column_config.TextColumn("Signal", width="medium"),
                "Fundamentals": st.column_config.ProgressColumn(
                    "Fundamentals", min_value=0, max_value=100, format="%d",
                ),
            },
            hide_index=True,
        )

    # --- Expandable detail rows ---
    st.markdown("### Details")
    for r in reports:
        color = _signal_color(r.overall_signal)
        with st.expander(f":{color[1:]}[{r.overall_signal}] **{r.ticker}** — {r.company or 'N/A'}"):
            _render_report_detail(r)


def _get_active_windows(report: AggregatedReport) -> str:
    """Get a short string of active window names."""
    windows = report.windows
    active = []

    fdp = windows.get("first_day_pullback", {})
    if fdp.get("active") and fdp.get("signal"):
        active.append("FDP")

    base = windows.get("ipo_base_breakout", {})
    if base.get("active"):
        if base.get("breakout_signal"):
            active.append("Breakout")
        elif base.get("base_detected"):
            active.append("Base")

    lockup = windows.get("lockup_expiry", {})
    if lockup.get("status") in ("imminent", "warning"):
        active.append("Lockup")

    earnings = windows.get("first_earnings", {})
    if earnings.get("days_until") is not None:
        if earnings["days_until"] <= 7 and earnings["days_until"] >= 0:
            active.append("Earnings")

    return ", ".join(active) if active else "—"


def _render_report_detail(r: AggregatedReport) -> None:
    """Render expanded detail for a single report."""
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Price", f"${r.current_price:.2f}" if r.current_price else "N/A")
        if r.ipo_price:
            st.caption(f"IPO: ${r.ipo_price:.2f} | vs IPO: {r.price_vs_ipo:.2f}x")
    with col2:
        st.metric("Fundamentals", f"{r.fundamental_score}/100")
    with col3:
        sent = r.sentiment.get("score", 0.0) if r.sentiment else 0.0
        buzz = r.sentiment.get("buzz", "N/A") if r.sentiment else "N/A"
        st.metric("Sentiment", f"{sent:+.2f}")
        st.caption(f"Buzz: {buzz}")

    if r.signal_reasons:
        st.markdown("**Reasons:**")
        for reason in r.signal_reasons:
            st.markdown(f"- :green[+] {reason}")

    if r.risk_factors:
        st.markdown("**Risks:**")
        for risk in r.risk_factors:
            st.markdown(f"- :red[!] {risk}")

    # Link to detail page
    if st.button(f"View Full Detail: {r.ticker}", key=f"detail_{r.ticker}"):
        st.session_state.selected_ticker = r.ticker
        st.rerun()


# ---------------------------------------------------------------------------
# Page 2: Stock Detail
# ---------------------------------------------------------------------------


def _render_stock_detail() -> None:
    """Render the individual stock detail page."""
    st.markdown("# Stock Detail")

    # Ticker selector
    ticker = st.selectbox(
        "Select Ticker",
        options=st.session_state.watchlist,
        index=(
            st.session_state.watchlist.index(st.session_state.selected_ticker)
            if st.session_state.selected_ticker in st.session_state.watchlist
            else 0
        ) if st.session_state.watchlist else 0,
    )

    if not ticker:
        st.warning("Add tickers to your watchlist first.")
        return

    st.session_state.selected_ticker = ticker

    # Find existing report or generate
    report = None
    for r in st.session_state.scan_results:
        if r.ticker == ticker:
            report = r
            break

    if report is None:
        with st.spinner(f"Generating report for {ticker}..."):
            agg = SignalAggregator()
            report = agg.generate_report(ticker)

    # --- Signal banner ---
    color = _signal_color(report.overall_signal)
    st.markdown(
        f'<div style="background:{color}22; border:1px solid {color}; '
        f'border-radius:8px; padding:12px; text-align:center;">'
        f'<span style="color:{color}; font-size:24px; font-weight:bold;">'
        f'{report.overall_signal}</span></div>',
        unsafe_allow_html=True,
    )
    st.markdown("")

    # --- Candlestick chart ---
    _render_candlestick(ticker, report)

    st.markdown("---")

    # --- Four window cards ---
    st.markdown("### Window Analysis")
    _render_window_cards(report)

    st.markdown("---")

    # --- Fundamental radar chart ---
    col_radar, col_info = st.columns([1, 1])

    with col_radar:
        st.markdown("### Fundamentals")
        _render_radar_chart(report)

    with col_info:
        st.markdown("### Key Info")
        info_data = {
            "Company": report.company or "N/A",
            "IPO Date": str(report.ipo_date) if report.ipo_date else "N/A",
            "Days Since IPO": report.days_since_ipo,
            "Current Price": f"${report.current_price:.2f}" if report.current_price else "N/A",
            "IPO Price": f"${report.ipo_price:.2f}" if report.ipo_price else "N/A",
            "Price vs IPO": f"{report.price_vs_ipo:.2f}x" if report.price_vs_ipo else "N/A",
            "Fundamental Score": f"{report.fundamental_score}/100",
        }
        for k, v in info_data.items():
            st.markdown(f"**{k}:** {v}")

    st.markdown("---")

    # --- Sentiment & News ---
    st.markdown("### Sentiment & News")
    _render_sentiment_section(report)

    # --- Lockup countdown ---
    lockup = report.windows.get("lockup_expiry", {})
    if lockup.get("days_until") is not None:
        st.markdown("---")
        st.markdown("### Lockup Countdown")
        days = lockup["days_until"]
        status = lockup.get("status", "safe")
        supply = lockup.get("supply_impact_pct")

        col_l1, col_l2, col_l3 = st.columns(3)
        with col_l1:
            if days > 0:
                st.metric("Days Until Lockup Expiry", days)
            else:
                st.metric("Days Since Lockup Expiry", abs(days))
        with col_l2:
            status_color = {
                "safe": "green", "warning": "orange",
                "imminent": "red", "expired": "gray",
            }.get(status, "gray")
            st.markdown(f"**Status:** :{status_color}[{status.upper()}]")
        with col_l3:
            if supply:
                st.metric("Supply Impact", f"{supply:.0f}%")


def _render_candlestick(ticker: str, report: AggregatedReport) -> None:
    """Render an interactive candlestick chart with annotations."""
    try:
        import yfinance as yf
        df = yf.Ticker(ticker).history(period="6mo")
        if df is None or df.empty:
            st.warning("No price data available for chart.")
            return
    except Exception:
        st.warning("Could not load price data for chart.")
        return

    fig = go.Figure()

    # Candlestick
    fig.add_trace(go.Candlestick(
        x=df.index,
        open=df["Open"],
        high=df["High"],
        low=df["Low"],
        close=df["Close"],
        name=ticker,
        increasing_line_color="#00ff88",
        decreasing_line_color="#ef4444",
    ))

    # IPO price line
    if report.ipo_price and report.ipo_price > 0:
        fig.add_hline(
            y=report.ipo_price,
            line_dash="dash",
            line_color="#f59e0b",
            annotation_text=f"IPO ${report.ipo_price:.2f}",
            annotation_position="top left",
        )

    # Base region annotation
    base_info = report.windows.get("ipo_base_breakout", {})
    base_details = base_info.get("base_details")
    if base_details:
        base_start = base_details.get("base_start")
        base_end = base_details.get("base_end")
        if base_start and base_end:
            fig.add_vrect(
                x0=base_start, x1=base_end,
                fillcolor="#3b82f6", opacity=0.1,
                line_width=0,
                annotation_text="Base",
                annotation_position="top left",
            )

    # Lockup expiry date
    lockup = report.windows.get("lockup_expiry", {})
    if report.ipo_date and lockup.get("days_until") is not None:
        lockup_date = report.ipo_date + timedelta(days=180)
        if df.index[0].date() <= lockup_date <= df.index[-1].date() + timedelta(days=30):
            fig.add_vline(
                x=datetime.combine(lockup_date, datetime.min.time()),
                line_dash="dot",
                line_color="#ef4444",
                annotation_text="Lockup Expiry",
                annotation_position="top right",
            )

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#0f1117",
        plot_bgcolor="#0f1117",
        xaxis_rangeslider_visible=False,
        height=450,
        margin=dict(l=50, r=20, t=30, b=30),
        xaxis=dict(gridcolor="#1e293b"),
        yaxis=dict(gridcolor="#1e293b", title="Price ($)"),
    )

    st.plotly_chart(fig, use_container_width=True)


def _render_window_cards(report: AggregatedReport) -> None:
    """Render the four analysis window status cards."""
    windows = report.windows
    cols = st.columns(4)

    # 1. First Day Pullback
    with cols[0]:
        fdp = windows.get("first_day_pullback", {})
        active = fdp.get("active", False)
        signal = fdp.get("signal")
        icon = "🟢" if signal else ("🔵" if active else "⚪")
        st.markdown(f"**{icon} First Day Pullback**")
        st.caption(f"Active: {'Yes' if active else 'No'}")
        if signal:
            st.markdown(f"Signal: **{signal}**")

    # 2. IPO Base Breakout
    with cols[1]:
        base = windows.get("ipo_base_breakout", {})
        active = base.get("active", False)
        base_det = base.get("base_detected", False)
        breakout = base.get("breakout_signal")
        icon = "🟢" if breakout else ("🔵" if base_det else ("⚪" if not active else "⚫"))
        st.markdown(f"**{icon} Base Breakout**")
        st.caption(f"Active: {'Yes' if active else 'No'}")
        if base_det:
            st.markdown(f"Base: **Detected**")
        if breakout:
            st.markdown(f"Breakout: **{breakout}**")

    # 3. Lockup Expiry
    with cols[2]:
        lockup = windows.get("lockup_expiry", {})
        status = lockup.get("status", "safe")
        days_until = lockup.get("days_until")
        icon_map = {"imminent": "🔴", "warning": "🟡", "safe": "🟢", "expired": "⚪"}
        icon = icon_map.get(status, "⚪")
        st.markdown(f"**{icon} Lockup Expiry**")
        if days_until is not None:
            if days_until > 0:
                st.caption(f"{days_until} days remaining")
            else:
                st.caption(f"Expired {abs(days_until)} days ago")
        st.markdown(f"Status: **{status.upper()}**")

    # 4. First Earnings
    with cols[3]:
        earn = windows.get("first_earnings", {})
        days_until = earn.get("days_until")
        earn_signal = earn.get("earnings_signal")
        icon = "🟢" if earn_signal in ("buy", "strong_buy") else ("🔴" if earn_signal == "caution" else "⚪")
        st.markdown(f"**{icon} First Earnings**")
        if days_until is not None:
            if days_until > 0:
                st.caption(f"In {days_until} days")
            else:
                st.caption(f"Reported {abs(days_until)} days ago")
        if earn_signal:
            st.markdown(f"Signal: **{earn_signal}**")


def _render_radar_chart(report: AggregatedReport) -> None:
    """Render a fundamental score radar chart."""
    # Build dimensions from available data
    categories = [
        "Fundamentals",
        "Sentiment",
        "Price Strength",
        "Earnings",
        "Lockup Safety",
    ]

    fund_score = min(report.fundamental_score, 100)
    sent_raw = report.sentiment.get("score", 0.0) if report.sentiment else 0.0
    sent_score = (sent_raw + 1) / 2 * 100  # -1..1 → 0..100

    price_score = min(report.price_vs_ipo * 20, 100) if report.price_vs_ipo else 0

    earn = report.windows.get("first_earnings", {})
    earn_signal = earn.get("earnings_signal", "")
    earn_score = {"strong_buy": 100, "buy": 75, "neutral": 50, "caution": 20}.get(earn_signal, 50)

    lockup = report.windows.get("lockup_expiry", {})
    lockup_status = lockup.get("status", "safe")
    lockup_score = {"safe": 100, "warning": 50, "imminent": 20, "expired": 80}.get(lockup_status, 50)

    values = [fund_score, sent_score, price_score, earn_score, lockup_score]

    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=values + [values[0]],  # Close the polygon
        theta=categories + [categories[0]],
        fill="toself",
        fillcolor="rgba(59, 130, 246, 0.2)",
        line=dict(color="#3b82f6", width=2),
        name=report.ticker,
    ))

    fig.update_layout(
        polar=dict(
            bgcolor="#0f1117",
            radialaxis=dict(
                visible=True, range=[0, 100],
                gridcolor="#334155", linecolor="#334155",
            ),
            angularaxis=dict(gridcolor="#334155", linecolor="#334155"),
        ),
        template="plotly_dark",
        paper_bgcolor="#0f1117",
        height=350,
        margin=dict(l=60, r=60, t=30, b=30),
        showlegend=False,
    )

    st.plotly_chart(fig, use_container_width=True)


def _render_sentiment_section(report: AggregatedReport) -> None:
    """Render sentiment info and recent news headlines."""
    sent = report.sentiment or {}
    score = sent.get("score", 0.0)
    buzz = sent.get("buzz", "N/A")
    pos = sent.get("positive", 0)
    neg = sent.get("negative", 0)
    method = sent.get("method", "N/A")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        color = "green" if score > 0.1 else ("red" if score < -0.1 else "gray")
        label = "Bullish" if score > 0.1 else ("Bearish" if score < -0.1 else "Neutral")
        st.metric("Sentiment", f"{score:+.2f}")
        st.caption(label)
    with col2:
        st.metric("Buzz Level", buzz.upper())
    with col3:
        st.metric("Positive", pos)
    with col4:
        st.metric("Negative", neg)

    st.caption(f"Analysis method: {method}")

    # Try to show recent headlines
    try:
        from src.sentiment.news_fetcher import fetch_news
        with st.expander("Recent News Headlines"):
            news = fetch_news(report.ticker, days=7, company_name=report.company)
            if news:
                for item in news[:8]:
                    date_str = item.date.strftime("%m/%d") if item.date else ""
                    st.markdown(
                        f"**[{date_str}]** {item.title}  \n"
                        f"<small style='color:#64748b'>{item.source}</small>",
                        unsafe_allow_html=True,
                    )
            else:
                st.caption("No recent news found.")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Page 3: IPO Calendar
# ---------------------------------------------------------------------------


def _render_calendar() -> None:
    """Render the IPO calendar page with upcoming events."""
    st.markdown("# IPO Calendar")

    tab1, tab2, tab3 = st.tabs([
        "Upcoming IPOs",
        "Lockup Expirations",
        "First Earnings Reports",
    ])

    # --- Upcoming IPOs ---
    with tab1:
        st.markdown("### Upcoming IPOs")
        try:
            from src.radar import fetch_upcoming_ipos
            with st.spinner("Fetching upcoming IPOs..."):
                events = fetch_upcoming_ipos()
            if events:
                rows = []
                for ev in events[:20]:
                    rows.append({
                        "Ticker": ev.ticker,
                        "Company": ev.company_name,
                        "Expected Date": str(ev.expected_date) if ev.expected_date else "TBD",
                        "Price Range": (
                            f"${ev.price_range[0]:.0f}-${ev.price_range[1]:.0f}"
                            if ev.price_range else "N/A"
                        ),
                        "Underwriter": ev.lead_underwriter or "N/A",
                        "Status": ev.status,
                    })
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            else:
                st.info("No upcoming IPOs found. Data may be limited by API access.")
        except Exception as exc:
            st.warning(f"Could not fetch upcoming IPOs: {exc}")

    # --- Lockup Expirations ---
    with tab2:
        st.markdown("### Upcoming Lockup Expirations")
        _render_lockup_calendar()

    # --- First Earnings ---
    with tab3:
        st.markdown("### Upcoming First Earnings Reports")
        _render_earnings_calendar()


def _render_lockup_calendar() -> None:
    """Render lockup expiry calendar from watchlist."""
    reports = st.session_state.scan_results

    if not reports:
        st.info("Run a scan first to see lockup data.")
        return

    rows = []
    for r in reports:
        lockup = r.windows.get("lockup_expiry", {})
        days = lockup.get("days_until")
        status = lockup.get("status", "unknown")
        supply = lockup.get("supply_impact_pct")

        if days is None:
            continue

        expiry_date = ""
        if r.ipo_date:
            expiry_date = str(r.ipo_date + timedelta(days=180))

        rows.append({
            "Ticker": r.ticker,
            "Company": r.company or "N/A",
            "Lockup Expiry": expiry_date,
            "Days Remaining": days,
            "Status": status.upper(),
            "Supply Impact": f"{supply:.0f}%" if supply else "N/A",
        })

    if rows:
        rows.sort(key=lambda x: x["Days Remaining"])
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("No lockup data available for watchlist tickers.")


def _render_earnings_calendar() -> None:
    """Render upcoming earnings dates for watchlist."""
    with st.spinner("Checking earnings dates..."):
        upcoming = get_upcoming_earnings(st.session_state.watchlist, days=60)

    if upcoming:
        rows = []
        for ue in upcoming:
            rows.append({
                "Ticker": ue.ticker,
                "Company": ue.company_name or "N/A",
                "Earnings Date": str(ue.earnings_date),
                "Days Until": ue.days_until,
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("No upcoming earnings found for watchlist tickers within 60 days.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    """Entry point for the Streamlit dashboard."""
    st.set_page_config(
        page_title="IPO Radar",
        page_icon="📡",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.markdown(_CUSTOM_CSS, unsafe_allow_html=True)

    _init_state()
    page = _render_sidebar()

    if page == "Signal Overview":
        _render_overview()
    elif page == "Stock Detail":
        _render_stock_detail()
    elif page == "IPO Calendar":
        _render_calendar()


if __name__ == "__main__":
    main()

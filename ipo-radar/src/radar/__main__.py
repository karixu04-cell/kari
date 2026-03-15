"""CLI entry point: python -m src.radar

Prints upcoming IPOs for the next 14 days.
"""

from __future__ import annotations

import sys
from datetime import date

from src.radar.ipo_calendar import fetch_nasdaq_calendar, fetch_upcoming_ipos
from src.radar.tracker import IPOTracker


def main() -> None:
    print("=" * 64)
    print("  IPO Radar - 未来14天新股日历")
    print("=" * 64)

    # 1. Fetch from sources
    print("\n[1/3] 从 SEC EDGAR 获取最新 S-1/424B4 申报...")
    sec_events = fetch_upcoming_ipos()
    print(f"      找到 {len(sec_events)} 条 SEC 申报记录")

    print("[2/3] 从 Nasdaq IPO 日历获取数据...")
    nasdaq_events = fetch_nasdaq_calendar()
    print(f"      找到 {len(nasdaq_events)} 条 Nasdaq 日历记录")

    # 2. Import into tracker
    tracker = IPOTracker()
    all_events = sec_events + nasdaq_events
    imported = tracker.import_events(all_events)
    print(f"[3/3] 已导入 {imported} 条新记录到数据库\n")

    # 3. Display upcoming
    upcoming = tracker.get_upcoming(days=14)
    if not upcoming:
        print("未来14天暂无已排期的 IPO。")
        print("提示: 数据库中可能已有记录但日期不在14天范围内。")
        watchlist = tracker.get_watchlist()
        if watchlist:
            print(f"\n当前观察列表中共有 {len(watchlist)} 只 IPO:\n")
            _print_table(watchlist)
        return

    print(f"未来14天共有 {len(upcoming)} 只 IPO:\n")
    _print_table(upcoming)


def _print_table(records: list) -> None:
    """Print a formatted table of IPO records."""
    header = f"{'Ticker':<10} {'公司名称':<30} {'预计日期':<12} {'交易所':<8} {'价格区间':<16} {'状态':<10}"
    print(header)
    print("-" * len(header))

    for r in records:
        date_str = r.expected_date.isoformat() if r.expected_date else "TBD"
        if r.price_low and r.price_high:
            if r.price_low == r.price_high:
                price_str = f"${r.price_low:.2f}"
            else:
                price_str = f"${r.price_low:.2f}-${r.price_high:.2f}"
        else:
            price_str = "N/A"
        name = r.company_name[:28] if len(r.company_name) > 28 else r.company_name

        print(f"{r.ticker:<10} {name:<30} {date_str:<12} {r.exchange:<8} {price_str:<16} {r.status:<10}")


if __name__ == "__main__":
    main()

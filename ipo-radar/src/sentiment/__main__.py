"""CLI entry point: python -m src.sentiment

Usage:
    python -m src.sentiment TICKER [--days N] [--company NAME]
"""

from __future__ import annotations

import argparse

from src.sentiment.news_fetcher import fetch_news
from src.sentiment.sentiment_scorer import analyze_sentiment, format_sentiment_report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sentiment Analyzer - Analyze news sentiment for a stock",
    )
    parser.add_argument("ticker", help="Ticker symbol (e.g. CAVA)")
    parser.add_argument("--days", type=int, default=7, help="Look-back days (default: 7)")
    parser.add_argument("--company", default="", help="Company name for broader search")

    args = parser.parse_args()
    ticker = args.ticker.upper()

    print(f"Fetching news for {ticker} (last {args.days} days)...")
    news = fetch_news(ticker, days=args.days, company_name=args.company)

    if not news:
        print(f"No news found for {ticker}.")
        print("This may be due to network restrictions or the ticker being too new.")
        print("\nRunning sentiment analysis with no data...\n")
    else:
        print(f"Found {len(news)} articles.\n")
        # Show top 5 headlines
        print("--- Top Headlines ---")
        for item in news[:5]:
            date_str = item.date.strftime("%m/%d") if item.date else "N/A"
            print(f"  [{date_str}] {item.title[:80]}")
            print(f"          ({item.source})")
        if len(news) > 5:
            print(f"  ... and {len(news) - 5} more")
        print()

    report = analyze_sentiment(news)
    print(format_sentiment_report(report, ticker=ticker))


if __name__ == "__main__":
    main()

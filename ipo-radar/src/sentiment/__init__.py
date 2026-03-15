"""情绪分析模块 - Sentiment Analysis: Analyze market sentiment for IPO stocks."""

from src.sentiment.keyword_sentiment import (
    KeywordSentimentResult,
    score_text,
    score_texts,
)
from src.sentiment.news_fetcher import NewsItem, fetch_news
from src.sentiment.sentiment_scorer import (
    SentimentReport,
    analyze_sentiment,
    format_sentiment_report,
)

__all__ = [
    "KeywordSentimentResult",
    "NewsItem",
    "SentimentReport",
    "analyze_sentiment",
    "fetch_news",
    "format_sentiment_report",
    "score_text",
    "score_texts",
]

"""Tests for the sentiment module (news_fetcher, keyword_sentiment, sentiment_scorer)."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from src.sentiment.keyword_sentiment import (
    NEGATIVE_WORDS,
    POSITIVE_WORDS,
    KeywordSentimentResult,
    score_text,
    score_texts,
)
from src.sentiment.news_fetcher import NewsItem, fetch_news, _fetch_google_news, _fetch_reddit
from src.sentiment.sentiment_scorer import (
    SentimentReport,
    _analyze_with_keywords,
    _compute_buzz_level,
    _extract_themes,
    _normalize_source,
    analyze_sentiment,
    format_sentiment_report,
)


# ======================================================================
# keyword_sentiment.py – score_text
# ======================================================================


class TestScoreText:
    def test_positive_text(self):
        result = score_text("Stock surged on strong growth and beat expectations")
        assert result.score > 0
        assert result.positive_count > 0
        assert len(result.positive_words) > 0

    def test_negative_text(self):
        result = score_text("Stock declined after weak earnings miss and downgrade")
        assert result.score < 0
        assert result.negative_count > 0
        assert len(result.negative_words) > 0

    def test_neutral_text(self):
        result = score_text("The company held a meeting today about logistics")
        assert result.positive_count == 0
        assert result.negative_count == 0
        assert result.score == 0.0

    def test_empty_text(self):
        result = score_text("")
        assert result.score == 0.0
        assert result.positive_count == 0
        assert result.negative_count == 0

    def test_mixed_text(self):
        result = score_text("Strong growth but risk of decline concerns investors")
        assert result.positive_count > 0
        assert result.negative_count > 0

    def test_score_range(self):
        result = score_text("beat surge strong growth upgrade outperform")
        assert -1.0 <= result.score <= 1.0

    def test_case_insensitive(self):
        result = score_text("STRONG GROWTH beat SURGE")
        assert result.positive_count > 0

    def test_ipo_specific_negatives(self):
        result = score_text("lockup expiration causes dilution from insider selling")
        assert result.negative_count > 0
        assert result.score < 0

    def test_word_lists_nonempty(self):
        assert len(POSITIVE_WORDS) > 10
        assert len(NEGATIVE_WORDS) > 10

    def test_no_overlap(self):
        """Positive and negative word lists should not overlap."""
        overlap = POSITIVE_WORDS & NEGATIVE_WORDS
        assert len(overlap) == 0, f"Overlapping words: {overlap}"


# ======================================================================
# keyword_sentiment.py – score_texts
# ======================================================================


class TestScoreTexts:
    def test_aggregate_positive(self):
        texts = [
            "Strong revenue growth beats expectations",
            "Impressive gains and bullish momentum",
        ]
        result = score_texts(texts)
        assert result.score > 0
        assert result.positive_count > 0

    def test_aggregate_negative(self):
        texts = [
            "Weak earnings disappoint investors",
            "Stock plunged on fraud investigation",
        ]
        result = score_texts(texts)
        assert result.score < 0
        assert result.negative_count > 0

    def test_empty_list(self):
        result = score_texts([])
        assert result.score == 0.0
        assert result.positive_count == 0

    def test_mixed_averages_out(self):
        texts = [
            "Strong surge beat expectations",
            "Weak decline miss disappointed",
        ]
        result = score_texts(texts)
        # Mixed results — score near zero
        assert -0.5 <= result.score <= 0.5


# ======================================================================
# news_fetcher.py – NewsItem
# ======================================================================


class TestNewsItem:
    def test_to_dict(self):
        now = datetime.now()
        item = NewsItem(
            title="CAVA stock surges",
            source="Google News",
            date=now,
            url="https://example.com",
            snippet="CAVA reported strong earnings",
        )
        d = item.to_dict()
        assert d["title"] == "CAVA stock surges"
        assert d["source"] == "Google News"
        assert d["url"] == "https://example.com"
        assert d["date"] is not None

    def test_to_dict_no_date(self):
        item = NewsItem(title="Test", source="Test", date=None, url="")
        d = item.to_dict()
        assert d["date"] is None


# ======================================================================
# news_fetcher.py – _fetch_google_news (mocked)
# ======================================================================


class TestFetchGoogleNews:
    @patch("src.sentiment.news_fetcher.requests.get")
    def test_parses_rss(self, mock_get):
        now = datetime.now().astimezone()
        rfc_date = now.strftime("%a, %d %b %Y %H:%M:%S %z")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = f"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
        <channel>
          <item>
            <title>CAVA stock hits new high</title>
            <link>https://example.com/news1</link>
            <pubDate>{rfc_date}</pubDate>
            <source url="https://example.com">Reuters</source>
            <description>&lt;p&gt;CAVA Group reported strong Q3&lt;/p&gt;</description>
          </item>
          <item>
            <title>CAVA expansion plans</title>
            <link>https://example.com/news2</link>
            <pubDate>{rfc_date}</pubDate>
            <description>CAVA to open 50 new locations</description>
          </item>
        </channel>
        </rss>""".encode()
        mock_get.return_value = mock_resp

        items = _fetch_google_news("CAVA stock", days=7)
        assert len(items) == 2
        assert items[0].title == "CAVA stock hits new high"
        assert "Reuters" in items[0].source
        assert items[0].url == "https://example.com/news1"

    @patch("src.sentiment.news_fetcher.requests.get")
    def test_network_error(self, mock_get):
        mock_get.side_effect = Exception("Connection refused")
        items = _fetch_google_news("CAVA", days=7)
        assert items == []

    @patch("src.sentiment.news_fetcher.requests.get")
    def test_filters_old_news(self, mock_get):
        old_date = (datetime.now().astimezone() - timedelta(days=30)).strftime(
            "%a, %d %b %Y %H:%M:%S %z"
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = f"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
        <channel>
          <item>
            <title>Old news</title>
            <link>https://example.com/old</link>
            <pubDate>{old_date}</pubDate>
            <description>Stale content</description>
          </item>
        </channel>
        </rss>""".encode()
        mock_get.return_value = mock_resp

        items = _fetch_google_news("CAVA", days=7)
        assert len(items) == 0


# ======================================================================
# news_fetcher.py – _fetch_reddit (mocked)
# ======================================================================


class TestFetchReddit:
    @patch("src.sentiment.news_fetcher.requests.get")
    def test_parses_reddit_posts(self, mock_get):
        now_ts = datetime.now().timestamp()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": {
                "children": [
                    {
                        "data": {
                            "title": "CAVA is the next Chipotle",
                            "selftext": "Long on CAVA, great fundamentals",
                            "permalink": "/r/stocks/comments/abc123/cava/",
                            "created_utc": now_ts,
                        }
                    },
                    {
                        "data": {
                            "title": "DD on CAVA stock",
                            "selftext": "Deep dive analysis...",
                            "permalink": "/r/stocks/comments/def456/dd/",
                            "created_utc": now_ts,
                        }
                    },
                ]
            }
        }
        mock_get.return_value = mock_resp

        items = _fetch_reddit("CAVA", days=7)
        assert len(items) >= 2
        assert "CAVA" in items[0].title
        assert "Reddit" in items[0].source

    @patch("src.sentiment.news_fetcher.requests.get")
    def test_handles_rate_limit(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_get.return_value = mock_resp
        items = _fetch_reddit("CAVA", days=7)
        assert items == []

    @patch("src.sentiment.news_fetcher.requests.get")
    def test_network_error(self, mock_get):
        mock_get.side_effect = Exception("Connection error")
        items = _fetch_reddit("CAVA", days=7)
        assert items == []


# ======================================================================
# news_fetcher.py – fetch_news (mocked)
# ======================================================================


class TestFetchNews:
    @patch("src.sentiment.news_fetcher._fetch_reddit")
    @patch("src.sentiment.news_fetcher._fetch_google_news")
    def test_combines_sources(self, mock_google, mock_reddit):
        now = datetime.now()
        mock_google.return_value = [
            NewsItem("Google headline", "Google News", now, "https://g.co/1"),
        ]
        mock_reddit.return_value = [
            NewsItem("Reddit post", "Reddit - r/stocks", now, "https://reddit.com/1"),
        ]

        items = fetch_news("CAVA", days=7)
        assert len(items) == 2
        sources = [i.source for i in items]
        assert any("Google" in s for s in sources)
        assert any("Reddit" in s for s in sources)

    @patch("src.sentiment.news_fetcher._fetch_reddit")
    @patch("src.sentiment.news_fetcher._fetch_google_news")
    def test_deduplicates(self, mock_google, mock_reddit):
        now = datetime.now()
        mock_google.return_value = [
            NewsItem("CAVA stock surges on earnings", "Google News", now, "https://g.co/1"),
        ]
        mock_reddit.return_value = [
            NewsItem("CAVA stock surges on earnings", "Reddit", now, "https://reddit.com/1"),
        ]

        items = fetch_news("CAVA")
        assert len(items) == 1

    @patch("src.sentiment.news_fetcher._fetch_reddit")
    @patch("src.sentiment.news_fetcher._fetch_google_news")
    def test_sorted_newest_first(self, mock_google, mock_reddit):
        old = datetime.now() - timedelta(days=3)
        new = datetime.now()
        mock_google.return_value = [
            NewsItem("Old news", "Google", old, ""),
            NewsItem("New news", "Google", new, ""),
        ]
        mock_reddit.return_value = []

        items = fetch_news("CAVA")
        assert items[0].title == "New news"
        assert items[1].title == "Old news"


# ======================================================================
# sentiment_scorer.py – helpers
# ======================================================================


class TestHelpers:
    def test_normalize_source_reddit(self):
        assert _normalize_source("Reddit - r/stocks") == "Reddit"
        assert _normalize_source("Reddit - r/wallstreetbets") == "Reddit"

    def test_normalize_source_google(self):
        assert _normalize_source("Google News - Reuters") == "Google News"

    def test_normalize_source_other(self):
        assert _normalize_source("Bloomberg") == "Bloomberg"

    def test_buzz_level_high(self):
        assert _compute_buzz_level(20) == "high"

    def test_buzz_level_medium(self):
        assert _compute_buzz_level(8) == "medium"

    def test_buzz_level_low(self):
        assert _compute_buzz_level(3) == "low"

    def test_extract_themes(self):
        texts = [
            "Strong earnings growth and revenue beat",
            "Revenue growth continues with expansion plans",
            "Analyst upgrade on growth momentum",
        ]
        themes = _extract_themes(texts)
        assert "growth" in themes

    def test_extract_themes_empty(self):
        assert _extract_themes([]) == []


# ======================================================================
# sentiment_scorer.py – _analyze_with_keywords
# ======================================================================


class TestAnalyzeWithKeywords:
    def test_positive_news(self):
        news = [
            NewsItem("CAVA beats earnings, stock surges", "Google News",
                     datetime.now(), "", "Strong growth momentum"),
            NewsItem("Analysts upgrade CAVA to outperform", "Google News",
                     datetime.now(), "", "Bullish outlook"),
        ]
        report = _analyze_with_keywords(news)
        assert report.overall_score > 0
        assert report.positive_count > 0
        assert report.method == "keyword"

    def test_negative_news(self):
        news = [
            NewsItem("CAVA misses earnings, stock plunges", "Google News",
                     datetime.now(), "", "Weak guidance concerns"),
            NewsItem("Lockup expiration causes selling pressure", "Reddit",
                     datetime.now(), "", "Insider selling risk"),
        ]
        report = _analyze_with_keywords(news)
        assert report.overall_score < 0
        assert report.negative_count > 0

    def test_source_breakdown(self):
        news = [
            NewsItem("Strong beat", "Google News - Reuters",
                     datetime.now(), "", ""),
            NewsItem("Bullish momentum", "Reddit - r/stocks",
                     datetime.now(), "", ""),
        ]
        report = _analyze_with_keywords(news)
        assert "Google News" in report.source_breakdown
        assert "Reddit" in report.source_breakdown


# ======================================================================
# sentiment_scorer.py – analyze_sentiment
# ======================================================================


class TestAnalyzeSentiment:
    def test_empty_news_list(self):
        report = analyze_sentiment([])
        assert report.overall_score == 0.0
        assert report.positive_count == 0
        assert report.negative_count == 0
        assert report.neutral_count == 0
        assert report.buzz_level == "low"

    @patch("src.sentiment.sentiment_scorer._check_ollama_available")
    def test_falls_back_to_keyword(self, mock_ollama):
        mock_ollama.return_value = False
        news = [
            NewsItem("Stock surges on strong earnings beat",
                     "Google News", datetime.now(), "", ""),
        ]
        report = analyze_sentiment(news)
        assert report.method == "keyword"
        assert report.overall_score > 0

    @patch("src.sentiment.sentiment_scorer._check_ollama_available")
    def test_keyword_method_label(self, mock_ollama):
        mock_ollama.return_value = False
        news = [
            NewsItem("neutral headline about company", "Source",
                     datetime.now(), "", ""),
        ]
        report = analyze_sentiment(news)
        assert report.method == "keyword"


# ======================================================================
# sentiment_scorer.py – Ollama integration (mocked)
# ======================================================================


class TestOllamaIntegration:
    @patch("src.sentiment.sentiment_scorer.requests.post")
    @patch("src.sentiment.sentiment_scorer._check_ollama_available")
    def test_ollama_success(self, mock_avail, mock_post):
        mock_avail.return_value = True
        mock_post_resp = MagicMock()
        mock_post_resp.status_code = 200
        mock_post_resp.json.return_value = {
            "response": (
                '{"title": "CAVA beats", "sentiment": "positive", "score": 0.8, "theme": "earnings"}\n'
                '{"title": "Stock surges", "sentiment": "positive", "score": 0.7, "theme": "growth"}\n'
            )
        }
        mock_post.return_value = mock_post_resp

        news = [
            NewsItem("CAVA beats", "Google News", datetime.now(), "", ""),
            NewsItem("Stock surges", "Reddit", datetime.now(), "", ""),
        ]
        report = analyze_sentiment(news)
        assert report.method == "ollama"
        assert report.overall_score > 0
        assert report.positive_count == 2
        assert "earnings" in report.key_themes

    @patch("src.sentiment.sentiment_scorer.requests.post")
    @patch("src.sentiment.sentiment_scorer._check_ollama_available")
    def test_ollama_failure_falls_back(self, mock_avail, mock_post):
        mock_avail.return_value = True
        mock_post.side_effect = Exception("Connection refused")

        news = [
            NewsItem("Strong growth", "Google News", datetime.now(), "", ""),
        ]
        report = analyze_sentiment(news)
        assert report.method == "keyword"

    @patch("src.sentiment.sentiment_scorer.requests.post")
    @patch("src.sentiment.sentiment_scorer._check_ollama_available")
    def test_ollama_empty_response_falls_back(self, mock_avail, mock_post):
        mock_avail.return_value = True
        mock_post_resp = MagicMock()
        mock_post_resp.status_code = 200
        mock_post_resp.json.return_value = {"response": ""}
        mock_post.return_value = mock_post_resp

        news = [
            NewsItem("Some headline", "Google News", datetime.now(), "", ""),
        ]
        report = analyze_sentiment(news)
        # Empty Ollama response → falls back to keyword
        assert report.method == "keyword"


# ======================================================================
# sentiment_scorer.py – format_sentiment_report
# ======================================================================


class TestFormatSentimentReport:
    def test_format_includes_key_sections(self):
        report = SentimentReport(
            overall_score=0.45,
            positive_count=8,
            negative_count=2,
            neutral_count=5,
            key_themes=["growth", "earnings"],
            buzz_level="medium",
            source_breakdown={"Google News": 0.5, "Reddit": 0.3},
            method="keyword",
        )
        text = format_sentiment_report(report, ticker="CAVA")
        assert "CAVA" in text
        assert "keyword" in text
        assert "Bullish" in text
        assert "growth" in text
        assert "Google News" in text
        assert "MEDIUM" in text

    def test_format_bearish(self):
        report = SentimentReport(
            overall_score=-0.6,
            positive_count=1,
            negative_count=10,
            neutral_count=2,
            key_themes=["risk"],
            buzz_level="high",
            source_breakdown={},
            method="keyword",
        )
        text = format_sentiment_report(report, ticker="BAD")
        assert "Bearish" in text

    def test_format_neutral(self):
        report = SentimentReport(
            overall_score=0.0,
            positive_count=0,
            negative_count=0,
            neutral_count=5,
            key_themes=[],
            buzz_level="low",
            source_breakdown={},
        )
        text = format_sentiment_report(report)
        assert "Neutral" in text


# ======================================================================
# SentimentReport.to_dict
# ======================================================================


class TestSentimentReportToDict:
    def test_to_dict(self):
        report = SentimentReport(
            overall_score=0.3,
            positive_count=5,
            negative_count=2,
            neutral_count=3,
            key_themes=["growth"],
            buzz_level="medium",
            source_breakdown={"Google News": 0.4},
            method="keyword",
        )
        d = report.to_dict()
        assert d["overall_score"] == 0.3
        assert d["positive_count"] == 5
        assert d["buzz_level"] == "medium"
        assert d["method"] == "keyword"

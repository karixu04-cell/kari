"""Sentiment Scorer - Analyze news sentiment using Ollama LLM or keyword fallback.

Primary: Local Ollama (Qwen3-8B) for nuanced sentiment analysis.
Fallback: Keyword-based scoring when Ollama is unavailable.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import dataclass, field

import requests

from src.sentiment.keyword_sentiment import score_text, score_texts
from src.sentiment.news_fetcher import NewsItem

logger = logging.getLogger(__name__)

_OLLAMA_URL = "http://localhost:11434/api/generate"
_OLLAMA_MODEL = "qwen3:8b"
_OLLAMA_TIMEOUT = 30


@dataclass
class SentimentReport:
    """Aggregated sentiment analysis report."""

    overall_score: float          # -1.0 to 1.0
    positive_count: int
    negative_count: int
    neutral_count: int
    key_themes: list[str]         # main discussion topics
    buzz_level: str               # 'high' | 'medium' | 'low'
    source_breakdown: dict[str, float] = field(default_factory=dict)
    method: str = "keyword"       # 'ollama' or 'keyword'

    def to_dict(self) -> dict:
        return {
            "overall_score": self.overall_score,
            "positive_count": self.positive_count,
            "negative_count": self.negative_count,
            "neutral_count": self.neutral_count,
            "key_themes": self.key_themes,
            "buzz_level": self.buzz_level,
            "source_breakdown": self.source_breakdown,
            "method": self.method,
        }


# ---------------------------------------------------------------------------
# Ollama LLM analysis
# ---------------------------------------------------------------------------

_SENTIMENT_PROMPT = """/no_think
Analyze the sentiment of the following news headlines about a stock.
For each headline, respond with exactly one JSON object per line:
{{"title": "...", "sentiment": "positive"|"negative"|"neutral", "score": -1.0 to 1.0, "theme": "one-word theme"}}

Headlines:
{headlines}

Respond ONLY with JSON lines, no other text."""


def _check_ollama_available() -> bool:
    """Check if Ollama is running and the model is available."""
    try:
        resp = requests.get("http://localhost:11434/api/tags", timeout=3)
        return resp.status_code == 200
    except requests.RequestException:
        return False


def _analyze_with_ollama(news_list: list[NewsItem]) -> SentimentReport | None:
    """Try to analyze sentiment using local Ollama model.

    Returns None if Ollama is unavailable or fails.
    """
    if not _check_ollama_available():
        return None

    # Build headlines string
    headlines = "\n".join(
        f"- {item.title}" for item in news_list[:20]  # cap at 20
    )

    prompt = _SENTIMENT_PROMPT.format(headlines=headlines)

    try:
        resp = requests.post(
            _OLLAMA_URL,
            json={
                "model": _OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
            },
            timeout=_OLLAMA_TIMEOUT,
        )
        resp.raise_for_status()
        result = resp.json()
        response_text = result.get("response", "")
    except Exception as exc:
        logger.warning("Ollama request failed: %s", exc)
        return None

    # Parse JSON lines from response
    positive = 0
    negative = 0
    neutral = 0
    scores: list[float] = []
    themes: list[str] = []
    source_scores: dict[str, list[float]] = {}

    for line in response_text.strip().split("\n"):
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        sentiment = obj.get("sentiment", "neutral")
        score = float(obj.get("score", 0.0))
        theme = obj.get("theme", "")

        scores.append(score)
        if theme:
            themes.append(theme)

        if sentiment == "positive":
            positive += 1
        elif sentiment == "negative":
            negative += 1
        else:
            neutral += 1

    if not scores:
        return None

    # Match scores to source items
    for i, item in enumerate(news_list[:len(scores)]):
        source_key = _normalize_source(item.source)
        source_scores.setdefault(source_key, []).append(scores[i])

    source_breakdown = {
        src: round(sum(s) / len(s), 3)
        for src, s in source_scores.items()
    }

    overall = sum(scores) / len(scores)
    buzz = _compute_buzz_level(len(news_list))
    top_themes = [t for t, _ in Counter(themes).most_common(5)]

    return SentimentReport(
        overall_score=round(overall, 3),
        positive_count=positive,
        negative_count=negative,
        neutral_count=neutral,
        key_themes=top_themes,
        buzz_level=buzz,
        source_breakdown=source_breakdown,
        method="ollama",
    )


# ---------------------------------------------------------------------------
# Keyword fallback analysis
# ---------------------------------------------------------------------------


def _analyze_with_keywords(news_list: list[NewsItem]) -> SentimentReport:
    """Analyze sentiment using keyword matching (fallback)."""
    positive = 0
    negative = 0
    neutral = 0
    source_scores: dict[str, list[float]] = {}
    all_texts: list[str] = []

    for item in news_list:
        text = f"{item.title} {item.snippet}"
        all_texts.append(text)
        result = score_text(text)

        source_key = _normalize_source(item.source)
        source_scores.setdefault(source_key, []).append(result.score)

        if result.score > 0.1:
            positive += 1
        elif result.score < -0.1:
            negative += 1
        else:
            neutral += 1

    # Aggregate score
    agg = score_texts(all_texts) if all_texts else None
    overall = agg.score if agg else 0.0

    # Extract themes from most frequent significant keywords
    themes = _extract_themes(all_texts)

    source_breakdown = {
        src: round(sum(s) / len(s), 3)
        for src, s in source_scores.items()
    }

    buzz = _compute_buzz_level(len(news_list))

    return SentimentReport(
        overall_score=round(overall, 3),
        positive_count=positive,
        negative_count=negative,
        neutral_count=neutral,
        key_themes=themes,
        buzz_level=buzz,
        source_breakdown=source_breakdown,
        method="keyword",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_THEME_WORDS = frozenset({
    "earnings", "revenue", "growth", "ipo", "lockup", "lock-up",
    "acquisition", "merger", "partnership", "fda", "approval",
    "guidance", "forecast", "valuation", "expansion", "market",
    "competition", "regulation", "ai", "cloud", "saas",
    "dividend", "buyback", "insider", "institutional",
    "upgrade", "downgrade", "analyst", "target",
})


def _extract_themes(texts: list[str]) -> list[str]:
    """Extract top discussion themes from texts."""
    word_counts: Counter[str] = Counter()
    for text in texts:
        words = text.lower().split()
        for w in words:
            clean = w.strip(".,!?;:\"'()[]")
            if clean in _THEME_WORDS:
                word_counts[clean] += 1

    return [theme for theme, _ in word_counts.most_common(5)]


def _normalize_source(source: str) -> str:
    """Normalize source names for grouping."""
    source_lower = source.lower()
    if "reddit" in source_lower:
        return "Reddit"
    if "google" in source_lower:
        return "Google News"
    return source


def _compute_buzz_level(news_count: int) -> str:
    """Determine buzz level from news volume."""
    if news_count >= 15:
        return "high"
    if news_count >= 5:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyze_sentiment(news_list: list[NewsItem]) -> SentimentReport:
    """Analyze sentiment of a list of news items.

    Tries Ollama (Qwen3-8B) first, falls back to keyword analysis.

    Parameters
    ----------
    news_list : list[NewsItem]
        News items to analyze.

    Returns
    -------
    SentimentReport with overall score, counts, themes, and breakdown.
    """
    if not news_list:
        return SentimentReport(
            overall_score=0.0,
            positive_count=0,
            negative_count=0,
            neutral_count=0,
            key_themes=[],
            buzz_level="low",
            source_breakdown={},
            method="keyword",
        )

    # Try Ollama first
    ollama_result = _analyze_with_ollama(news_list)
    if ollama_result is not None:
        logger.info("Sentiment analysis via Ollama (%s)", _OLLAMA_MODEL)
        return ollama_result

    # Fallback to keyword analysis
    logger.info("Ollama unavailable, using keyword sentiment analysis")
    return _analyze_with_keywords(news_list)


def format_sentiment_report(report: SentimentReport, ticker: str = "") -> str:
    """Format a human-readable sentiment report."""
    header = f"  Sentiment Report: {ticker}" if ticker else "  Sentiment Report"
    lines = [
        f"{'=' * 55}",
        header,
        f"  (method: {report.method})",
        f"{'=' * 55}",
        "",
    ]

    # Score bar
    bar_width = 20
    normalized = (report.overall_score + 1) / 2  # 0 to 1
    filled = int(normalized * bar_width)
    bar = "█" * filled + "░" * (bar_width - filled)
    label = "Bullish" if report.overall_score > 0.1 else "Bearish" if report.overall_score < -0.1 else "Neutral"
    lines.append(f"  Overall:  [{bar}] {report.overall_score:+.2f}  ({label})")
    lines.append("")

    # Counts
    total = report.positive_count + report.negative_count + report.neutral_count
    lines.append(f"  Positive: {report.positive_count:3d}  |  Negative: {report.negative_count:3d}  |  Neutral: {report.neutral_count:3d}")
    lines.append(f"  Total articles: {total}")
    lines.append(f"  Buzz level: {report.buzz_level.upper()}")
    lines.append("")

    # Themes
    if report.key_themes:
        lines.append(f"  Key themes: {', '.join(report.key_themes)}")
        lines.append("")

    # Source breakdown
    if report.source_breakdown:
        lines.append("  By source:")
        for src, score in sorted(report.source_breakdown.items()):
            s_label = "+" if score > 0.1 else "-" if score < -0.1 else "~"
            lines.append(f"    {src:<20} {score:+.2f}  ({s_label})")
        lines.append("")

    lines.append(f"{'=' * 55}")
    return "\n".join(lines)

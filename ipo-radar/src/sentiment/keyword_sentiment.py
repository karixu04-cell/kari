"""Keyword-based sentiment analysis fallback.

Uses curated positive/negative word lists tuned for financial/IPO context.
No external dependencies required.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Word lists (lowercase, finance/IPO-focused)
# ---------------------------------------------------------------------------

POSITIVE_WORDS: frozenset[str] = frozenset({
    # Earnings / performance
    "beat", "beats", "exceeded", "surpass", "surpassed", "outperform",
    "outperformed", "strong", "stronger", "robust", "solid", "record",
    "impressive", "stellar",
    # Growth
    "growth", "growing", "surge", "surged", "soared", "soaring", "rally",
    "rallied", "gain", "gains", "jumped", "jumps", "climbing",
    # Upgrades
    "upgrade", "upgraded", "bullish", "buy", "overweight", "positive",
    "optimistic", "confident", "momentum",
    # Innovation / strategy
    "innovative", "innovation", "breakthrough", "disruptive", "expansion",
    "expanding", "launched", "partnership", "acquisition",
    # Financials
    "profitable", "profitability", "revenue", "margin", "dividend",
    "buyback", "repurchase",
    # Market
    "highs", "breakout", "upside", "opportunity", "undervalued",
})

NEGATIVE_WORDS: frozenset[str] = frozenset({
    # Earnings / performance
    "miss", "missed", "missed", "disappoint", "disappointed", "disappointing",
    "weak", "weaker", "poor", "underperform", "underperformed",
    # Decline
    "decline", "declined", "declining", "drop", "dropped", "fall", "fell",
    "plunge", "plunged", "crash", "crashed", "sink", "sinking", "tumbled",
    "slump",
    # Downgrades
    "downgrade", "downgraded", "bearish", "sell", "underweight", "negative",
    "pessimistic", "concern", "concerns", "worried", "warning",
    # Risk
    "risk", "risks", "risky", "lawsuit", "litigation", "investigation",
    "fraud", "scandal", "violation", "penalty", "fine", "fined",
    # IPO-specific negatives
    "dilution", "dilutive", "lockup", "lock-up", "expiration", "insider",
    "selling", "secondary", "offering",
    # Operations
    "delay", "delayed", "shortage", "recall", "layoff", "layoffs",
    "restructuring", "bankruptcy", "default", "debt",
    # Market
    "overvalued", "bubble", "correction", "volatility", "uncertain",
    "uncertainty",
})


@dataclass
class KeywordSentimentResult:
    """Result of keyword-based sentiment analysis on a single text."""

    score: float           # -1.0 to 1.0
    positive_count: int
    negative_count: int
    positive_words: list[str]
    negative_words: list[str]


def _tokenize(text: str) -> list[str]:
    """Split text into lowercase word tokens."""
    return re.findall(r"[a-z]+(?:[-'][a-z]+)*", text.lower())


def score_text(text: str) -> KeywordSentimentResult:
    """Score a single text using keyword matching.

    Parameters
    ----------
    text : str
        The text to analyze (title, snippet, etc.)

    Returns
    -------
    KeywordSentimentResult with score in [-1.0, 1.0].
    """
    tokens = _tokenize(text)
    if not tokens:
        return KeywordSentimentResult(
            score=0.0, positive_count=0, negative_count=0,
            positive_words=[], negative_words=[],
        )

    pos_found = [t for t in tokens if t in POSITIVE_WORDS]
    neg_found = [t for t in tokens if t in NEGATIVE_WORDS]

    pos_count = len(pos_found)
    neg_count = len(neg_found)
    total = pos_count + neg_count

    if total == 0:
        score = 0.0
    else:
        score = (pos_count - neg_count) / total

    return KeywordSentimentResult(
        score=round(score, 4),
        positive_count=pos_count,
        negative_count=neg_count,
        positive_words=sorted(set(pos_found)),
        negative_words=sorted(set(neg_found)),
    )


def score_texts(texts: list[str]) -> KeywordSentimentResult:
    """Score multiple texts and return an aggregate result.

    Parameters
    ----------
    texts : list[str]
        List of texts to analyze.

    Returns
    -------
    Aggregated KeywordSentimentResult.
    """
    if not texts:
        return KeywordSentimentResult(
            score=0.0, positive_count=0, negative_count=0,
            positive_words=[], negative_words=[],
        )

    all_pos: list[str] = []
    all_neg: list[str] = []
    total_pos = 0
    total_neg = 0

    for text in texts:
        r = score_text(text)
        total_pos += r.positive_count
        total_neg += r.negative_count
        all_pos.extend(r.positive_words)
        all_neg.extend(r.negative_words)

    total = total_pos + total_neg
    if total == 0:
        score = 0.0
    else:
        score = (total_pos - total_neg) / total

    return KeywordSentimentResult(
        score=round(score, 4),
        positive_count=total_pos,
        negative_count=total_neg,
        positive_words=sorted(set(all_pos)),
        negative_words=sorted(set(all_neg)),
    )

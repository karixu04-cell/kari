"""News Fetcher - Gather news from free sources for sentiment analysis.

Sources:
- Google News RSS feed (no API key required)
- Reddit search API (public, unauthenticated)
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import requests

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "IPORadar/0.1 (research tool)",
    "Accept": "text/html,application/json,application/xml",
}

_TIMEOUT = 15


@dataclass
class NewsItem:
    """A single news item."""

    title: str
    source: str
    date: datetime | None
    url: str
    snippet: str = ""

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "source": self.source,
            "date": self.date.isoformat() if self.date else None,
            "url": self.url,
            "snippet": self.snippet,
        }


# ---------------------------------------------------------------------------
# Google News RSS
# ---------------------------------------------------------------------------

_GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"


def _fetch_google_news(query: str, days: int = 7) -> list[NewsItem]:
    """Fetch news from Google News RSS feed."""
    url = _GOOGLE_NEWS_RSS.format(query=quote_plus(query))
    cutoff = datetime.now().astimezone() - timedelta(days=days)

    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("Google News fetch failed: %s", exc)
        return []

    items: list[NewsItem] = []
    try:
        root = ET.fromstring(resp.content)
        for item_el in root.iter("item"):
            title = (item_el.findtext("title") or "").strip()
            link = (item_el.findtext("link") or "").strip()
            pub_date_str = item_el.findtext("pubDate") or ""
            source_el = item_el.find("source")
            source = source_el.text.strip() if source_el is not None and source_el.text else "Google News"

            pub_date = None
            if pub_date_str:
                try:
                    pub_date = parsedate_to_datetime(pub_date_str)
                except (ValueError, TypeError):
                    pass

            # Filter by date
            if pub_date and pub_date < cutoff:
                continue

            # Extract snippet from description (strip HTML)
            desc = (item_el.findtext("description") or "").strip()
            snippet = re.sub(r"<[^>]+>", "", desc)[:300]

            if title:
                items.append(NewsItem(
                    title=title,
                    source=f"Google News - {source}",
                    date=pub_date,
                    url=link,
                    snippet=snippet,
                ))
    except ET.ParseError as exc:
        logger.warning("Failed to parse Google News RSS: %s", exc)

    return items


# ---------------------------------------------------------------------------
# Reddit Search
# ---------------------------------------------------------------------------

_REDDIT_SEARCH = "https://www.reddit.com/search.json"
_SUBREDDITS = ("stocks", "wallstreetbets", "investing", "stockmarket")


def _fetch_reddit(query: str, days: int = 7) -> list[NewsItem]:
    """Fetch posts from Reddit search API (public, no auth)."""
    cutoff_ts = (datetime.now() - timedelta(days=days)).timestamp()
    items: list[NewsItem] = []

    # Search specific subreddits
    for sub in _SUBREDDITS:
        url = f"https://www.reddit.com/r/{sub}/search.json"
        params = {
            "q": query,
            "sort": "relevance",
            "t": "week" if days <= 7 else "month",
            "limit": 10,
            "restrict_sr": "on",
        }
        headers = {**_HEADERS, "User-Agent": "IPORadar/0.1 (by research tool)"}

        try:
            resp = requests.get(url, params=params, headers=headers, timeout=_TIMEOUT)
            if resp.status_code == 429:
                logger.debug("Reddit rate limited for r/%s", sub)
                continue
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.debug("Reddit r/%s fetch failed: %s", sub, exc)
            continue

        for post in data.get("data", {}).get("children", []):
            post_data = post.get("data", {})
            created = post_data.get("created_utc", 0)
            if created < cutoff_ts:
                continue

            title = post_data.get("title", "").strip()
            if not title:
                continue

            selftext = (post_data.get("selftext") or "")[:300]
            permalink = post_data.get("permalink", "")
            post_url = f"https://www.reddit.com{permalink}" if permalink else ""

            pub_date = datetime.fromtimestamp(created) if created else None

            items.append(NewsItem(
                title=title,
                source=f"Reddit - r/{sub}",
                date=pub_date,
                url=post_url,
                snippet=selftext,
            ))

    return items


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_news(ticker: str, days: int = 7, company_name: str = "") -> list[NewsItem]:
    """Fetch news for a ticker from multiple free sources.

    Parameters
    ----------
    ticker : str
        Stock ticker symbol (e.g. "CAVA").
    days : int
        Number of days to look back (default 7).
    company_name : str
        Optional company name for broader search.

    Returns
    -------
    List of NewsItem, sorted by date (newest first).
    """
    query = f"{ticker} stock"
    if company_name:
        query = f"{company_name} {ticker}"

    all_items: list[NewsItem] = []

    # Fetch from all sources
    all_items.extend(_fetch_google_news(query, days=days))
    all_items.extend(_fetch_reddit(ticker, days=days))

    # Deduplicate by title similarity
    seen_titles: set[str] = set()
    unique: list[NewsItem] = []
    for item in all_items:
        key = item.title.lower()[:60]
        if key not in seen_titles:
            seen_titles.add(key)
            unique.append(item)

    # Sort by date (newest first), items without date go last
    unique.sort(key=lambda x: x.date or datetime.min, reverse=True)

    return unique

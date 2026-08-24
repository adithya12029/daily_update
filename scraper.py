"""
scraper.py

Fetches recent news articles per topic from Google News RSS feeds,
filters them to the last 24 hours, and removes any that have already
been sent within the deduplication retention window.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from time import mktime
from typing import Dict, List
from urllib.parse import quote_plus

import feedparser

from config import (
    ARTICLE_FRESHNESS_HOURS,
    GOOGLE_NEWS_COUNTRY,
    GOOGLE_NEWS_LANGUAGE,
    GOOGLE_NEWS_RSS_BASE_URL,
    MAX_CANDIDATES_PER_TOPIC,
)
from database import is_duplicate


@dataclass
class Article:
    """A single candidate news article."""

    title: str
    url: str
    source: str
    topic: str
    published_at: datetime


def _build_rss_url(topic: str) -> str:
    """
    Construct a Google News RSS search URL for a given topic.

    Args:
        topic: The search topic/query string.

    Returns:
        A fully formed Google News RSS URL.
    """
    query = quote_plus(topic)
    lang_short = GOOGLE_NEWS_LANGUAGE.split("-")[0]
    return (
        f"{GOOGLE_NEWS_RSS_BASE_URL}?q={query}"
        f"&hl={GOOGLE_NEWS_LANGUAGE}&gl={GOOGLE_NEWS_COUNTRY}&ceid={GOOGLE_NEWS_COUNTRY}:{lang_short}"
    )


def _parse_entry_datetime(entry: "feedparser.FeedParserDict") -> datetime:
    """
    Extract a timezone-aware UTC datetime from a feedparser entry.

    Args:
        entry: A single feedparser entry.

    Returns:
        A timezone-aware UTC datetime. Defaults to "now" if the feed did
        not provide a parseable publish date, so the article is not
        incorrectly filtered out due to missing metadata.
    """
    time_struct = getattr(entry, "published_parsed", None)
    if time_struct is None:
        return datetime.now(timezone.utc)
    return datetime.fromtimestamp(mktime(time_struct), tz=timezone.utc)


def fetch_topic_candidates(topic: str) -> List[Article]:
    """
    Fetch and filter candidate articles for a single topic.

    Articles are excluded if they are older than ARTICLE_FRESHNESS_HOURS
    or if they have already been sent within the deduplication window.

    Args:
        topic: The topic/search query to fetch news for.

    Returns:
        A list of fresh, non-duplicate Article objects (may be empty).

    Raises:
        RuntimeError: If the RSS feed cannot be fetched or parsed at all.
    """
    rss_url = _build_rss_url(topic)

    try:
        feed = feedparser.parse(rss_url)
    except Exception as exc:
        raise RuntimeError(f"Failed to fetch/parse RSS feed for topic '{topic}': {exc}") from exc

    entries = getattr(feed, "entries", None)
    if not entries:
        if getattr(feed, "bozo", False):
            raise RuntimeError(
                f"Malformed or empty RSS feed for topic '{topic}': "
                f"{getattr(feed, 'bozo_exception', 'unknown error')}"
            )
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=ARTICLE_FRESHNESS_HOURS)
    candidates: List[Article] = []

    for entry in entries[: MAX_CANDIDATES_PER_TOPIC * 2]:
        url = getattr(entry, "link", None)
        title = getattr(entry, "title", None)
        if not url or not title:
            continue

        published_at = _parse_entry_datetime(entry)
        if published_at < cutoff:
            continue

        try:
            if is_duplicate(url):
                continue
        except Exception:
            # Fail safe: if the dedup check itself errors, skip the
            # article rather than crashing the whole pipeline.
            continue

        source = getattr(entry, "source", {})
        source_title = (
            source.get("title", "Unknown Source") if isinstance(source, dict) else "Unknown Source"
        )

        candidates.append(
            Article(
                title=title,
                url=url,
                source=source_title,
                topic=topic,
                published_at=published_at,
            )
        )

        if len(candidates) >= MAX_CANDIDATES_PER_TOPIC:
            break

    return candidates


def fetch_all_candidates(topics: List[str]) -> Dict[str, List[Article]]:
    """
    Fetch candidate articles for a list of topics.

    A failure on one topic does not abort the others; it is logged and
    that topic simply returns an empty list.

    Args:
        topics: A list of topic strings to fetch news for.

    Returns:
        A dict mapping topic -> list of Article objects.
    """
    results: Dict[str, List[Article]] = {}
    for topic in topics:
        try:
            results[topic] = fetch_topic_candidates(topic)
        except RuntimeError as exc:
            print(f"[scraper] Warning: could not fetch news for topic '{topic}': {exc}")
            results[topic] = []
    return results

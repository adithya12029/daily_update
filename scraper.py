"""scraper.py

Fetches recent news articles per topic from Google News RSS feeds,
filters them to the last 24 hours, extracts a clean summary snippet,
and removes any that have already been sent within the deduplication retention window.
"""

import html
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from time import mktime
from typing import Dict, List, Union
from urllib.parse import quote_plus

import feedparser

import config
from config import (
    ARTICLE_FRESHNESS_HOURS,
    GOOGLE_NEWS_COUNTRY,
    GOOGLE_NEWS_LANGUAGE,
    GOOGLE_NEWS_RSS_BASE_URL,
    MAX_CANDIDATES_PER_TOPIC,
)
from database import is_duplicate

# Fallback to default test topics if DAILY_TOPICS is not defined in config
TEST_TOPICS = getattr(
    config, "DAILY_TOPICS", ["Artificial Intelligence", "Space Exploration"]
)


@dataclass
class Article:
    """A single candidate news article."""

    title: str
    url: str
    source: str
    topic: str
    published_at: datetime
    summary: str = ""  # Default ensures compatibility with 5-arg instantiation


def _clean_html_snippet(raw_html: str) -> str:
    """Strip HTML tags, unescape entities, and normalize whitespace."""
    if not raw_html:
        return "No summary snippet available."
    unescaped = html.unescape(raw_html)
    clean_text = re.sub(r"<[^>]+>", " ", unescaped)
    clean_text = " ".join(clean_text.split())
    return clean_text if clean_text else "No summary snippet available."


def _build_rss_url(query_str: str) -> str:
    """Construct a Google News RSS search URL for a given query string."""
    query = quote_plus(query_str)
    lang_short = GOOGLE_NEWS_LANGUAGE.split("-")[0]
    return (
        f"{GOOGLE_NEWS_RSS_BASE_URL}?q={query}"
        f"&hl={GOOGLE_NEWS_LANGUAGE}&gl={GOOGLE_NEWS_COUNTRY}&ceid={GOOGLE_NEWS_COUNTRY}:{lang_short}"
    )


def _parse_entry_datetime(entry: "feedparser.FeedParserDict") -> datetime:
    """Extract a timezone-aware UTC datetime from a feedparser entry."""
    time_struct = getattr(entry, "published_parsed", None)
    if time_struct is None:
        return datetime.now(timezone.utc)
    return datetime.fromtimestamp(mktime(time_struct), tz=timezone.utc)


def fetch_topic_candidates(topic_name: str, search_query: str = None) -> List[Article]:
    """Fetch and filter candidate articles for a single topic using a specific search query."""
    query_to_use = search_query if search_query else topic_name
    rss_url = _build_rss_url(query_to_use)

    try:
        feed = feedparser.parse(rss_url)
    except Exception as exc:
        raise RuntimeError(
            f"Failed to fetch/parse RSS feed for topic '{topic_name}': {exc}"
        ) from exc

    entries = getattr(feed, "entries", None)
    if not entries:
        if getattr(feed, "bozo", False):
            raise RuntimeError(
                f"Malformed or empty RSS feed for topic '{topic_name}': "
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
            continue

        source_obj = getattr(entry, "source", None)
        if isinstance(source_obj, dict):
            source_title = source_obj.get("title", "Unknown Source")
        else:
            source_title = getattr(source_obj, "title", "Unknown Source")

        raw_summary = (
            getattr(entry, "summary", "") or getattr(entry, "description", "")
        )
        clean_summary = _clean_html_snippet(raw_summary)

        candidates.append(
            Article(
                title=title,
                url=url,
                source=source_title,
                topic=topic_name,
                published_at=published_at,
                summary=clean_summary,
            )
        )

        if len(candidates) >= MAX_CANDIDATES_PER_TOPIC:
            break

    return candidates


def fetch_all_candidates(
    topics: Union[Dict[str, str], List[str]]
) -> Dict[str, List[Article]]:
    """Fetch candidate articles for topics (supports both dict mapping and list)."""
    results: Dict[str, List[Article]] = {}

    if isinstance(topics, dict):
        items = topics.items()
    else:
        items = [(t, t) for t in topics]

    for topic_name, search_query in items:
        try:
            results[topic_name] = fetch_topic_candidates(topic_name, search_query)
        except RuntimeError as exc:
            print(f"[scraper] Warning: could not fetch news for topic '{topic_name}': {exc}")
            results[topic_name] = []
    return results
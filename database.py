"""
database.py

SQLite-backed persistence layer for tracking previously-sent articles.
Used to deduplicate news stories across a rolling retention window.
"""

import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Generator, List

from config import DB_PATH, DEDUP_RETENTION_DAYS


def _hash_url(url: str) -> str:
    """
    Generate a stable SHA-256 hash for a given URL.

    Args:
        url: The article URL to hash.

    Returns:
        A hex-encoded SHA-256 digest of the normalized URL.
    """
    return hashlib.sha256(url.strip().lower().encode("utf-8")).hexdigest()


@contextmanager
def _get_connection(db_path: Path = DB_PATH) -> Generator[sqlite3.Connection, None, None]:
    """
    Context manager that yields a SQLite connection and guarantees it is
    committed (or rolled back on error) and closed afterward.

    Args:
        db_path: Path to the SQLite database file.

    Yields:
        An open sqlite3.Connection object.
    """
    conn = sqlite3.connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path = DB_PATH) -> None:
    """
    Initialize the SQLite database and create the `sent_articles` table
    if it does not already exist.

    Args:
        db_path: Path to the SQLite database file.

    Raises:
        sqlite3.Error: If table creation fails.
    """
    try:
        with _get_connection(db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sent_articles (
                    url_hash TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    sent_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sent_at ON sent_articles (sent_at)"
            )
    except sqlite3.Error as exc:
        raise sqlite3.Error(f"Failed to initialize database at {db_path}: {exc}") from exc


def is_duplicate(
    url: str, db_path: Path = DB_PATH, retention_days: int = DEDUP_RETENTION_DAYS
) -> bool:
    """
    Check whether a URL was already sent within the retention window.

    Args:
        url: The article URL to check.
        db_path: Path to the SQLite database file.
        retention_days: How many days back to check for duplicates.

    Returns:
        True if the URL was sent within the retention window, False otherwise.

    Raises:
        sqlite3.Error: If the query fails.
    """
    url_hash = _hash_url(url)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()

    try:
        with _get_connection(db_path) as conn:
            cursor = conn.execute(
                "SELECT 1 FROM sent_articles WHERE url_hash = ? AND sent_at >= ? LIMIT 1",
                (url_hash, cutoff),
            )
            return cursor.fetchone() is not None
    except sqlite3.Error as exc:
        raise sqlite3.Error(f"Failed to check duplicate status for URL '{url}': {exc}") from exc


def mark_as_sent(articles: List[Dict[str, str]], db_path: Path = DB_PATH) -> None:
    """
    Record a list of dispatched articles in the database so they are
    excluded from future digests within the retention window.

    Args:
        articles: A list of dicts, each expected to contain at least
            'url' and 'topic' keys.
        db_path: Path to the SQLite database file.

    Raises:
        sqlite3.Error: If the insert operation fails.
        KeyError: If an article dict is missing a required key.
    """
    if not articles:
        return

    now_iso = datetime.now(timezone.utc).isoformat()

    try:
        with _get_connection(db_path) as conn:
            for article in articles:
                url = article["url"]
                topic = article["topic"]
                conn.execute(
                    """
                    INSERT OR REPLACE INTO sent_articles (url_hash, url, topic, sent_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (_hash_url(url), url, topic, now_iso),
                )
    except KeyError as exc:
        raise KeyError(f"Article dict missing required key: {exc}") from exc
    except sqlite3.Error as exc:
        raise sqlite3.Error(f"Failed to mark articles as sent: {exc}") from exc


def purge_old_records(
    db_path: Path = DB_PATH, retention_days: int = DEDUP_RETENTION_DAYS
) -> int:
    """
    Delete records older than the retention window to keep the database
    lean. Safe to run on every execution.

    Args:
        db_path: Path to the SQLite database file.
        retention_days: How many days of history to retain.

    Returns:
        The number of rows deleted.

    Raises:
        sqlite3.Error: If the delete operation fails.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
    try:
        with _get_connection(db_path) as conn:
            cursor = conn.execute("DELETE FROM sent_articles WHERE sent_at < ?", (cutoff,))
            return cursor.rowcount
    except sqlite3.Error as exc:
        raise sqlite3.Error(f"Failed to purge old records: {exc}") from exc

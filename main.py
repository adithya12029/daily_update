"""
main.py

Central orchestrator for the News Agent pipeline:
1. Initialize the database.
2. Fetch candidate articles per topic (deduplicated against history).
3. Use Claude to curate the top story per topic.
4. Email the digest.
5. Record sent articles in the database ONLY on successful delivery.
"""

import sys
from typing import List

from config import DAILY_TOPICS, DEDUP_RETENTION_DAYS
from database import init_db, mark_as_sent, purge_old_records
from notifier import send_digest_email
from scraper import fetch_all_candidates
from summarizer import CuratedStory, curate_top_stories


def run_pipeline() -> None:
    """
    Execute the full news agent pipeline end-to-end.

    Exits with a non-zero status code on unrecoverable failure, after
    printing a clear error message.
    """
    print("[main] Initializing database...")
    try:
        init_db()
        purged = purge_old_records()
        if purged:
            print(f"[main] Purged {purged} record(s) older than {DEDUP_RETENTION_DAYS} days.")
    except Exception as exc:
        print(f"[main] FATAL: could not initialize database: {exc}")
        sys.exit(1)

    print(f"[main] Fetching candidate articles for {len(DAILY_TOPICS)} topics...")
    try:
        candidates_by_topic = fetch_all_candidates(DAILY_TOPICS)
    except Exception as exc:
        print(f"[main] FATAL: candidate fetching failed unexpectedly: {exc}")
        sys.exit(1)

    total_candidates = sum(len(v) for v in candidates_by_topic.values())
    print(f"[main] Found {total_candidates} fresh, non-duplicate candidate(s) across all topics.")

    curated_stories: List[CuratedStory] = []
    if total_candidates == 0:
        print("[main] No new candidates found today. Sending an empty digest notice.")
    else:
        print("[main] Asking Claude to curate top stories...")
        try:
            curated_stories = curate_top_stories(candidates_by_topic)
        except Exception as exc:
            print(f"[main] FATAL: curation step failed: {exc}")
            sys.exit(1)
        print(f"[main] Curated {len(curated_stories)} top stor(y/ies).")

    print("[main] Sending digest email...")
    try:
        send_digest_email(curated_stories)
    except Exception as exc:
        print(f"[main] FATAL: email delivery failed, history will NOT be updated: {exc}")
        sys.exit(1)

    print("[main] Email delivered successfully. Recording sent articles in history...")
    try:
        articles_to_record = [
            {"url": story["url"], "topic": story["topic"]} for story in curated_stories
        ]
        mark_as_sent(articles_to_record)
    except Exception as exc:
        # The email already sent successfully; a history-write failure is
        # surfaced but should not be treated as a full pipeline failure.
        print(f"[main] WARNING: email sent, but failed to record history: {exc}")
        sys.exit(2)

    print("[main] Pipeline completed successfully.")


if __name__ == "__main__":
    run_pipeline()

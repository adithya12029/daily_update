"""
config.py

Centralized configuration for the News Agent application.
Loads sensitive values from environment variables (.env file) and
defines shared constants used across all other modules.
"""

import os
from pathlib import Path
from typing import List

from dotenv import load_dotenv

# Load environment variables from a .env file located in the project root.
load_dotenv()


def _get_required_env(var_name: str) -> str:
    """
    Fetch a required environment variable or raise a clear error.

    Args:
        var_name: The name of the environment variable to fetch.

    Returns:
        The value of the environment variable.

    Raises:
        EnvironmentError: If the variable is not set or is empty.
    """
    value = os.getenv(var_name)
    if not value:
        raise EnvironmentError(
            f"Missing required environment variable: '{var_name}'. "
            f"Please set it in your .env file (see .env.example)."
        )
    return value


# --------------------------------------------------------------------------
# Credentials / Secrets (loaded from .env)
# --------------------------------------------------------------------------
GEMINI_API_KEY: str = _get_required_env("GEMINI_API_KEY")
GMAIL_USER: str = _get_required_env("GMAIL_USER")
GMAIL_APP_PASSWORD: str = _get_required_env("GMAIL_APP_PASSWORD")
RECIPIENT_EMAIL: str = _get_required_env("RECIPIENT_EMAIL")

# --------------------------------------------------------------------------
# Topics: the 5 daily target topics the agent will scan for news.
# Edit this list to change what the agent tracks.
# --------------------------------------------------------------------------
DAILY_TOPICS: List[str] = [
    "Artificial Intelligence",
    "Global Economy",
    "Climate Change",
    "Space Exploration",
    "Cybersecurity",
]

# --------------------------------------------------------------------------
# Deduplication / retention settings
# --------------------------------------------------------------------------
# Number of days a previously-sent article URL is remembered and excluded
# from future digests.
DEDUP_RETENTION_DAYS: int = 10

# Only consider articles published within this many hours as "fresh".
ARTICLE_FRESHNESS_HOURS: int = 24

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
BASE_DIR: Path = Path(__file__).resolve().parent
DB_PATH: Path = BASE_DIR / "news_agent.db"

# --------------------------------------------------------------------------
# Scraper settings
# --------------------------------------------------------------------------
GOOGLE_NEWS_RSS_BASE_URL: str = "https://news.google.com/rss/search"
GOOGLE_NEWS_LANGUAGE: str = "en-US"
GOOGLE_NEWS_COUNTRY: str = "US"
# Max number of candidate articles kept per topic after filtering.
MAX_CANDIDATES_PER_TOPIC: int = 10

# --------------------------------------------------------------------------
# LLM settings
# --------------------------------------------------------------------------
# Gemini has a generous free tier (as of this writing, gemini-2.5-flash is
# free within daily rate limits) — check https://ai.google.dev/pricing for
# current limits. Swap this string if you want a different Gemini model.
GEMINI_MODEL: str = "gemini-2.5-flash"
LLM_MAX_TOKENS: int = 1024

# --------------------------------------------------------------------------
# Email settings
# --------------------------------------------------------------------------
SMTP_HOST: str = "smtp.gmail.com"
SMTP_PORT: int = 465
EMAIL_SUBJECT_PREFIX: str = "🗞️ Your Daily News Digest"
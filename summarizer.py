"""
summarizer.py

Curates the single most important story per topic from a set of candidate
articles using the Gemini API and generates a 2-sentence summary.
Includes exponential backoff for rate limits (HTTP 429) and an offline fallback.
"""

import time
import random
from typing import Dict, List, TypedDict
from pydantic import BaseModel, Field

from config import GEMINI_API_KEY, GEMINI_MODEL, LLM_MAX_TOKENS
from scraper import Article

try:
    from google import genai
    from google.genai import types
    from google.genai.errors import APIError
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False


class CuratedStory(TypedDict):
    """Structured representation of a single curated news story."""
    topic: str
    title: str
    url: str
    source: str
    summary: str


# --- Structured Schema for Gemini ---

class TopicSelection(BaseModel):
    """Selection and summary for a single topic."""
    topic_id: int = Field(description="1-based index corresponding to the topic number.")
    selected_candidate_id: int = Field(
        description="1-based index of the single most important article candidate."
    )
    summary: str = Field(
        description="A concise, neutral 2-sentence summary of the selected development."
    )


class CurationResponse(BaseModel):
    """Top-level container for all topic selections."""
    selections: List[TopicSelection]


_SYSTEM_PROMPT = """You are a professional news editor.
For each topic, review the candidates and:
1. Select the SINGLE most impactful, newsworthy, and non-trivial candidate article.
2. Write a concise, neutral 2-sentence summary for the selected development.
3. Return only the numeric topic_id, selected_candidate_id, and the summary."""


def _build_user_prompt(
    topic_keys: List[str],
    candidates_by_topic: Dict[str, List[Article]],
) -> str:
    """Format candidate articles into numbered topics and candidate indices."""
    lines: List[str] = []
    for t_idx, topic in enumerate(topic_keys, start=1):
        articles = candidates_by_topic.get(topic, [])
        lines.append(f"=== Topic {t_idx}: {topic} ===")
        if not articles:
            lines.append("(no candidates)")
            continue
        for c_idx, article in enumerate(articles, start=1):
            lines.append(
                f"[Candidate {c_idx}]\n"
                f"Title: {article.title}\n"
                f"Source: {article.source}\n"
                f"Snippet: {getattr(article, 'summary', '') or article.title}"
            )
        lines.append("")
    return "\n".join(lines)


def _heuristic_fallback(
    candidates_by_topic: Dict[str, List[Article]],
) -> List[CuratedStory]:
    """Fallback: Selects the first candidate and uses its existing snippet."""
    curated: List[CuratedStory] = []
    for topic, articles in candidates_by_topic.items():
        if not articles:
            continue
        top = articles[0]
        curated.append(
            CuratedStory(
                topic=topic,
                title=top.title,
                url=top.url,
                source=top.source,
                summary=getattr(top, "summary", "") or top.title,
            )
        )
    return curated


def _call_gemini_with_retry(
    client: "genai.Client",
    user_prompt: str,
    max_retries: int = 4,
    initial_delay: float = 2.0,
    backoff_factor: float = 2.0,
) -> CurationResponse:
    """
    Executes generate_content with exponential backoff and jitter for 429/transient errors.
    """
    delay = initial_delay

    for attempt in range(1, max_retries + 1):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=_SYSTEM_PROMPT,
                    max_output_tokens=max(LLM_MAX_TOKENS, 2048),
                    response_mime_type="application/json",
                    response_schema=CurationResponse,
                    temperature=0.2,
                ),
            )
            parsed: CurationResponse = response.parsed
            if not parsed or not parsed.selections:
                raise ValueError("Model returned an empty structured response.")
            return parsed

        except Exception as exc:
            err_str = str(exc).lower()
            is_rate_limit = "429" in err_str or "resource_exhausted" in err_str or "quota" in err_str
            is_transient = "503" in err_str or "unavailable" in err_str or "timeout" in err_str

            if (is_rate_limit or is_transient) and attempt < max_retries:
                jitter = random.uniform(0.5, 1.5)
                sleep_duration = (delay * jitter)
                print(f"[summarizer] Rate limit/Transient error hit on attempt {attempt}/{max_retries}. "
                      f"Retrying in {sleep_duration:.2f}s...")
                time.sleep(sleep_duration)
                delay *= backoff_factor
            else:
                raise exc


def curate_top_stories(
    candidates_by_topic: Dict[str, List[Article]],
) -> List[CuratedStory]:
    """Curates the top story per topic and returns structured CuratedStory objects."""
    topics_with_candidates = {t: a for t, a in candidates_by_topic.items() if a}
    if not topics_with_candidates:
        return []

    if not GEMINI_API_KEY or not GENAI_AVAILABLE:
        print("[summarizer] Missing API key or google-genai package. Using fallback.")
        return _heuristic_fallback(topics_with_candidates)

    topic_keys = list(topics_with_candidates.keys())
    user_prompt = _build_user_prompt(topic_keys, topics_with_candidates)

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        parsed_data = _call_gemini_with_retry(client, user_prompt)

        curated_stories: List[CuratedStory] = []
        handled_topics = set()

        for sel in parsed_data.selections:
            t_idx = sel.topic_id - 1
            if not (0 <= t_idx < len(topic_keys)):
                continue

            topic = topic_keys[t_idx]
            articles = topics_with_candidates[topic]
            c_idx = sel.selected_candidate_id - 1

            # Fall back to first candidate if the LLM returns an out-of-bounds index
            selected_article = articles[c_idx] if 0 <= c_idx < len(articles) else articles[0]

            curated_stories.append(
                CuratedStory(
                    topic=topic,
                    title=selected_article.title,
                    url=selected_article.url,
                    source=selected_article.source,
                    summary=sel.summary.strip(),
                )
            )
            handled_topics.add(topic)

        # Backfill any topics the LLM dropped from its output
        for topic in topic_keys:
            if topic not in handled_topics:
                first = topics_with_candidates[topic][0]
                curated_stories.append(
                    CuratedStory(
                        topic=topic,
                        title=first.title,
                        url=first.url,
                        source=first.source,
                        summary=getattr(first, "summary", "") or first.title,
                    )
                )

        return curated_stories

    except Exception as exc:
        print(f"[summarizer] Warning: Gemini curation failed ({exc}). Using fallback.")
        return _heuristic_fallback(topics_with_candidates)



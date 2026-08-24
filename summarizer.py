"""
summarizer.py

Uses the Google Gemini API (free-tier friendly) to curate the single most
important story per topic from a set of candidate articles, and generate
a concise 2-sentence summary for each selected story.
"""

import json
from typing import Dict, List, TypedDict

from google import genai
from google.genai import types

from config import GEMINI_API_KEY, GEMINI_MODEL, LLM_MAX_TOKENS
from scraper import Article


class CuratedStory(TypedDict):
    """Structured representation of a single curated news story."""

    topic: str
    title: str
    url: str
    source: str
    summary: str


_SYSTEM_PROMPT = """You are a professional news editor. You will be given, for \
several topics, a numbered list of candidate news articles (title, source, and URL).

For EACH topic that has at least one candidate, select the SINGLE most \
important, newsworthy, and non-trivial development. Then write a concise, \
neutral, 2-sentence summary of that story in your own words.

Respond with ONLY a raw JSON array (no markdown fences, no commentary, no \
preamble). Each element must be an object with exactly these keys:
- "topic": string, the topic name exactly as given
- "title": string, the original headline of the article you selected
- "url": string, the exact URL of the article you selected (copy verbatim)
- "source": string, the source/publisher name of the article you selected
- "summary": string, your 2-sentence summary

If a topic has zero candidates, omit it entirely from the array. Do not \
invent articles, URLs, or facts that are not present in the candidate list."""


def _build_user_prompt(candidates_by_topic: Dict[str, List[Article]]) -> str:
    """
    Format the candidate articles into a structured text prompt for the LLM.

    Args:
        candidates_by_topic: Mapping of topic -> list of candidate Articles.

    Returns:
        A formatted string listing all topics and their numbered candidates.
    """
    lines: List[str] = []
    for topic, articles in candidates_by_topic.items():
        lines.append(f"## Topic: {topic}")
        if not articles:
            lines.append("(no candidates)")
            continue
        for idx, article in enumerate(articles, start=1):
            lines.append(
                f"{idx}. Title: {article.title}\n   Source: {article.source}\n   URL: {article.url}"
            )
        lines.append("")
    return "\n".join(lines)


def _extract_json(raw_text: str) -> str:
    """
    Strip common markdown code-fence wrappers from an LLM response so the
    remaining text is parseable JSON.

    Args:
        raw_text: The raw text returned by the LLM.

    Returns:
        A cleaned string expected to contain only JSON.
    """
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        parts = cleaned.split("```")
        cleaned = parts[1] if len(parts) >= 2 else cleaned
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    return cleaned.strip()


def curate_top_stories(candidates_by_topic: Dict[str, List[Article]]) -> List[CuratedStory]:
    """
    Ask Gemini to select and summarize the top story for each topic.

    Args:
        candidates_by_topic: Mapping of topic -> list of candidate Articles.
            Topics with an empty candidate list are simply skipped.

    Returns:
        A list of CuratedStory dicts, at most one per topic that had
        candidates.

    Raises:
        RuntimeError: If the API call fails or the response cannot be
            parsed into valid JSON matching the expected schema.
    """
    topics_with_candidates = {t: a for t, a in candidates_by_topic.items() if a}
    if not topics_with_candidates:
        return []

    user_prompt = _build_user_prompt(topics_with_candidates)

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_PROMPT,
                max_output_tokens=LLM_MAX_TOKENS,
                response_mime_type="application/json",
                temperature=0.3,
            ),
        )
    except Exception as exc:
        raise RuntimeError(f"Gemini API call failed: {exc}") from exc

    raw_text = (getattr(response, "text", None) or "").strip()

    if not raw_text:
        raise RuntimeError("Gemini API returned an empty response.")

    cleaned_json = _extract_json(raw_text)

    try:
        parsed = json.loads(cleaned_json)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Failed to parse LLM response as JSON: {exc}\nRaw response: {raw_text}"
        ) from exc

    if not isinstance(parsed, list):
        raise RuntimeError(f"Expected LLM response to be a JSON array, got: {type(parsed)}")

    curated: List[CuratedStory] = []
    required_keys = {"topic", "title", "url", "source", "summary"}

    for item in parsed:
        if not isinstance(item, dict) or not required_keys.issubset(item.keys()):
            raise RuntimeError(f"Malformed curated story object in LLM response: {item}")
        curated.append(
            CuratedStory(
                topic=str(item["topic"]),
                title=str(item["title"]),
                url=str(item["url"]),
                source=str(item["source"]),
                summary=str(item["summary"]),
            )
        )

    return curated
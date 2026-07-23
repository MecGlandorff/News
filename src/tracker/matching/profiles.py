from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date

from src.tracker.matching.constants import GENERIC_EVENT_TOKENS, LABEL_STOPWORDS


WORD_RE = re.compile(r"[a-z0-9]+")
NUMBER_RE = re.compile(r"\b\d+(?:[.,]\d+)?%?\b")
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
PROFILE_TEXT_LIMIT = 6_000
PROFILE_STOPWORDS = {
    "about",
    "after",
    "amid",
    "before",
    "day",
    "days",
    "had",
    "has",
    "have",
    "its",
    "latest",
    "live",
    "new",
    "news",
    "people",
    "report",
    "reports",
    "say",
    "says",
    "that",
    "their",
    "this",
    "under",
    "will",
    "year",
    "years",
}


def normalize_text(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(character for character in text if not unicodedata.combining(character))
    return " ".join(text.casefold().split())


def normalized_tokens(value: object) -> tuple[str, ...]:
    return tuple(WORD_RE.findall(normalize_text(value)))


def content_tokens(value: object) -> frozenset[str]:
    return frozenset(
        token
        for token in normalized_tokens(value)
        if len(token) > 1
        and token not in LABEL_STOPWORDS
        and token not in PROFILE_STOPWORDS
    )


def distinctive_tokens(value: object) -> frozenset[str]:
    return frozenset(
        token
        for token in content_tokens(value)
        if token not in GENERIC_EVENT_TOKENS and not token.isdigit()
    )


def content_phrases(values: Iterable[object]) -> frozenset[str]:
    phrases: set[str] = set()
    for value in values:
        sequence = [
            token
            for token in normalized_tokens(value)
            if len(token) > 1
            and token not in LABEL_STOPWORDS
            and token not in PROFILE_STOPWORDS
            and token not in GENERIC_EVENT_TOKENS
            and not token.isdigit()
        ]
        for width in (2, 3):
            for index in range(0, len(sequence) - width + 1):
                phrases.add(" ".join(sequence[index:index + width]))
    return frozenset(phrases)


def numeric_tokens(values: Iterable[object]) -> frozenset[str]:
    return frozenset(
        match.group(0).replace(",", ".")
        for value in values
        for match in NUMBER_RE.finditer(normalize_text(value))
    )


def year_tokens(values: Iterable[object]) -> frozenset[str]:
    return frozenset(
        match.group(0)
        for value in values
        for match in YEAR_RE.finditer(normalize_text(value))
    )


def _clean_values(values: Iterable[object]) -> tuple[str, ...]:
    return tuple(
        text
        for value in values
        if (text := " ".join(str(value or "").split()))
    )


def _profile_date(values: Iterable[object]) -> str:
    valid = []
    for value in values:
        text = str(value or "")[:10]
        try:
            valid.append(date.fromisoformat(text).isoformat())
        except ValueError:
            continue
    return max(valid, default="")


def _mapping_items(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _occurrence_id(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


@dataclass(frozen=True)
class MatchProfile:
    profile_id: str
    label: str
    theme: str
    date: str
    article_ids: tuple[str, ...]
    occurrence_ids: tuple[int, ...]
    titles: tuple[str, ...]
    descriptions: tuple[str, ...]
    summaries: tuple[str, ...]
    urls: frozenset[str]
    tokens: frozenset[str]
    distinctive: frozenset[str]
    phrases: frozenset[str]
    numbers: frozenset[str]
    years: frozenset[str]
    importance: float

    def evidence_text(self, limit: int = PROFILE_TEXT_LIMIT) -> str:
        parts = _clean_values(
            (
                self.label,
                *self.titles,
                *self.descriptions,
                *self.summaries,
            )
        )
        text = "\n".join(parts)
        return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0]


def profile_from_articles(
    articles: Iterable[Mapping[str, object]],
    *,
    label: str | None = None,
    profile_id: str | None = None,
) -> MatchProfile:
    items = list(articles)
    labels = _clean_values(item.get("story_label") for item in items)
    resolved_label = str(label or (labels[0] if labels else "")).strip()
    titles = _clean_values(item.get("title") for item in items)
    descriptions = _clean_values(item.get("description") for item in items)
    evidence_values = (resolved_label, *labels, *titles, *descriptions)
    article_ids = tuple(str(item.get("id") or "") for item in items)
    occurrence_ids = tuple(
        value
        for item in items
        if (value := _occurrence_id(item.get("occurrence_id"))) is not None
    )
    themes = _clean_values(item.get("theme") for item in items)
    importance_values = [
        float(importance)
        for item in items
        if isinstance((importance := item.get("importance")), (int, float))
    ]
    resolved_id = profile_id or "current:" + ",".join(
        str(value)
        for value in (occurrence_ids or article_ids)
    )
    return MatchProfile(
        profile_id=resolved_id,
        label=resolved_label,
        theme=themes[0] if themes else "",
        date=_profile_date(item.get("published_at") for item in items),
        article_ids=article_ids,
        occurrence_ids=occurrence_ids,
        titles=titles,
        descriptions=descriptions,
        summaries=(),
        urls=frozenset(
            normalize_text(item.get("url"))
            for item in items
            if item.get("url")
        ),
        tokens=content_tokens(" ".join(str(value or "") for value in evidence_values)),
        distinctive=distinctive_tokens(
            " ".join(str(value or "") for value in evidence_values)
        ),
        phrases=content_phrases(evidence_values),
        numbers=numeric_tokens(evidence_values),
        years=year_tokens(evidence_values),
        importance=max(importance_values, default=0.0),
    )


def profile_from_story(label: str, story: Mapping[str, object]) -> MatchProfile:
    recent_articles = _mapping_items(story.get("recent_articles"))
    titles = _clean_values(article.get("title") for article in recent_articles)
    descriptions = _clean_values(
        article.get("description") for article in recent_articles
    )
    summaries = _clean_values(
        (
            story.get("summary"),
            story.get("delta_summary"),
            *(
                development.get("label")
                for development in _mapping_items(story.get("recent_developments"))
            ),
        )
    )
    evidence_values = (
        label,
        story.get("canonical_label"),
        story.get("arc_label"),
        story.get("parent_label"),
        *titles,
        *descriptions,
        *summaries,
    )
    story_id = story.get("story_id")
    return MatchProfile(
        profile_id=f"story:{story_id if story_id is not None else label}",
        label=str(story.get("canonical_label") or label),
        theme=str(story.get("theme") or ""),
        date=str(story.get("last_seen") or ""),
        article_ids=(),
        occurrence_ids=(),
        titles=titles,
        descriptions=descriptions,
        summaries=summaries,
        urls=frozenset(
            normalize_text(article.get("url"))
            for article in recent_articles
            if article.get("url")
        ),
        tokens=content_tokens(" ".join(str(value or "") for value in evidence_values)),
        distinctive=distinctive_tokens(
            " ".join(str(value or "") for value in evidence_values)
        ),
        phrases=content_phrases(evidence_values),
        numbers=numeric_tokens(evidence_values),
        years=year_tokens(evidence_values),
        importance=0.0,
    )


def profile_from_arc(arc: Mapping[str, object]) -> MatchProfile:
    stories = _mapping_items(arc.get("recent_stories"))
    titles = _clean_values(story.get("canonical_label") for story in stories)
    summaries = _clean_values(
        value
        for story in stories
        for value in (
            story.get("summary"),
            story.get("delta_summary"),
            story.get("parent_label"),
        )
    )
    label = str(arc.get("canonical_label") or "")
    evidence_values = (label, *titles, *summaries)
    return MatchProfile(
        profile_id=f"arc:{arc.get('arc_id')}",
        label=label,
        theme=str(arc.get("theme") or ""),
        date=str(arc.get("last_seen") or ""),
        article_ids=(),
        occurrence_ids=(),
        titles=titles,
        descriptions=(),
        summaries=summaries,
        urls=frozenset(),
        tokens=content_tokens(" ".join(str(value or "") for value in evidence_values)),
        distinctive=distinctive_tokens(
            " ".join(str(value or "") for value in evidence_values)
        ),
        phrases=content_phrases(evidence_values),
        numbers=numeric_tokens(evidence_values),
        years=year_tokens(evidence_values),
        importance=0.0,
    )

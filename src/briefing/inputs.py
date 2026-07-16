from datetime import datetime, timezone

from src.article_dates import editorial_date, parse_reported_at
from src.config import (
    BRIEFING_ARTICLES_PER_STORY,
    BRIEFING_DESCRIPTION_CHAR_LIMIT,
    BRIEFING_TITLE_CHAR_LIMIT,
)


def latest_reported_at(articles):
    parsed = [parse_reported_at(article.get("published_at")) for article in articles]
    parsed = [value for value in parsed if value]
    if not parsed:
        return "unknown time"
    return max(parsed).strftime("%Y-%m-%d %H:%M UTC")


def claims_for_prompt(story):
    if story.get("claims_for_prompt") is not None:
        return story["claims_for_prompt"]
    from src.claims import get_claims_for_story
    current_date = story_editorial_date(story)
    article_by_id = {str(article.get("id")): article for article in story.get("articles", [])}
    article_by_occurrence = {
        str(article.get("occurrence_id")): article
        for article in story.get("articles", [])
        if article.get("occurrence_id") is not None
    }
    claims = []
    saved_claims = get_claims_for_story(
        story.get("story_id"),
        as_of_date=current_date,
        history_days=7,
    )
    for claim in saved_claims[:12]:
        article = article_by_occurrence.get(str(claim.get("occurrence_id"))) or article_by_id.get(
            str(claim.get("article_id")),
            {},
        )
        claim_date = str(claim.get("editorial_date") or "")
        is_current = bool(
            (current_date and claim_date == current_date)
            or (
                not claim_date
                and (
                    str(claim.get("occurrence_id")) in article_by_occurrence
                    or str(claim.get("article_id")) in article_by_id
                )
            )
        )
        claims.append({
            "article_id": claim.get("article_id"),
            "occurrence_id": claim.get("occurrence_id"),
            "editorial_date": claim_date,
            "evidence_role": "current" if is_current else "historical_context",
            "is_current": is_current,
            "source_id": claim.get("source_id") or article.get("source_id"),
            "claim_text": claim.get("claim_text", ""),
            "claim_type": claim.get("claim_type", ""),
            "evidence_span": claim.get("evidence_span", ""),
            "confidence": claim.get("confidence"),
            "source": claim.get("source") or article.get("source", ""),
            "article_title": claim.get("article_title") or article.get("title", ""),
            "url": claim.get("url") or article.get("url", ""),
        })
    return claims


def story_editorial_date(story):
    explicit = [
        str(article.get("editorial_date"))
        for article in story.get("articles", [])
        if article.get("editorial_date")
    ]
    if explicit:
        return max(explicit)
    parsed = [editorial_date(article.get("published_at")) for article in story.get("articles", [])]
    parsed = [value for value in parsed if value is not None]
    return max(parsed).isoformat() if parsed else None


def bounded_text(value, limit):
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip() + "…"


def articles_for_prompt(story):
    articles = sorted(
        story.get("articles", []),
        key=lambda value: parse_reported_at(value.get("published_at"))
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )[:BRIEFING_ARTICLES_PER_STORY]
    return [
        {
            "source_id": article.get("source_id"),
            "source": article.get("source", ""),
            "title": bounded_text(article.get("title"), BRIEFING_TITLE_CHAR_LIMIT),
            "description": bounded_text(
                article.get("description"),
                BRIEFING_DESCRIPTION_CHAR_LIMIT,
            ),
            "reported_at": article.get("published_at", ""),
            "url": article.get("url", ""),
        }
        for article in articles
    ]

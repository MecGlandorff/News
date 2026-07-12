import hashlib
import re

from src.config import CLAIMS_CONTENT_CHAR_LIMIT


def _strip_html(text):
    return re.sub(r"<[^>]+>", " ", text or "").strip()


def _clean_article_part(text):
    return re.sub(r"\s+", " ", _strip_html(text)).strip()


def article_claim_content(article, include_full_text=True):
    title = _clean_article_part(article.get("title"))
    description = _clean_article_part(article.get("description"))
    parts = [title, description]
    full_text = _clean_article_part(article.get("text")) if include_full_text else ""
    if include_full_text and full_text:
        parts.append(full_text)
    return "\n\n".join(part for part in parts if part)


def _article_content(article):
    content = article_claim_content(article, include_full_text=True)
    if len(content) <= CLAIMS_CONTENT_CHAR_LIMIT:
        return content, False
    bounded = content[:CLAIMS_CONTENT_CHAR_LIMIT].rsplit(" ", 1)[0].rstrip()
    return bounded, True


def _article_content_hash(content):
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _normalize_for_span_match(text):
    return re.sub(r"\s+", " ", text or "").strip().casefold()


def _evidence_in_content(evidence_span, content):
    normalized_span = _normalize_for_span_match(evidence_span)
    if not normalized_span:
        return False
    return normalized_span in _normalize_for_span_match(content)

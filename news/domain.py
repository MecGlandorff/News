"""Checks at the two trust boundaries: captured sources and model decisions."""

import copy
import hashlib
import json
import re
from datetime import date, datetime
from html import escape
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from jsonschema import ValidationError, validate

TASKS = Path(__file__).parent / "tasks"
TIMEZONE = ZoneInfo("Europe/Brussels")
MAX_ARTICLES = 50
MAX_INPUT_CHARS = 120_000


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def valid_day(value: str) -> str:
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError("day must be YYYY-MM-DD")
    return value


def valid_url(value: str) -> str:
    if not isinstance(value, str) or any(c.isspace() or ord(c) < 32 for c in value):
        raise ValueError("URL must be an absolute HTTP(S) URL without whitespace")
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("URL must be an absolute HTTP(S) URL without credentials")
    _ = parsed.port  # Reject malformed ports before network or Markdown rendering.
    return value


def _text(value: object, field: str, limit: int) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{field} must be nonempty text of at most {limit} characters")
    if any(ord(c) < 32 and c not in "\n\r\t" for c in value):
        raise ValueError(f"{field} contains control characters")


def validate_input(value: object) -> dict:
    """Accept one bounded, dated snapshot. Never silently truncate source text."""
    if not isinstance(value, dict) or set(value) != {"day", "articles"}:
        raise ValueError("input must contain exactly day and articles")
    day = valid_day(value["day"])
    articles = value["articles"]
    if not isinstance(articles, list) or not 1 <= len(articles) <= MAX_ARTICLES:
        raise ValueError(f"input must contain 1–{MAX_ARTICLES} articles")
    ids, urls = set(), set()
    fields = {"id", "source", "url", "published_at", "title", "text"}
    for article in articles:
        if not isinstance(article, dict) or set(article) != fields:
            raise ValueError(f"each article must contain exactly {sorted(fields)}")
        for key, limit in (("id", 100), ("source", 160), ("title", 500), ("text", 20_000)):
            _text(article[key], key, limit)
        valid_url(article["url"])
        if article["id"] in ids or article["url"] in urls:
            raise ValueError("article IDs and URLs must be unique within a snapshot")
        ids.add(article["id"])
        urls.add(valid_url(article["url"]))
        if not isinstance(article["published_at"], str):
            raise ValueError("published_at must be a timezone-aware ISO timestamp")
        published = datetime.fromisoformat(article["published_at"].replace("Z", "+00:00"))
        if published.tzinfo is None:
            raise ValueError("published_at must include a timezone")
        if published.astimezone(TIMEZONE).date().isoformat() > day:
            raise ValueError("article publication cannot be after the snapshot day")
    if len(canonical(value)) > MAX_INPUT_CHARS:
        raise ValueError(f"snapshot exceeds {MAX_INPUT_CHARS} characters; use a smaller batch")
    result = copy.deepcopy(value)
    result["articles"].sort(key=lambda article: article["id"])
    return result


def validate_schema(task: str, result: object) -> None:
    schema = json.loads((TASKS / f"{task}.schema.json").read_text())
    try:
        validate(result, schema)
    except ValidationError as exc:
        raise ValueError(f"{task} output does not match its schema: {exc.message}") from exc


def _markdown(text: str) -> str:
    return re.sub(r"([\\`*{}\[\]()#!|_~])", r"\\\1", escape(text, quote=False))

"""Bounded RSS/Atom snapshots. Network fetching is separate from AI processing."""

import hashlib
import json
import math
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from http.client import HTTPException, IncompleteRead
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from news.domain import TIMEZONE, digest, valid_day, valid_url, validate_input

MAX_FEED_BYTES = 2_000_000


class _NoDTD(ET.TreeBuilder):
    def doctype(self, name, public_id, system_id):
        raise ValueError("feed DTD/entity declarations are not supported")


class _PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        elif not self.hidden:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        elif not self.hidden:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain_text(value: str) -> str:
    parser = _PlainText()
    parser.feed(value)
    return re.sub(r"\s+", " ", "".join(parser.parts)).strip()


def normalize_url(value: str) -> str:
    valid_url(value)
    parts = urlsplit(value)
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}
    ]
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path, urlencode(sorted(query)), "")
    )


def _child_text(entry: ET.Element, *names: str) -> str:
    for name in names:
        for child in entry:
            if child.tag.rsplit("}", 1)[-1] == name:
                if len(child):
                    return (child.text or "") + "".join(
                        ET.tostring(node, encoding="unicode") for node in child
                    )
                return "".join(child.itertext()).strip()
    return ""


def _entries(data: bytes) -> list[ET.Element]:
    if len(data) > MAX_FEED_BYTES:
        raise ValueError("feed exceeds 2 MB")
    root = ET.fromstring(data, parser=ET.XMLParser(target=_NoDTD()))
    if root.tag.rsplit("}", 1)[-1] not in {"rss", "feed", "RDF"}:
        raise ValueError("response is not an RSS or Atom feed")
    return [entry for entry in root.iter() if entry.tag.rsplit("}", 1)[-1] in {"item", "entry"}]


def _article(entry: ET.Element, source: str, base_url: str) -> dict:
    title = plain_text(_child_text(entry, "title"))
    body = plain_text(_child_text(entry, "encoded", "content", "description", "summary"))
    link = _child_text(entry, "link")
    if not link:
        link = next(
            (
                node.get("href", "")
                for node in entry
                if node.tag.rsplit("}", 1)[-1] == "link"
                and node.get("rel", "alternate") == "alternate"
            ),
            "",
        )
    url = normalize_url(urljoin(base_url, link)) if link else ""
    raw_date = _child_text(entry, "pubDate", "published", "date", "updated")
    try:
        timestamp = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
    except ValueError:
        timestamp = parsedate_to_datetime(raw_date)
    if not title or not body or not url or timestamp.tzinfo is None:
        raise ValueError("item lacks title, body, URL or timezone-aware publication time")
    return {
        "id": hashlib.sha256(url.encode()).hexdigest()[:24],
        "source": source,
        "url": url,
        "title": title,
        "text": body,
        "published_at": timestamp.astimezone(timezone.utc).isoformat(),
    }


def parse_feed(data: bytes, source: str, base_url: str, day: str, limit: int) -> tuple[list, dict]:
    valid_day(day)
    articles, seen = [], set()
    stats = {"invalid": 0, "outside_day": 0, "duplicates": 0, "over_limit": 0}
    for entry in _entries(data):
        try:
            article = _article(entry, source, base_url)
            timestamp = datetime.fromisoformat(article["published_at"])
            if timestamp.astimezone(TIMEZONE).date().isoformat() != day:
                stats["outside_day"] += 1
                continue
            if article["url"] in seen:
                stats["duplicates"] += 1
                continue
            seen.add(article["url"])
            if len(articles) >= limit:
                stats["over_limit"] += 1
                continue
            validate_input({"day": day, "articles": [article]})
            articles.append(article)
        except (ValueError, TypeError, OverflowError):
            stats["invalid"] += 1
    return articles, stats


def _validate_config(feeds: list) -> None:
    if not isinstance(feeds, list) or not 1 <= len(feeds) <= 10:
        raise ValueError("feeds must be a list of 1–10 {name, url} objects")
    for feed in feeds:
        if not isinstance(feed, dict) or set(feed) != {"name", "url"}:
            raise ValueError("each feed needs exactly name and url")
        if not isinstance(feed["name"], str) or not feed["name"].strip():
            raise ValueError("feed name must be nonempty")
        valid_url(feed["url"])


def fetch(
    feeds: list, day: str, *, max_per_feed: int = 10, timeout: float = 20
) -> tuple[dict, dict]:
    valid_day(day)
    _validate_config(feeds)
    if not 1 <= max_per_feed <= 50:
        raise ValueError("max_per_feed must be between 1 and 50")
    articles, seen, report = [], set(), {"feeds": [], "cross_feed_duplicates": 0}
    for feed in feeds:
        request = Request(feed["url"], headers={"User-Agent": "NewsMemory/0.1 (RSS reader)"})
        # A failed feed makes this command fail; never quietly publish a partial snapshot.
        with urlopen(request, timeout=timeout) as response:
            data = response.read(MAX_FEED_BYTES + 1)
        parsed, stats = parse_feed(data, feed["name"], feed["url"], day, max_per_feed)
        report["feeds"].append(dict(feed, **stats, accepted=len(parsed)))
        for article in parsed:
            if article["url"] in seen:
                report["cross_feed_duplicates"] += 1
                continue
            seen.add(article["url"])
            articles.append(article)
    snapshot = validate_input({"day": day, "articles": articles})
    return snapshot, report


def collect(
    config: list, day: str, directory: Path, *, timeout: float = 20
) -> tuple[list[dict], dict]:
    """Capture exposed feed versions published on or before a Brussels capture day.

    The caller provides an existing empty directory. Raw bodies and collection.json
    are audit artifacts; filesystem failures propagate. Feed failures are explicit
    report entries, while empty parsed feeds succeed. Status describes feed coverage,
    not the absence of invalid items or proof of comprehensive news coverage.

    Articles require the same fields/body as fetch, but have no age/count cutoff.
    Full-field duplicates collapse; different versions of a URL retain the same ID.
    Order is publication/source/URL/digest, not inferred occurrence chronology. The
    caller must batch same-URL versions separately and handle cross-poll transitions.
    """
    valid_day(day)
    _validate_config(config)
    for feed in config:
        if len(feed["name"]) > 160 or any(ord(c) < 32 and c not in "\n\r\t" for c in feed["name"]):
            raise ValueError("feed name must be valid source text of at most 160 characters")
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(timeout)
        or timeout <= 0
    ):
        raise ValueError("timeout must be finite and positive")
    directory = Path(directory)
    if not directory.is_dir():
        raise NotADirectoryError(directory)
    if any(directory.iterdir()):
        raise ValueError("capture directory must be empty")
    articles, seen = [], set()
    report = {
        "day": day,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "status": "collecting",
        "planned_feeds": len(config),
        "accepted": 0,
        "invalid": 0,
        "future": 0,
        "duplicates": 0,
        "feed_errors": 0,
        "feeds": [],
    }
    report_path = directory / "collection.json"
    with report_path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    for number, feed in enumerate(config, 1):
        entry = dict(
            feed,
            status="error",
            retrieved_at=None,
            raw_file=None,
            raw_sha256=None,
            raw_bytes=0,
            raw_complete=False,
            declared_bytes=None,
            error=None,
            items=None,
            accepted=0,
            invalid=0,
            future=0,
            duplicates=0,
        )
        response, data = None, None
        try:
            request = Request(feed["url"], headers={"User-Agent": "NewsMemory/0.1 (RSS reader)"})
            response = urlopen(request, timeout=timeout)
        except HTTPError as exc:
            response = exc  # Retain an HTTP error's response body, without parsing it as a feed.
            entry["error"] = f"{type(exc).__name__}: {exc}"
        except (OSError, HTTPException, ValueError, UnicodeError) as exc:
            entry["error"] = f"{type(exc).__name__}: {exc}"
        if response is not None:
            try:
                with response:
                    length = getattr(response, "headers", {}).get("Content-Length")
                    if isinstance(length, str) and length.isdecimal():
                        entry["declared_bytes"] = int(length)
                    data = response.read(MAX_FEED_BYTES + 1)
                entry["raw_complete"] = len(data) <= MAX_FEED_BYTES
                if entry["declared_bytes"] is not None and len(data) < entry["declared_bytes"]:
                    entry["raw_complete"] = False
                    if len(data) <= MAX_FEED_BYTES and entry["error"] is None:
                        entry["error"] = "IncompleteRead: body is shorter than Content-Length"
            except (OSError, HTTPException, ValueError) as exc:
                if isinstance(exc, IncompleteRead):
                    data = exc.partial[: MAX_FEED_BYTES + 1]
                entry["error"] = f"{type(exc).__name__}: {exc}"
            entry["retrieved_at"] = datetime.now(timezone.utc).isoformat()
        # Durable evidence writes are deliberately outside feed-error handling.
        if data is not None:
            filename = f"feed-{number:03d}.xml"
            with (directory / filename).open("xb") as handle:
                handle.write(data)
            entry.update(
                raw_file=filename, raw_sha256=hashlib.sha256(data).hexdigest(), raw_bytes=len(data)
            )
        if data is not None and entry["error"] is None:
            try:
                items = _entries(data)
            except (ET.ParseError, ValueError, LookupError) as exc:
                entry["error"] = f"{type(exc).__name__}: {exc}"
            else:
                entry["status"], entry["items"] = "ok", len(items)
                for item in items:
                    try:
                        article = _article(item, feed["name"], feed["url"])
                        published_day = (
                            datetime.fromisoformat(article["published_at"])
                            .astimezone(TIMEZONE)
                            .date()
                            .isoformat()
                        )
                        # Validate structure before classifying an otherwise-valid future item.
                        validate_input({"day": published_day, "articles": [article]})
                        if published_day > day:
                            entry["future"] += 1
                            continue
                        version = digest(article)
                        if version in seen:
                            entry["duplicates"] += 1
                            continue
                        seen.add(version)
                        articles.append(article)
                        entry["accepted"] += 1
                    except (ValueError, TypeError, OverflowError):
                        entry["invalid"] += 1
        report["feeds"].append(entry)
        report["feed_errors"] += entry["status"] == "error"
        for key in ("accepted", "invalid", "future", "duplicates"):
            report[key] += entry[key]
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    report["status"] = (
        "complete"
        if not report["feed_errors"]
        else "failed"
        if report["feed_errors"] == len(config)
        else "partial"
    )
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    articles.sort(
        key=lambda article: (
            article["published_at"],
            article["source"],
            article["url"],
            digest(article),
        )
    )
    return articles, report

"""Bounded RSS/Atom snapshots. Network fetching is separate from AI processing."""

import hashlib
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from news.domain import TIMEZONE, valid_day, valid_url, validate_input

MAX_FEED_BYTES = 2_000_000


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
                return "".join(child.itertext()).strip()
    return ""


def parse_feed(data: bytes, source: str, base_url: str, day: str, limit: int) -> tuple[list, dict]:
    valid_day(day)
    if len(data) > MAX_FEED_BYTES:
        raise ValueError("feed exceeds 2 MB")
    if re.search(rb"<!\s*(?:DOCTYPE|ENTITY)", data, re.IGNORECASE):
        raise ValueError("feed DTD/entity declarations are not supported")
    root = ET.fromstring(data)
    if root.tag.rsplit("}", 1)[-1] not in {"rss", "feed", "RDF"}:
        raise ValueError("response is not an RSS or Atom feed")
    articles, seen = [], set()
    stats = {"invalid": 0, "outside_day": 0, "duplicates": 0, "over_limit": 0}
    for entry in root.iter():
        if entry.tag.rsplit("}", 1)[-1] not in {"item", "entry"}:
            continue
        try:
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
            if timestamp.astimezone(TIMEZONE).date().isoformat() != day:
                stats["outside_day"] += 1
                continue
            if url in seen:
                stats["duplicates"] += 1
                continue
            seen.add(url)
            if len(articles) >= limit:
                stats["over_limit"] += 1
                continue
            article = {
                "id": hashlib.sha256(url.encode()).hexdigest()[:24],
                "source": source,
                "url": url,
                "title": title,
                "text": body,
                "published_at": timestamp.astimezone(timezone.utc).isoformat(),
            }
            validate_input({"day": day, "articles": [article]})
            articles.append(article)
        except (ValueError, TypeError, OverflowError):
            stats["invalid"] += 1
    return articles, stats


def fetch(
    feeds: list, day: str, *, max_per_feed: int = 10, timeout: float = 20
) -> tuple[dict, dict]:
    valid_day(day)
    if not isinstance(feeds, list) or not 1 <= len(feeds) <= 10:
        raise ValueError("feeds must be a list of 1–10 {name, url} objects")
    if not 1 <= max_per_feed <= 50:
        raise ValueError("max_per_feed must be between 1 and 50")
    for feed in feeds:
        if not isinstance(feed, dict) or set(feed) != {"name", "url"}:
            raise ValueError("each feed needs exactly name and url")
        if not isinstance(feed["name"], str) or not feed["name"].strip():
            raise ValueError("feed name must be nonempty")
        valid_url(feed["url"])
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

import hashlib
import json
from http.client import IncompleteRead
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError
from xml.sax.saxutils import escape

import pytest

from news import feeds


def rss(*items, encoding="utf-8", doctype=""):
    body = "".join(
        "<item>" + "".join(f"<{k}>{escape(v)}</{k}>" for k, v in item.items()) + "</item>"
        for item in items
    )
    return (
        f'<?xml version="1.0" encoding="{encoding}"?>{doctype}<rss><channel>{body}</channel></rss>'
    ).encode(encoding)


@pytest.fixture
def item():
    return {
        "title": "Brook bridge closes",
        "link": "https://example.test/bridge?utm_source=rss",
        "description": "<p>The bridge closed.</p><p>A truck hit it.</p>",
        "pubDate": "Thu, 01 Oct 2026 08:00:00 GMT",
    }


def test_rss_capture_retains_paragraph_boundaries_and_normalizes_urls(item):
    articles, stats = feeds.parse_feed(
        rss(item), "Source", "https://example.test/rss", "2026-10-01", 10
    )
    assert articles[0]["text"] == "The bridge closed. A truck hit it."
    assert articles[0]["url"] == "https://example.test/bridge"
    assert articles[0]["published_at"] == "2026-10-01T08:00:00+00:00"
    assert sum(stats.values()) == 0


def test_atom_xhtml_does_not_join_words():
    data = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry>
    <title>Bridge report</title><link href="https://example.test/a"/>
    <published>2026-10-01T08:00:00Z</published><content type="xhtml">
    <div xmlns="http://www.w3.org/1999/xhtml"><p>Bridge closed.</p><p>Road diverted.</p></div>
    </content></entry></feed>"""
    articles, _ = feeds.parse_feed(data, "Source", "https://example.test", "2026-10-01", 5)
    assert articles[0]["text"] == "Bridge closed. Road diverted."


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "utf-16-le", "utf-16-be"])
def test_dtd_is_rejected_independent_of_encoding(encoding):
    declaration = encoding.replace("-le", "le").replace("-be", "be")
    xml = f'''<?xml version="1.0" encoding="{declaration}"?>
    <!DOCTYPE rss [<!ENTITY extra "injected entity">]>
    <rss><channel><item><title>Example</title><link>https://example.test/a</link>
    <description>&extra;</description><pubDate>Thu, 01 Oct 2026 08:00:00 GMT</pubDate>
    </item></channel></rss>'''.encode(encoding)
    with pytest.raises(ValueError, match="DTD"):
        feeds.parse_feed(xml, "Source", "https://example.test", "2026-10-01", 5)


@pytest.mark.parametrize(
    "field,value",
    [
        ("link", "javascript:alert(1)"),
        ("link", ""),
        ("description", ""),
        ("title", ""),
        ("pubDate", "bad date"),
        ("pubDate", "2026-10-01T08:00:00"),
    ],
)
def test_bad_item_is_counted_not_assigned_an_invented_date(item, field, value):
    item[field] = value
    articles, stats = feeds.parse_feed(rss(item), "Source", "https://example.test", "2026-10-01", 5)
    assert not articles
    assert stats["invalid"] == 1


def test_feed_duplicates_limits_and_day_boundary_are_counted(item):
    next_item = dict(item, link="https://example.test/next")
    night_item = dict(item, link="https://example.test/night", pubDate="2026-10-01T23:00:00Z")
    articles, stats = feeds.parse_feed(
        rss(item, item, next_item, night_item), "Source", "https://example.test", "2026-10-01", 1
    )
    assert len(articles) == 1
    assert stats == {"duplicates": 1, "over_limit": 1, "outside_day": 1, "invalid": 0}


def test_plain_text_removes_scripts_without_removing_evidence():
    assert (
        feeds.plain_text("Before <script>bad()</script><style>bad</style><b>after</b>")
        == "Before after"
    )


def test_feed_size_is_bounded():
    with pytest.raises(ValueError, match="2 MB"):
        feeds.parse_feed(
            b"x" * (feeds.MAX_FEED_BYTES + 1), "s", "https://example.test", "2026-10-01", 1
        )


def test_html_response_is_not_silently_accepted():
    with pytest.raises(ValueError, match="not an RSS"):
        feeds.parse_feed(
            b"<html><body>Paywall</body></html>", "s", "https://example.test", "2026-10-01", 1
        )


def test_fetch_deduplicates_across_feeds(item, monkeypatch):
    monkeypatch.setattr(feeds, "urlopen", lambda *args, **kwargs: BytesIO(rss(item)))
    snapshot, report = feeds.fetch(
        [
            {"name": "A", "url": "https://example.test/rss-a"},
            {"name": "B", "url": "https://example.test/rss-b"},
        ],
        "2026-10-01",
    )
    assert len(snapshot["articles"]) == 1
    assert report["cross_feed_duplicates"] == 1


def test_failed_feed_never_returns_a_partial_snapshot(item, monkeypatch):
    calls = []

    def network(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise URLError("unavailable")
        return BytesIO(rss(item))

    monkeypatch.setattr(feeds, "urlopen", network)
    with pytest.raises(URLError):
        feeds.fetch(
            [
                {"name": "A", "url": "https://example.test/rss-a"},
                {"name": "B", "url": "https://example.test/rss-b"},
            ],
            "2026-10-01",
        )


@pytest.mark.parametrize(
    "config",
    [
        [],
        {},
        [{"url": "https://example.test"}],
        [{"name": "", "url": "https://example.test"}],
        [{"name": "A", "url": "file:///tmp/a"}],
    ],
)
def test_bad_config_rejected_before_network(config, monkeypatch):
    monkeypatch.setattr(feeds, "urlopen", lambda *args, **kwargs: pytest.fail("network used"))
    with pytest.raises(ValueError):
        feeds.fetch(config, "2026-10-01")


def test_collect_keeps_old_items_and_has_no_per_feed_article_limit(item, monkeypatch, tmp_path):
    exposed = [
        dict(item, link=f"https://example.test/{number:03d}", pubDate="2020-01-01T08:00:00Z")
        for number in reversed(range(75))
    ]
    data = rss(*exposed)
    monkeypatch.setattr(feeds, "urlopen", lambda *a, **kw: BytesIO(data))
    articles, report = feeds.collect(
        [{"name": "Source", "url": "https://example.test/rss"}], "2026-10-01", tmp_path
    )
    assert len(articles) == 75
    assert articles[0]["url"] == "https://example.test/000"
    assert {a["published_at"] for a in articles} == {"2020-01-01T08:00:00+00:00"}
    assert report["accepted"] == report["feeds"][0]["items"] == 75
    assert report["status"] == "complete"
    assert json.loads((tmp_path / "collection.json").read_text()) == report
    assert report["started_at"] <= report["feeds"][0]["retrieved_at"] <= report["finished_at"]


def test_collect_saves_exact_bytes_before_parsing(item, monkeypatch, tmp_path):
    data = rss(dict(item, description="Café remains open."), encoding="utf-16")
    original = feeds._entries

    def parse(raw):
        assert raw == data == (tmp_path / "feed-001.xml").read_bytes()
        return original(raw)

    monkeypatch.setattr(feeds, "_entries", parse)
    monkeypatch.setattr(feeds, "urlopen", lambda *a, **kw: BytesIO(data))
    articles, report = feeds.collect(
        [{"name": "Source", "url": "https://example.test/rss"}], "2026-10-01", tmp_path
    )
    assert articles[0]["text"] == "Café remains open."
    assert report["feeds"][0]["raw_sha256"] == hashlib.sha256(data).hexdigest()
    assert report["feeds"][0]["raw_bytes"] == len(data)
    assert report["feeds"][0]["raw_complete"] is True


def test_collect_validates_items_and_uses_brussels_future_day(item, monkeypatch, tmp_path):
    data = rss(
        item,
        dict(item, link="https://example.test/old", pubDate="2026-09-01T08:00:00Z"),
        dict(item, link="https://example.test/future", pubDate="2026-10-01T23:00:00Z"),
        dict(item, title="x" * 501),
        dict(item, description="x" * 20_001),
        dict(item, description=""),
        dict(item, pubDate="not a date"),
        dict(item, pubDate="2026-10-01T08:00:00"),
    )
    monkeypatch.setattr(feeds, "urlopen", lambda *a, **kw: BytesIO(data))
    articles, report = feeds.collect(
        [{"name": "Source", "url": "https://example.test/rss"}], "2026-10-01", tmp_path
    )
    assert len(articles) == report["accepted"] == 2
    assert report["future"] == 1
    assert report["invalid"] == 5
    assert report["duplicates"] == 0
    entry = report["feeds"][0]
    assert entry["items"] == sum(entry[k] for k in ("accepted", "invalid", "future", "duplicates"))
    # The default fetch path retains its exact-day policy and item limits.
    snapshot, _ = feeds.fetch([{"name": "Source", "url": "https://example.test/rss"}], "2026-10-01")
    assert len(snapshot["articles"]) == 1


def test_collect_full_version_dedup_preserves_revisions_and_is_deterministic(
    item, monkeypatch, tmp_path
):
    revision = dict(item, description="The bridge reopened.")
    responses = {
        "https://example.test/rss-a": rss(item, item, revision),
        "https://example.test/rss-b": rss(revision, item),
    }
    monkeypatch.setattr(
        feeds, "urlopen", lambda request, **kw: BytesIO(responses[request.full_url])
    )
    config = [{"name": "Source", "url": url} for url in responses]
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    articles, report = feeds.collect(config, "2026-10-01", first)
    repeated, reverse_report = feeds.collect(list(reversed(config)), "2026-10-01", second)
    assert repeated == articles
    assert len(articles) == 2
    assert len({a["id"] for a in articles}) == len({a["url"] for a in articles}) == 1
    assert {a["text"] for a in articles} == {
        "The bridge closed. A truck hit it.",
        "The bridge reopened.",
    }
    assert report["duplicates"] == reverse_report["duplicates"] == 3
    assert report["feeds"][0]["duplicates"] == 1
    assert report["feeds"][1]["duplicates"] == 2


def test_collect_does_not_merge_different_source_attribution(item, monkeypatch, tmp_path):
    monkeypatch.setattr(feeds, "urlopen", lambda *a, **kw: BytesIO(rss(item)))
    articles, report = feeds.collect(
        [
            {"name": "A", "url": "https://example.test/a"},
            {"name": "B", "url": "https://example.test/b"},
        ],
        "2026-10-01",
        tmp_path,
    )
    assert [a["source"] for a in articles] == ["A", "B"]
    assert report["duplicates"] == 0


def test_collect_feed_errors_are_explicit_and_other_sources_continue(item, monkeypatch, tmp_path):
    raw_error = b"Service unavailable"
    raw_html = b"<html>paywall</html>"

    def network(request, **kwargs):
        assert kwargs["timeout"] == 3
        url = request.full_url
        if url.endswith("/http-error"):
            raise HTTPError(url, 503, "Unavailable", {}, BytesIO(raw_error))
        if url.endswith("/network-error"):
            raise URLError("offline")
        return BytesIO(
            raw_html if url.endswith("/html") else rss() if url.endswith("/empty") else rss(item)
        )

    monkeypatch.setattr(feeds, "urlopen", network)
    config = [
        {"name": name, "url": f"https://example.test/{name}"}
        for name in ("http-error", "network-error", "html", "empty", "working")
    ]
    articles, report = feeds.collect(config, "2026-10-01", tmp_path, timeout=3)
    assert len(articles) == 1
    assert report["status"] == "partial"
    assert report["feed_errors"] == 3
    assert [f["status"] for f in report["feeds"]] == ["error", "error", "error", "ok", "ok"]
    assert (tmp_path / "feed-001.xml").read_bytes() == raw_error
    assert report["feeds"][1]["raw_file"] is None
    assert (tmp_path / "feed-003.xml").read_bytes() == raw_html
    assert report["feeds"][3]["items"] == 0
    assert report["feeds"][0]["error"].startswith("HTTPError: HTTP Error 503")
    assert report["feeds"][2]["error"].startswith("ValueError: response is not an RSS")


@pytest.mark.parametrize(
    "data", [b"<rss>", b'<?xml version="1.0" encoding="unknown-encoding"?><rss/>']
)
def test_collect_malformed_feed_retains_evidence_and_reports_failure(data, monkeypatch, tmp_path):
    monkeypatch.setattr(feeds, "urlopen", lambda *a, **kw: BytesIO(data))
    articles, report = feeds.collect(
        [{"name": "Source", "url": "https://example.test/rss"}], "2026-10-01", tmp_path
    )
    assert articles == []
    assert report["status"] == "failed"
    assert report["feeds"][0]["items"] is None
    assert (tmp_path / "feed-001.xml").read_bytes() == data


def test_collect_oversized_response_keeps_bounded_prefix(monkeypatch, tmp_path):
    data = b"x" * (feeds.MAX_FEED_BYTES + 10)
    monkeypatch.setattr(feeds, "urlopen", lambda *a, **kw: BytesIO(data))
    articles, report = feeds.collect(
        [{"name": "Source", "url": "https://example.test/rss"}], "2026-10-01", tmp_path
    )
    assert articles == []
    assert report["feeds"][0]["raw_bytes"] == feeds.MAX_FEED_BYTES + 1
    assert report["feeds"][0]["raw_complete"] is False
    assert "exceeds 2 MB" in report["feeds"][0]["error"]
    assert (tmp_path / "feed-001.xml").read_bytes() == data[: feeds.MAX_FEED_BYTES + 1]


def test_collect_partial_response_is_not_parsed(monkeypatch, tmp_path):
    class Partial(BytesIO):
        def read(self, size):
            raise IncompleteRead(b"<rss>", 100)

    monkeypatch.setattr(feeds, "urlopen", lambda *a, **kw: Partial())
    articles, report = feeds.collect(
        [{"name": "Source", "url": "https://example.test/rss"}], "2026-10-01", tmp_path
    )
    assert articles == []
    assert report["status"] == "failed"
    assert (tmp_path / "feed-001.xml").read_bytes() == b"<rss>"
    assert report["feeds"][0]["raw_complete"] is False
    assert report["feeds"][0]["error"].startswith("IncompleteRead:")


def test_collect_short_declared_body_is_not_accepted(item, monkeypatch, tmp_path):
    data = rss(item)

    class ShortResponse(BytesIO):
        headers = {"Content-Length": str(len(data) + 10)}

    monkeypatch.setattr(feeds, "urlopen", lambda *a, **kw: ShortResponse(data))
    articles, report = feeds.collect(
        [{"name": "Source", "url": "https://example.test/rss"}], "2026-10-01", tmp_path
    )
    assert articles == []
    assert report["status"] == "failed"
    assert (tmp_path / "feed-001.xml").read_bytes() == data
    assert report["feeds"][0]["raw_complete"] is False
    assert report["feeds"][0]["declared_bytes"] == len(data) + 10
    assert report["feeds"][0]["error"].startswith("IncompleteRead:")


def test_collect_accepts_empty_feed_without_changing_fetch(monkeypatch, tmp_path):
    monkeypatch.setattr(feeds, "urlopen", lambda *a, **kw: BytesIO(rss()))
    config = [{"name": "Source", "url": "https://example.test/rss"}]
    articles, report = feeds.collect(config, "2026-10-01", tmp_path)
    assert articles == []
    assert report["status"] == "complete"
    assert report["accepted"] == report["feed_errors"] == 0
    with pytest.raises(ValueError, match="1–50 articles"):
        feeds.fetch(config, "2026-10-01")


@pytest.mark.parametrize(
    "config",
    [
        [],
        {},
        [{"url": "https://example.test"}],
        [{"name": "", "url": "https://example.test"}],
        [{"name": "A", "url": "file:///tmp/a"}],
        [{"name": "x" * 161, "url": "https://example.test"}],
        [{"name": "bad\x00name", "url": "https://example.test"}],
    ],
)
def test_collect_config_rejected_before_network_or_writes(config, monkeypatch, tmp_path):
    monkeypatch.setattr(feeds, "urlopen", lambda *a, **kw: pytest.fail("network used"))
    with pytest.raises(ValueError):
        feeds.collect(config, "2026-10-01", tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan"), True, "20"])
def test_collect_bad_timeout_rejected_before_network(timeout, monkeypatch, tmp_path):
    monkeypatch.setattr(feeds, "urlopen", lambda *a, **kw: pytest.fail("network used"))
    with pytest.raises(ValueError, match="timeout"):
        feeds.collect(
            [{"name": "Source", "url": "https://example.test/rss"}],
            "2026-10-01",
            tmp_path,
            timeout=timeout,
        )
    assert list(tmp_path.iterdir()) == []


def test_collect_requires_unused_existing_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(feeds, "urlopen", lambda *a, **kw: pytest.fail("network used"))
    config = [{"name": "Source", "url": "https://example.test/rss"}]
    with pytest.raises(NotADirectoryError):
        feeds.collect(config, "2026-10-01", tmp_path / "absent")
    (tmp_path / "existing").write_text("preserve")
    with pytest.raises(ValueError, match="empty"):
        feeds.collect(config, "2026-10-01", tmp_path)
    assert (tmp_path / "existing").read_text() == "preserve"


@pytest.mark.parametrize("failure", ["raw", "report"])
def test_collect_filesystem_failure_propagates(item, monkeypatch, tmp_path, failure):
    calls = []

    def network(*args, **kwargs):
        calls.append(1)
        return BytesIO(rss(item))

    original_open, original_write = Path.open, Path.write_text

    def open_file(path, *args, **kwargs):
        if failure == "raw" and path.name == "feed-001.xml":
            raise PermissionError("disk cannot retain evidence")
        return original_open(path, *args, **kwargs)

    def write_file(path, *args, **kwargs):
        if failure == "report" and path.name == "collection.json":
            raise OSError("disk full")
        return original_write(path, *args, **kwargs)

    monkeypatch.setattr(feeds, "urlopen", network)
    monkeypatch.setattr(Path, "open", open_file)
    monkeypatch.setattr(Path, "write_text", write_file)
    with pytest.raises(OSError):
        feeds.collect(
            [
                {"name": "A", "url": "https://example.test/a"},
                {"name": "B", "url": "https://example.test/b"},
            ],
            "2026-10-01",
            tmp_path,
        )
    assert len(calls) == 1

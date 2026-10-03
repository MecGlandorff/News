from io import BytesIO
from urllib.error import URLError
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

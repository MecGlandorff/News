import logging

from src import scraper


def test_scrape_all_does_not_fetch_article_text_by_default(monkeypatch):
    def fake_parse_rss(url, session=None):
        return [{
            "title": "Title",
            "url": "https://example.com/article",
            "description": "Description",
            "published_at": "Sat, 18 Apr 2026 10:00:00 GMT",
        }]

    def fail_extract_text(url, session=None):
        raise AssertionError("article text should not be fetched by default")

    monkeypatch.setattr(scraper, "_parse_rss", fake_parse_rss)
    monkeypatch.setattr(scraper, "_extract_text", fail_extract_text)

    articles = scraper.scrape_all(sources=[("Example", "en", "https://example.com/rss")])

    assert articles[0]["text"] == ""


def test_scrape_all_can_fetch_article_text_when_requested(monkeypatch):
    def fake_parse_rss(url, session=None):
        return [{
            "title": "Title",
            "url": "https://example.com/article",
            "description": "Description",
            "published_at": "Sat, 18 Apr 2026 10:00:00 GMT",
        }]

    monkeypatch.setattr(scraper, "_parse_rss", fake_parse_rss)
    monkeypatch.setattr(scraper, "_extract_text", lambda url, session=None: "Full text")

    articles = scraper.scrape_all(
        sources=[("Example", "en", "https://example.com/rss")],
        fetch_article_text=True,
    )

    assert articles[0]["text"] == "Full text"
    assert scraper.last_scrape_stats()["article_text_fetch_successes"] == 1


def test_scrape_all_records_duplicate_and_failure_counts(monkeypatch):
    def fake_parse_rss(url, session=None):
        if url.endswith("/bad"):
            raise RuntimeError("feed down")
        return [
            {
                "title": "First",
                "url": "https://example.com/article?utm_source=x",
                "description": "Description",
                "published_at": "Sat, 18 Apr 2026 10:00:00 GMT",
            },
            {
                "title": "Duplicate",
                "url": "https://example.com/article",
                "description": "Description",
                "published_at": "Sat, 18 Apr 2026 11:00:00 GMT",
            },
            {
                "title": "Empty body",
                "url": "https://example.com/empty",
                "description": "Description",
                "published_at": "Sat, 18 Apr 2026 12:00:00 GMT",
            },
        ]

    def fake_extract_text(url, session=None):
        if url.endswith("/empty"):
            return ""
        return "Full text"

    monkeypatch.setattr(scraper, "_parse_rss", fake_parse_rss)
    monkeypatch.setattr(scraper, "_extract_text", fake_extract_text)
    monkeypatch.setattr(scraper.time, "sleep", lambda delay: None)

    articles = scraper.scrape_all(
        sources=[
            ("Good", "en", "https://example.com/good"),
            ("Bad", "en", "https://example.com/bad"),
        ],
        fetch_article_text=True,
    )

    stats = scraper.last_scrape_stats()
    assert [article["title"] for article in articles] == ["First", "Empty body"]
    assert stats["duplicate_url_skips"] == 1
    assert stats["feed_fetch_failures"] == 1
    assert stats["article_text_fetch_successes"] == 1
    assert stats["article_text_fetch_failures"] == 1


def test_scrape_all_reads_all_feed_items_by_default(monkeypatch):
    def fake_parse_rss(url, session=None):
        return [
            {
                "title": f"Title {i}",
                "url": f"https://example.com/article-{i}",
                "description": "Description",
                "published_at": "Sat, 18 Apr 2026 10:00:00 GMT",
            }
            for i in range(12)
        ]

    monkeypatch.setattr(scraper, "_parse_rss", fake_parse_rss)
    monkeypatch.setattr(scraper.time, "sleep", lambda delay: None)

    articles = scraper.scrape_all(sources=[("Example", "en", "https://example.com/rss")])

    assert len(articles) == 12


def test_scrape_all_still_honors_max_per_source(monkeypatch):
    def fake_parse_rss(url, session=None):
        return [
            {
                "title": f"Title {i}",
                "url": f"https://example.com/article-{i}",
                "description": "Description",
                "published_at": "Sat, 18 Apr 2026 10:00:00 GMT",
            }
            for i in range(12)
        ]

    monkeypatch.setattr(scraper, "_parse_rss", fake_parse_rss)
    monkeypatch.setattr(scraper.time, "sleep", lambda delay: None)

    articles = scraper.scrape_all(
        sources=[("Example", "en", "https://example.com/rss")],
        max_per_source=5,
    )

    assert len(articles) == 5


def test_scrape_all_filters_to_target_date(monkeypatch):
    def fake_parse_rss(url, session=None):
        return [
            {
                "title": "Today",
                "url": "https://example.com/today",
                "description": "Description",
                "published_at": "Sat, 18 Apr 2026 10:00:00 GMT",
            },
            {
                "title": "Yesterday",
                "url": "https://example.com/yesterday",
                "description": "Description",
                "published_at": "Fri, 17 Apr 2026 10:00:00 GMT",
            },
            {
                "title": "Undated",
                "url": "https://example.com/undated",
                "description": "Description",
                "published_at": "",
            },
        ]

    monkeypatch.setattr(scraper, "_parse_rss", fake_parse_rss)
    monkeypatch.setattr(scraper.time, "sleep", lambda delay: None)

    articles = scraper.scrape_all(
        sources=[("Example", "en", "https://example.com/rss")],
        target_date="2026-04-18",
    )

    assert [article["title"] for article in articles] == ["Today"]


def test_scrape_all_can_include_undated_items_with_target_date(monkeypatch, caplog):
    def fake_parse_rss(url, session=None):
        return [
            {
                "title": "Today",
                "url": "https://example.com/today",
                "description": "Description",
                "published_at": "Sat, 18 Apr 2026 10:00:00 GMT",
            },
            {
                "title": "Yesterday",
                "url": "https://example.com/yesterday",
                "description": "Description",
                "published_at": "Fri, 17 Apr 2026 10:00:00 GMT",
            },
            {
                "title": "Missing",
                "url": "https://example.com/missing",
                "description": "Description",
                "published_at": "",
            },
            {
                "title": "Bad date",
                "url": "https://example.com/bad-date",
                "description": "Description",
                "published_at": "not a date",
            },
        ]

    monkeypatch.setattr(scraper, "_parse_rss", fake_parse_rss)
    monkeypatch.setattr(scraper.time, "sleep", lambda delay: None)

    with caplog.at_level(logging.INFO, logger="src.scraper"):
        articles = scraper.scrape_all(
            sources=[("Example", "en", "https://example.com/rss")],
            target_date="2026-04-18",
            include_undated=True,
        )

    output = caplog.text
    stats = scraper.last_scrape_stats()
    assert [article["title"] for article in articles] == ["Today", "Missing", "Bad date"]
    assert stats["feed_items_outside_date_skipped"] == 1
    assert stats["feed_items_missing_timestamp_included"] == 1
    assert stats["feed_items_unparseable_timestamp_included"] == 1
    assert stats["feed_items_missing_timestamp_skipped"] == 0
    assert stats["feed_items_unparseable_timestamp_skipped"] == 0
    assert "Included 2 feed items without a usable timestamp because --include-undated is enabled" in output


def test_scrape_all_reports_timestamp_skip_reasons(monkeypatch, caplog):
    def fake_parse_rss(url, session=None):
        if url.endswith("/a"):
            return [
                {
                    "title": "Today",
                    "url": "https://example.com/today",
                    "description": "Description",
                    "published_at": "Sat, 18 Apr 2026 10:00:00 GMT",
                },
                {
                    "title": "Yesterday",
                    "url": "https://example.com/yesterday",
                    "description": "Description",
                    "published_at": "Fri, 17 Apr 2026 10:00:00 GMT",
                },
                {
                    "title": "Missing",
                    "url": "https://example.com/missing",
                    "description": "Description",
                    "published_at": "",
                },
                {
                    "title": "Bad",
                    "url": "https://example.com/bad",
                    "description": "Description",
                    "published_at": "not a date",
                },
            ]
        return [{
            "title": "Also missing",
            "url": "https://example.org/missing",
            "description": "Description",
            "published_at": "",
        }]

    monkeypatch.setattr(scraper, "_parse_rss", fake_parse_rss)
    monkeypatch.setattr(scraper.time, "sleep", lambda delay: None)

    with caplog.at_level(logging.INFO, logger="src.scraper"):
        articles = scraper.scrape_all(
            sources=[
                ("Example A", "en", "https://example.com/a"),
                ("Example B", "en", "https://example.com/b"),
            ],
            target_date="2026-04-18",
        )

    output = caplog.text
    assert [article["title"] for article in articles] == ["Today"]
    stats = scraper.last_scrape_stats()
    assert stats["feed_items_outside_date_skipped"] == 1
    assert stats["feed_items_missing_timestamp_skipped"] == 2
    assert stats["feed_items_unparseable_timestamp_skipped"] == 1
    assert "Skipped 1 feed items outside 2026-04-18" in output
    assert "Skipped 3 feed items without a usable timestamp (2 missing, 1 unparseable)" in output
    assert "Example A: 2 (1 missing, 1 unparseable)" in output
    assert "Example B: 1 (1 missing, 0 unparseable)" in output


def test_scrape_all_applies_max_per_source_after_date_filter(monkeypatch):
    def fake_parse_rss(url, session=None):
        return [
            {
                "title": "Stale",
                "url": "https://example.com/stale",
                "description": "Description",
                "published_at": "Fri, 17 Apr 2026 10:00:00 GMT",
            },
            {
                "title": "Today",
                "url": "https://example.com/today",
                "description": "Description",
                "published_at": "Sat, 18 Apr 2026 10:00:00 GMT",
            },
        ]

    monkeypatch.setattr(scraper, "_parse_rss", fake_parse_rss)
    monkeypatch.setattr(scraper.time, "sleep", lambda delay: None)

    articles = scraper.scrape_all(
        sources=[("Example", "en", "https://example.com/rss")],
        max_per_source=1,
        target_date="2026-04-18",
    )

    assert [article["title"] for article in articles] == ["Today"]


def test_article_id_is_stable_for_tracking_query_params():
    plain = scraper._article_id("https://Example.com/story?b=2&utm_source=newsletter")
    tracked = scraper._article_id("https://example.com/story/?fbclid=abc&b=2")

    assert plain == tracked

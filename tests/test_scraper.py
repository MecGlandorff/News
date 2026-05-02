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

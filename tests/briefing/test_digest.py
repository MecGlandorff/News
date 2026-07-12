
from src.digest import build_themed_markdown
from tests.briefing.support import _briefing_article


def test_digest_handles_empty_articles():
    markdown = build_themed_markdown([])

    assert "# News Digest" in markdown
    assert "0 articles" in markdown
    assert "No articles found." in markdown


def test_digest_renders_cross_theme_story_once():
    first = _briefing_article(1, "Economy", "Shared Story", source="Source A")
    second = _briefing_article(2, "Tech", "Shared Story", source="Source B")

    markdown = build_themed_markdown([first, second])

    assert markdown.count("Shared Story _(importance") == 1
    assert "Source A" in markdown
    assert "Source B" in markdown


def test_digest_keeps_distinct_story_ids_with_same_label_separate():
    first = _briefing_article(1, "Economy", "Recurring Label", source="Source A")
    first["story_id"] = 10
    second = _briefing_article(2, "Economy", "Recurring Label", source="Source B")
    second["story_id"] = 11

    markdown = build_themed_markdown([first, second])

    assert markdown.count("Recurring Label _(importance") == 2


def test_digest_includes_reported_time_and_source_url():
    markdown = build_themed_markdown([{
        "source": "Example News",
        "language": "en",
        "title": "Example development",
        "description": "Description",
        "url": "https://example.com/story",
        "published_at": "Sat, 18 Apr 2026 12:30:00 GMT",
        "text": "",
        "theme": "Economy",
        "story_label": "Example Story",
        "importance": 3,
    }])

    assert "reported 2026-04-18 12:30 UTC" in markdown
    assert "[Example development](https://example.com/story)" in markdown

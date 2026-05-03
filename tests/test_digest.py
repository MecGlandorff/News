import json

import src.claims as claims_module
from src.digest import build_themed_markdown
import src.top10 as top10
from src.claims import extract_and_save_claims
from src.top10 import build_briefing_markdown, write_top10


def test_digest_handles_empty_articles():
    markdown = build_themed_markdown([])

    assert "# News Digest" in markdown
    assert "0 articles" in markdown
    assert "No articles found." in markdown


def test_briefing_handles_empty_stories():
    markdown = build_briefing_markdown([])

    assert "# Top Developments" in markdown
    assert "No tracked stories found." in markdown


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


def test_briefing_includes_latest_reported_time_and_source_urls(monkeypatch):
    monkeypatch.setattr(
        top10,
        "_get_briefings",
        lambda stories: {"Example Story": "Briefing text."},
    )

    markdown = build_briefing_markdown([{
        "id": 1,
        "source": "Example News",
        "language": "en",
        "title": "Example development",
        "description": "Description",
        "url": "https://example.com/story",
        "published_at": "Sat, 18 Apr 2026 12:30:00 GMT",
        "text": "",
        "theme": "Economy",
        "story_label": "Example Story",
        "canonical_label": "Example Story",
        "importance": 3,
        "trend": "new",
    }])

    assert "latest reported 2026-04-18 12:30 UTC" in markdown
    assert "**What changed today:** First detected today." in markdown
    assert "Sources:" in markdown
    assert "[Example development](https://example.com/story)" in markdown


def test_write_top10_writes_public_briefing_markdown(tmp_path, monkeypatch):
    monkeypatch.setattr(top10, "BRIEFINGS_DIR", tmp_path / "briefings")
    monkeypatch.setattr(
        top10,
        "_get_briefings",
        lambda stories: {"Example Story": "Briefing text."},
    )

    out = write_top10([{
        "id": 1,
        "source": "Example News",
        "language": "en",
        "title": "Example development",
        "description": "Description",
        "url": "https://example.com/story",
        "published_at": "Sat, 18 Apr 2026 12:30:00 GMT",
        "text": "",
        "theme": "Economy",
        "story_label": "Example Story",
        "canonical_label": "Example Story",
        "importance": 3,
        "trend": "new",
    }])

    assert out.parent == tmp_path / "briefings"
    assert out.name.startswith("briefing_")
    assert out.suffix == ".md"
    text = out.read_text(encoding="utf-8")
    assert "Briefing text." in text
    assert "**What changed today:** First detected today." in text


def test_briefing_retries_missing_summary(monkeypatch):
    calls = []

    def fake_get_briefings(stories):
        calls.append([story["canonical_label"] for story in stories])
        if len(calls) == 1:
            return {"Story A": "Briefing A.", "Story B": ""}
        return {"Story B": "Briefing B after retry."}

    monkeypatch.setattr(top10, "_get_briefings", fake_get_briefings)

    markdown = build_briefing_markdown([
        _briefing_article(1, "Geopolitics & War", "Story A", 5),
        _briefing_article(2, "Economy", "Story B", 4),
    ], n=3)

    assert calls == [["Story A", "Story B"], ["Story B"]]
    assert "Briefing A." in markdown
    assert "Briefing B after retry." in markdown


def test_briefing_remembers_generated_story_summary(monkeypatch):
    memories = []
    monkeypatch.setattr(
        top10,
        "_get_briefings",
        lambda stories: {
            "Example Story": {
                "briefing": "Generated briefing.",
                "delta_summary": "New reporting clarified the policy impact.",
            }
        },
    )
    monkeypatch.setattr(top10, "save_observation_memory", lambda updates: memories.extend(updates))

    article = _briefing_article(1, "Economy", "Example Story", 4)
    article["observation_id"] = 42

    markdown = build_briefing_markdown([article])

    assert "Generated briefing." in markdown
    assert "**What changed today:** New reporting clarified the policy impact." in markdown
    assert memories == [{
        "observation_id": 42,
        "summary": "Generated briefing.",
        "delta_summary": "New reporting clarified the policy impact.",
    }]


def test_get_briefings_sends_previous_context(monkeypatch):
    captured = {}

    class Message:
        content = (
            '{"briefings":[{"canonical_label":"Example Story",'
            '"delta_summary":"Today added a concrete deadline.",'
            '"briefing":"Briefing text."}]}'
        )

    class Choice:
        message = Message()

    class Response:
        choices = [Choice()]

    class Completions:
        def create(self, **kwargs):
            captured["items"] = json.loads(kwargs["messages"][1]["content"])
            return Response()

    class Chat:
        def __init__(self):
            self.completions = Completions()

    class Client:
        def __init__(self):
            self.chat = Chat()

    monkeypatch.setattr(top10, "get_openai_client", lambda: Client())

    result = top10._get_briefings([{
        "canonical_label": "Example Story",
        "previous_context": {
            "summary": "Earlier summary.",
            "recent_articles": [{"title": "Older title"}],
        },
        "articles": [{
            "source": "Example News",
            "title": "Current title",
            "description": "Current description",
            "published_at": "Sat, 18 Apr 2026 12:30:00 GMT",
            "url": "https://example.com/current",
        }],
    }])

    assert result == {
        "Example Story": {
            "briefing": "Briefing text.",
            "delta_summary": "Today added a concrete deadline.",
        }
    }
    assert captured["items"][0]["previous_context"]["summary"] == "Earlier summary."
    assert captured["items"][0]["previous_context"]["recent_articles"][0]["title"] == "Older title"


def test_get_briefings_sends_claims_when_evidence_enabled(tmp_path, monkeypatch):
    monkeypatch.setattr(claims_module, "DB_PATH", tmp_path / "stories.db")

    article = _briefing_article(1, "Economy", "Example Story", 4)
    article["story_id"] = 42
    article["description"] = "Concrete supported claim."

    class ClaimMessage:
        content = json.dumps({
            "claims": [{
                "claim_text": "Example Story has a concrete supported claim.",
                "claim_type": "fact",
                "entities": ["Example Story"],
                "evidence_span": "Concrete supported claim.",
                "confidence": 0.9,
            }]
        })

    class ClaimChoice:
        message = ClaimMessage()

    class ClaimResponse:
        choices = [ClaimChoice()]

    class ClaimCompletions:
        def create(self, **kwargs):
            return ClaimResponse()

    class ClaimChat:
        completions = ClaimCompletions()

    class ClaimClient:
        chat = ClaimChat()

    monkeypatch.setattr(claims_module, "get_openai_client", lambda: ClaimClient())
    extract_and_save_claims([article])

    captured = {}

    class BriefingMessage:
        content = (
            '{"briefings":[{"canonical_label":"Example Story",'
            '"delta_summary":"First detected today.",'
            '"briefing":"Briefing text."}]}'
        )

    class BriefingChoice:
        message = BriefingMessage()

    class BriefingResponse:
        choices = [BriefingChoice()]

    class BriefingCompletions:
        def create(self, **kwargs):
            captured["items"] = json.loads(kwargs["messages"][1]["content"])
            return BriefingResponse()

    class BriefingChat:
        completions = BriefingCompletions()

    class BriefingClient:
        chat = BriefingChat()

    monkeypatch.setattr(top10, "get_openai_client", lambda: BriefingClient())

    top10._get_briefings([{
        "canonical_label": "Example Story",
        "story_id": 42,
        "articles": [article],
    }], include_evidence=True)

    assert captured["items"][0]["claims"][0]["claim_text"] == "Example Story has a concrete supported claim."
    assert captured["items"][0]["claims"][0]["evidence_span"] == "Concrete supported claim."


def test_evidence_lines_do_not_fallback_to_claim_text(monkeypatch):
    monkeypatch.setattr(
        claims_module,
        "get_claims_for_story",
        lambda story_id: [{
            "claim_text": "Unsupported model wording.",
            "claim_type": "fact",
            "evidence_span": "",
            "confidence": 0.9,
            "source": "Example News",
            "url": "https://example.com/story",
        }],
    )

    assert top10._evidence_lines(42) == []


def test_briefing_uses_fallback_when_summary_stays_missing(monkeypatch):
    monkeypatch.setattr(top10, "_get_briefings", lambda stories: {})

    markdown = build_briefing_markdown([
        _briefing_article(1, "Economy", "Missing Story", 4, source="Example News"),
    ])

    assert "Missing Story is included based on 1 source" in markdown
    assert "**What changed today:** First detected today." in markdown
    assert "The lead item is from Example News" in markdown
    assert "\n\n\nSources:" not in markdown


def _briefing_article(article_id, theme, label, importance=3, source=None):
    return {
        "id": article_id,
        "source": source or f"Source {article_id}",
        "language": "en",
        "title": f"{label} title",
        "description": "Description",
        "url": f"https://example.com/{article_id}",
        "published_at": "Sat, 18 Apr 2026 12:30:00 GMT",
        "text": "",
        "theme": theme,
        "story_label": label,
        "canonical_label": label,
        "importance": importance,
        "trend": "new",
    }


def test_briefing_uses_editorial_sections_and_scraps_sports(monkeypatch):
    monkeypatch.setattr(
        top10,
        "_get_briefings",
        lambda stories: {story["canonical_label"]: "Briefing text." for story in stories},
    )

    markdown = build_briefing_markdown([
        _briefing_article(1, "Geopolitics & War", "Hormuz Strait", 5),
        _briefing_article(2, "USA Politics", "US Congress", 4),
        _briefing_article(3, "Dutch Politics", "Dutch Cabinet", 4),
        _briefing_article(4, "Economy", "Oil Prices", 4),
        _briefing_article(5, "Other", "Kinahan Arrest", 3),
        _briefing_article(9, "USA Politics", "US Courts", 3),
        _briefing_article(10, "Dutch Politics", "Dutch Budget", 3),
        _briefing_article(11, "Economy", "China Sanctions", 3),
        _briefing_article(12, "Other", "Celebrity Video", 4),
        _briefing_article(6, "Sports", "Korfball Title", 5),
        _briefing_article(7, "Tech", "AI Opinion Piece", 4),
        _briefing_article(8, "Science", "Minor Health Story", 4),
    ], n=3)

    assert markdown.startswith("# Top Developments")
    assert "# Politics" in markdown
    assert "# Economy" in markdown
    assert "# Other Important Stories" in markdown
    assert "# Sports" not in markdown
    assert "Korfball Title" not in markdown
    assert "AI Opinion Piece" not in markdown
    assert "Minor Health Story" not in markdown
    assert "Celebrity Video" not in markdown
    assert "Kinahan Arrest" in markdown


def test_briefing_deduplicates_story_across_themes(monkeypatch):
    monkeypatch.setattr(
        top10,
        "_get_briefings",
        lambda stories: {story["canonical_label"]: "Briefing text." for story in stories},
    )

    markdown = build_briefing_markdown([
        _briefing_article(1, "Geopolitics & War", "Iran War", 5, source="Source A"),
        _briefing_article(2, "Economy", "Iran War", 4, source="Source B"),
        _briefing_article(3, "USA Politics", "Iran War", 4, source="Source C"),
    ], n=3)

    assert markdown.count("## 1. NEW STORY Iran War") == 1
    assert "Geopolitics & War / USA Politics / Economy" in markdown

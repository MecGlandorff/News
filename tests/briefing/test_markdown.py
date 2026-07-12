
import src.claims as claims_module
import src.briefing as top10
from src.briefing import build_briefing_markdown, write_top10
from tests.briefing.support import _briefing_article


def test_briefing_handles_empty_stories():
    markdown = build_briefing_markdown([])

    assert "# Top Developments" in markdown
    assert "No tracked stories found." in markdown


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


def test_briefing_renders_structured_story_card_fields(monkeypatch):
    monkeypatch.setattr(
        top10,
        "_get_briefings",
        lambda stories: {
            "Example Story": {
                "briefing": "The decision changes the political stakes.",
                "delta_summary": "New reporting clarified the policy impact.",
                "status": "developing",
                "confidence": "medium",
                "source_agreement": "mixed",
                "dispute_flag": "possible conflict",
                "open_questions": ["Whether the cabinet changes the proposal."],
            }
        },
    )

    markdown = build_briefing_markdown([
        _briefing_article(1, "Economy", "Example Story", 4),
    ])

    assert "**Status:** Developing" in markdown
    assert "**Confidence:** Medium" in markdown
    assert "**Source agreement:** Mixed" in markdown
    assert "**Dispute:** Possible Conflict" in markdown
    assert "### Why it matters" in markdown
    assert "### What to watch" in markdown
    assert "- Whether the cabinet changes the proposal." in markdown


def test_briefing_bounds_invalid_structured_story_card_fields(monkeypatch):
    monkeypatch.setattr(
        top10,
        "_get_briefings",
        lambda stories: {
            "Example Story": {
                "briefing": "Briefing text.",
                "delta_summary": "First detected today.",
                "status": "certainly explosive",
                "confidence": "absolute",
                "source_agreement": "everyone agrees",
                "dispute_flag": "messy",
            }
        },
    )

    markdown = build_briefing_markdown([
        _briefing_article(1, "Economy", "Example Story", 4),
    ])

    assert "certainly explosive" not in markdown
    assert "absolute" not in markdown
    assert "everyone agrees" not in markdown
    assert "messy" not in markdown
    assert "**Status:** New" in markdown
    assert "**Confidence:** Low" in markdown
    assert "**Source agreement:** Single Source" in markdown
    assert "**Dispute:** None" in markdown


def test_evidence_lines_do_not_fallback_to_claim_text(monkeypatch):
    monkeypatch.setattr(
        claims_module,
        "get_claims_for_story",
        lambda story_id, **kwargs: [{
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


def test_briefing_marks_new_child_development_under_parent_arc(monkeypatch):
    monkeypatch.setattr(
        top10,
        "_get_briefings",
        lambda stories: {story["canonical_label"]: "Briefing text." for story in stories},
    )

    article = _briefing_article(1, "Geopolitics & War", "Iran conflict", 5)
    article["canonical_label"] = "Iran war crisis"
    article["development_label"] = "Iran conflict"
    article["development_status"] = "new_child"
    article["previous_context"] = {"summary": "Earlier Iran war context."}
    article["trend"] = "steady"

    markdown = build_briefing_markdown([article], n=3)

    assert "## 1. NEW DEVELOPMENT Iran war crisis" in markdown
    assert "**Parent arc:** Iran war crisis | **Today's development:** Iran conflict" in markdown

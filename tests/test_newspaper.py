from datetime import datetime

import src.newspaper as newspaper
from src.geo import infer_story_location


def _story(label, trend, theme="Geopolitics & War", source="Example News"):
    return {
        "canonical_label": label,
        "story_label": label,
        "theme": theme,
        "themes": {theme},
        "trend": trend,
        "source_count": 1,
        "importance_avg": 4.0,
        "previous_context": {},
        "articles": [{
            "source": source,
            "title": f"{label} title",
            "description": f"{label} description",
            "url": "https://example.com/story",
            "published_at": "Sat, 18 Apr 2026 12:30:00 GMT",
            "importance": 4,
            "theme": theme,
        }],
    }


def test_newspaper_sections_group_by_story_movement():
    package = {
        "display_stories": [
            _story("Chad water clash", "new"),
            _story("Iran diplomacy", "up"),
            _story("Ukraine war", "steady"),
            _story("Old campaign story", "down"),
        ],
    }

    sections = newspaper.build_newspaper_sections(package)

    assert [section["title"] for section in sections] == [
        "NEW TODAY",
        "DEVELOPING STORIES",
        "CONTINUING WATCH",
        "COOLING / LOWER PRIORITY",
    ]
    assert sections[0]["stories"][0]["canonical_label"] == "Chad water clash"


def test_infer_story_location_returns_story_level_point():
    location = infer_story_location(_story("Mali attacks", "new"))

    assert location["label"] == "Mali"
    assert location["points"][0]["lat"] == 17.5707
    assert location["confidence"] == "high"


def test_existing_story_body_does_not_duplicate_previous_label():
    item = _story("Iran war economic fallout", "up", theme="Economy")
    item["previous_context"] = {
        "summary": "Previously: markets were reacting mainly to oil and shipping disruption."
    }

    body = newspaper._story_body(item, "The economic effects are widening.")

    assert body.startswith("Previously: markets were reacting")
    assert "Previously: Previously:" not in body


def test_story_body_does_not_leak_raw_article_titles():
    item = _story("Mali attacks", "up")
    item["articles"][0]["title"] = "Voormalig vijanden slaan de handen ineen in Mali"
    item["previous_context"] = {
        "delta_summary": "Today's reporting: Mali Terror Attack; Voormalig vijanden slaan de handen ineen in Mali"
    }

    body = newspaper._story_body(item, "Mali's junta is facing a severe challenge.")

    assert "Voormalig" not in body
    assert "Today's reporting" not in body
    assert "Mali's junta is facing" in body


def test_story_body_includes_delta_summary():
    item = _story("Mali attacks", "up")

    body = newspaper._story_body(
        item,
        "Mali's junta is facing a severe challenge.",
        "New refugee accounts widened the picture of civilian harm.",
    )

    assert body.startswith("What changed today: New refugee accounts")
    assert "Mali's junta is facing a severe challenge." in body


def test_story_body_fallback_avoids_raw_article_text():
    item = _story("Mali attacks", "new")
    item["articles"][0]["title"] = "Voormalig vijanden slaan de handen ineen in Mali"
    item["articles"][0]["description"] = "Nederlandse omschrijving"

    body = newspaper._story_body(item, "")

    assert "Voormalig" not in body
    assert "Nederlandse" not in body
    assert "generated briefing was not available" in body


def test_map_projection_keeps_locations_inside_inset():
    x, y = newspaper._project(18.7322, 15.4542, 10, 20, 62, 28)

    assert 10 <= x <= 72
    assert 20 <= y <= 48


def test_write_newspaper_pdf_outputs_local_pdf(tmp_path, monkeypatch):
    monkeypatch.setattr(newspaper, "NEWSPAPER_DIR", tmp_path)
    package = {
        "generated_at": datetime(2026, 4, 27, 20, 42),
        "display_stories": [_story("Mali attacks", "new")],
        "briefings": {
            "Mali attacks": "Mali saw coordinated attacks that exposed pressure on the state."
        },
        "deltas": {
            "Mali attacks": "First detected today."
        },
    }

    out = newspaper.write_newspaper_pdf([], package=package)

    data = out.read_bytes()
    assert out.suffix == ".pdf"
    assert data.startswith(b"%PDF-1.4")
    assert b"THE DAILY BRIEFING" in data
    assert b"NEW TODAY" in data
    assert b"What changed today" in data
    assert b"Mali attacks" in data

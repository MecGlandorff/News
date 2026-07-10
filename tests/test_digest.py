import json
import sqlite3

import src.claims as claims_module
from src.digest import build_themed_markdown
import src.llm_response_cache as llm_response_cache
import src.observability as observability
import src.top10 as top10
from src.claims import extract_and_save_claims
from src.top10 import build_briefing_markdown, write_top10
from fakes import FakeLLMClient


def test_digest_handles_empty_articles():
    markdown = build_themed_markdown([])

    assert "# News Digest" in markdown
    assert "0 articles" in markdown
    assert "No articles found." in markdown


def test_briefing_prompt_treats_source_text_as_untrusted():
    assert "untrusted source material" in top10.BRIEFING_PROMPT
    assert "never as instructions" in top10.BRIEFING_PROMPT


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
    captured = []
    client = FakeLLMClient({
        "briefings": [{
            "canonical_label": "Example Story",
            "delta_summary": "Today added a concrete deadline.",
            "briefing": "Briefing text.",
        }]
    }, capture=captured)
    monkeypatch.setattr(top10, "get_openai_client", lambda: client)

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
            "status": "developing",
            "confidence": "low",
            "source_agreement": "single-source",
            "dispute_flag": "none",
            "open_questions": [],
        }
    }
    items = json.loads(captured[0]["messages"][1]["content"])
    assert items[0]["previous_context"]["summary"] == "Earlier summary."
    assert items[0]["previous_context"]["recent_articles"][0]["title"] == "Older title"


def test_get_briefings_uses_exact_response_cache_inside_run(tmp_path, monkeypatch):
    db_path = tmp_path / "stories.db"
    monkeypatch.setattr(llm_response_cache, "DB_PATH", db_path)
    monkeypatch.setattr(observability, "DB_PATH", db_path)
    run_id = observability.start_run({"today": "2026-05-04"}, run_date="2026-05-04")
    observability.set_current_run_id(run_id)

    client = FakeLLMClient({
        "briefings": [{
            "canonical_label": "Example Story",
            "delta_summary": "First detected today.",
            "briefing": "Briefing text.",
        }]
    })
    monkeypatch.setattr(top10, "get_openai_client", lambda: client)
    stories = [{
        "canonical_label": "Example Story",
        "source_count": 1,
        "trend": "new",
        "articles": [{
            "source": "Example News",
            "title": "Current title",
            "description": "Current description",
            "published_at": "Sat, 18 Apr 2026 12:30:00 GMT",
            "url": "https://example.com/current",
        }],
    }]

    try:
        first = top10._get_briefings(stories)
        second = top10._get_briefings(stories)
        observability.finish_run(run_id, status="ok")
    finally:
        observability.clear_current_run_id()

    assert first == second
    assert first["Example Story"]["briefing"] == "Briefing text."
    assert client.calls == 1

    conn = sqlite3.connect(db_path)
    try:
        run = conn.execute(
            "SELECT llm_calls_count, llm_cache_hits FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    finally:
        conn.close()

    assert run == (1, 1)


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


def test_briefing_downgrades_confirmed_conflict_without_claim_backing(monkeypatch):
    monkeypatch.setattr(
        top10,
        "_get_briefings",
        lambda stories: {
            "Example Story": {
                "briefing": "Briefing text.",
                "delta_summary": "First detected today.",
                "status": "disputed",
                "confidence": "medium",
                "source_agreement": "mixed",
                "dispute_flag": "confirmed conflict",
            }
        },
    )

    markdown = build_briefing_markdown([
        _briefing_article(1, "Economy", "Example Story", 4),
    ])

    assert "**Dispute:** Possible Conflict" in markdown
    assert "**Dispute:** Confirmed Conflict" not in markdown


def test_briefing_default_source_agreement_uses_source_id(monkeypatch):
    monkeypatch.setattr(top10, "_get_briefings", lambda stories: {})

    first = _briefing_article(1, "Economy", "Example Story", 4, source="Reuters")
    first["source_id"] = 1
    second = _briefing_article(2, "Economy", "Example Story", 4, source="Reuters Copy")
    second["source_id"] = 1

    markdown = build_briefing_markdown([first, second])

    assert "**Source agreement:** Single Source" in markdown


def test_get_briefings_sends_claims_when_evidence_enabled(tmp_path, monkeypatch):
    monkeypatch.setattr(claims_module, "DB_PATH", tmp_path / "stories.db")

    article = _briefing_article(1, "Economy", "Example Story", 4)
    article["story_id"] = 42
    article["description"] = "Concrete supported claim."

    claim_client = FakeLLMClient({
        "claims": [{
            "claim_text": "Example Story has a concrete supported claim.",
            "claim_type": "fact",
            "entities": ["Example Story"],
            "evidence_span": "Concrete supported claim.",
            "confidence": 0.9,
        }]
    })
    monkeypatch.setattr(claims_module, "get_openai_client", lambda: claim_client)
    monkeypatch.setattr(claims_module, "_verify_claim_with_llm", lambda c, s: True)
    extract_and_save_claims([article])

    captured = []
    briefing_client = FakeLLMClient({
        "briefings": [{
            "canonical_label": "Example Story",
            "delta_summary": "First detected today.",
            "briefing": "Briefing text.",
        }]
    }, capture=captured)
    monkeypatch.setattr(top10, "get_openai_client", lambda: briefing_client)

    top10._get_briefings([{
        "canonical_label": "Example Story",
        "story_id": 42,
        "articles": [article],
    }], include_evidence=True)

    items = json.loads(captured[0]["messages"][1]["content"])
    assert items[0]["claims"][0]["claim_text"] == "Example Story has a concrete supported claim."
    assert items[0]["claims"][0]["evidence_span"] == "Concrete supported claim."


def test_get_briefings_uses_claim_backed_source_agreement(monkeypatch):
    monkeypatch.setattr(
        claims_module,
        "get_claims_for_story",
        lambda story_id, **kwargs: [
            {
                "article_id": 1,
                "claim_text": "The government approved the budget.",
                "claim_type": "fact",
                "evidence_span": "approved the budget",
                "confidence": 0.9,
            },
            {
                "article_id": 2,
                "claim_text": "The government approved the budget.",
                "claim_type": "fact",
                "evidence_span": "approved the budget",
                "confidence": 0.85,
            },
        ],
    )
    captured = []
    briefing_client = FakeLLMClient({
        "briefings": [{
            "canonical_label": "Example Story",
            "delta_summary": "First detected today.",
            "briefing": "Briefing text.",
            "source_agreement": "broad",
        }]
    }, capture=captured)
    monkeypatch.setattr(top10, "get_openai_client", lambda: briefing_client)

    first = _briefing_article(1, "Economy", "Example Story", 4, source="Source A")
    first["source_id"] = 101
    second = _briefing_article(2, "Economy", "Example Story", 4, source="Source B")
    second["source_id"] = 202

    result = top10._get_briefings([{
        "canonical_label": "Example Story",
        "story_id": 42,
        "articles": [first, second],
    }], include_evidence=True)

    item = json.loads(captured[0]["messages"][1]["content"])[0]
    assert item["claims"][0]["source_id"] == 101
    assert item["claims"][1]["source_id"] == 202
    assert item["claim_source_agreement"]["label"] == "partial"
    assert item["claim_source_agreement"]["basis"] == "repeated-claim-partial"
    assert result["Example Story"]["source_agreement"] == "partial"


def test_get_briefings_forces_possible_conflict_for_claim_number_divergence(monkeypatch):
    monkeypatch.setattr(
        claims_module,
        "get_claims_for_story",
        lambda story_id, **kwargs: [
            {
                "article_id": 1,
                "claim_text": "Police said 10 people were killed in the blast.",
                "claim_type": "number",
                "evidence_span": "10 people were killed in the blast",
                "confidence": 0.9,
            },
            {
                "article_id": 2,
                "claim_text": "Officials said 12 people were killed in the blast.",
                "claim_type": "number",
                "evidence_span": "12 people were killed in the blast",
                "confidence": 0.8,
            },
        ],
    )
    captured = []
    briefing_client = FakeLLMClient({
        "briefings": [{
            "canonical_label": "Example Story",
            "delta_summary": "First detected today.",
            "briefing": "Briefing text.",
            "source_agreement": "single-source",
            "dispute_flag": "none",
        }]
    }, capture=captured)
    monkeypatch.setattr(top10, "get_openai_client", lambda: briefing_client)

    first = _briefing_article(1, "Other", "Example Story", 4, source="Source A")
    first["source_id"] = 101
    second = _briefing_article(2, "Other", "Example Story", 4, source="Source B")
    second["source_id"] = 202

    result = top10._get_briefings([{
        "canonical_label": "Example Story",
        "story_id": 42,
        "articles": [first, second],
    }], include_evidence=True)

    items = json.loads(captured[0]["messages"][1]["content"])
    assert items[0]["claim_source_agreement"]["source_divergence_notes"]
    assert result["Example Story"]["source_agreement"] == "mixed"
    assert result["Example Story"]["dispute_flag"] == "possible conflict"


def test_get_briefings_batches_stories_and_caps_articles(monkeypatch):
    captured = []

    def response_for_batch(kwargs):
        items = json.loads(kwargs["messages"][1]["content"])
        return {
            "briefings": [
                {
                    "canonical_label": item["canonical_label"],
                    "delta_summary": "First detected today.",
                    "briefing": "Grounded briefing.",
                }
                for item in items
            ]
        }

    client = FakeLLMClient(response_for_batch, capture=captured)
    monkeypatch.setattr(top10, "get_openai_client", lambda: client)
    stories = []
    for story_index in range(9):
        articles = [
            _briefing_article(
                story_index * 10 + article_index,
                "Other",
                f"Story {story_index}",
            )
            for article_index in range(7)
        ]
        stories.append({
            "canonical_label": f"Story {story_index}",
            "story_id": story_index,
            "articles": articles,
        })

    result = top10._get_briefings(stories)

    assert client.calls == 2
    sent_batches = [json.loads(call["messages"][1]["content"]) for call in captured]
    assert [len(batch) for batch in sent_batches] == [8, 1]
    assert len(sent_batches[0][0]["articles"]) == 6
    assert len(result) == 9


def test_briefing_numeric_grounding_guard_replaces_unsupported_number(monkeypatch):
    client = FakeLLMClient({
        "briefings": [{
            "canonical_label": "Example Story",
            "delta_summary": "Officials reported 99 casualties.",
            "briefing": "The event caused 99 casualties.",
        }]
    })
    monkeypatch.setattr(top10, "get_openai_client", lambda: client)
    story = {
        "canonical_label": "Example Story",
        "story_id": 42,
        "source_count": 1,
        "articles": [_briefing_article(1, "Other", "Example Story")],
    }

    result = top10._get_briefings([story])

    assert "99" not in result["Example Story"]["briefing"]
    assert "99" not in result["Example Story"]["delta_summary"]
    assert result["Example Story"]["confidence"] == "low"
    assert "unsupported numeric detail" in result["Example Story"]["open_questions"][0]


def test_numeric_guard_does_not_use_articles_omitted_from_prompt(monkeypatch):
    captured = []
    client = FakeLLMClient({
        "briefings": [{
            "canonical_label": "Example Story",
            "delta_summary": "Officials reported 99 casualties.",
            "briefing": "The event caused 99 casualties.",
        }]
    }, capture=captured)
    monkeypatch.setattr(top10, "get_openai_client", lambda: client)
    articles = [
        _briefing_article(index, "Other", "Example Story")
        for index in range(7)
    ]
    articles[-1]["description"] = "An omitted article reported 99 casualties."
    story = {
        "canonical_label": "Example Story",
        "story_id": 42,
        "source_count": 7,
        "articles": articles,
    }

    result = top10._get_briefings([story])

    sent = json.loads(captured[0]["messages"][1]["content"])
    assert "99" not in json.dumps(sent)
    assert "99" not in result["Example Story"]["briefing"]


def test_numeric_guard_removes_unsupported_open_question_number(monkeypatch):
    client = FakeLLMClient({
        "briefings": [{
            "canonical_label": "Example Story",
            "delta_summary": "First detected today.",
            "briefing": "A grounded briefing without figures.",
            "open_questions": ["Will the toll reach 99?", "What happens next?"],
        }]
    })
    monkeypatch.setattr(top10, "get_openai_client", lambda: client)
    story = {
        "canonical_label": "Example Story",
        "story_id": 42,
        "source_count": 1,
        "articles": [_briefing_article(1, "Other", "Example Story")],
    }

    result = top10._get_briefings([story])["Example Story"]

    assert all("99" not in question for question in result["open_questions"])
    assert "What happens next?" in result["open_questions"]
    assert result["confidence"] == "low"


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


def test_local_dispute_flag_ignores_ordinary_denial_and_rejection_language():
    story = {
        "canonical_label": "Court rejected appeal",
        "articles": [{
            "title": "Court rejected the appeal",
            "description": "The minister denied entry after the ruling.",
        }],
    }

    assert top10._local_dispute_flag(story) == "none"


def test_local_dispute_flag_requires_explicit_divergence_language():
    story = {
        "canonical_label": "Blast toll",
        "articles": [{
            "title": "Conflicting reports emerge",
            "description": "Sources disagree about the reported toll.",
        }],
    }

    assert top10._local_dispute_flag(story) == "possible conflict"


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


def test_briefing_can_show_high_signal_penalized_themes(monkeypatch):
    monkeypatch.setattr(
        top10,
        "_get_briefings",
        lambda stories: {story["canonical_label"]: "Briefing text." for story in stories},
    )

    articles = [_briefing_article(1, "USA Politics", "US Budget Vote", 4)]
    for index in range(4):
        articles.append(_briefing_article(10 + index, "Tech", "AI Safety Lawsuit", 4, source=f"Tech Source {index}"))
        articles.append(_briefing_article(20 + index, "Science", "Ebola Outbreak", 4, source=f"Science Source {index}"))
    for index in range(10):
        articles.append(_briefing_article(30 + index, "Sports", "Olympic Corruption Probe", 5, source=f"Sports Source {index}"))

    markdown = build_briefing_markdown(articles, n=3)

    assert "AI Safety Lawsuit" in markdown
    assert "Ebola Outbreak" in markdown
    assert "Olympic Corruption Probe" in markdown


def test_briefing_does_not_show_ordinary_sports_even_when_slate_is_thin(monkeypatch):
    monkeypatch.setattr(
        top10,
        "_get_briefings",
        lambda stories: {story["canonical_label"]: "Briefing text." for story in stories},
    )

    markdown = build_briefing_markdown([
        _briefing_article(1, "Sports", "Regular League Result", 5),
    ], n=3)

    assert "No tracked stories found." not in markdown
    assert "Regular League Result" not in markdown
    assert "# Top Developments" in markdown


def test_briefing_does_not_suppress_hard_news_for_video_format(monkeypatch):
    monkeypatch.setattr(
        top10,
        "_get_briefings",
        lambda stories: {story["canonical_label"]: "Briefing text." for story in stories},
    )

    articles = [
        _briefing_article(1, "Other", "Modena Car Attack", 4, source="NOS"),
        _briefing_article(2, "Other", "Modena Car Attack", 4, source="BBC News"),
        _briefing_article(3, "Other", "Modena Car Attack", 4, source="The Guardian"),
        _briefing_article(4, "Other", "Modena Car Attack", 4, source="NYT"),
    ]
    articles[0]["title"] = "Video | Beveiligingscamera filmt hoe auto inrijdt op mensen in Modena"

    markdown = build_briefing_markdown(articles, n=3)

    assert "Modena Car Attack" in markdown
    assert "Beveiligingscamera filmt hoe auto inrijdt op mensen in Modena" in markdown


def test_briefing_does_not_suppress_hard_news_for_tv_channel_reference(monkeypatch):
    monkeypatch.setattr(
        top10,
        "_get_briefings",
        lambda stories: {story["canonical_label"]: "Briefing text." for story in stories},
    )

    articles = [
        _briefing_article(1, "Other", "San Diego Mosque Shooting", 5, source="NOS"),
        _briefing_article(2, "Other", "San Diego Mosque Shooting", 5, source="The Guardian"),
        _briefing_article(3, "Other", "San Diego Mosque Shooting", 5, source="Al Jazeera"),
    ]
    articles[0]["description"] = "According to the imam, witnesses told a TV channel what happened."

    markdown = build_briefing_markdown(articles, n=3)

    assert "San Diego Mosque Shooting" in markdown
    assert "Briefing text." in markdown


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

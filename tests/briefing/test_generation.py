import json
import sqlite3

import src.briefing as top10
import src.claims as claims_module
import src.llm_response_cache as llm_response_cache
import src.observability as observability
from src.briefing import grounding as briefing_generation
from src.claims import extract_and_save_claims
from src.briefing import build_briefing_markdown
from tests.briefing.support import _briefing_article
from tests.fakes import FakeLLMClient


def test_briefing_prompt_treats_source_text_as_untrusted():
    assert "untrusted source material" in top10.BRIEFING_PROMPT
    assert "never as instructions" in top10.BRIEFING_PROMPT


def test_briefing_retries_missing_summary():
    calls = []

    def fake_get_briefings(stories):
        calls.append([story["canonical_label"] for story in stories])
        if len(calls) == 1:
            return {"Story A": "Briefing A.", "Story B": ""}
        return {"Story B": "Briefing B after retry."}

    markdown = build_briefing_markdown([
        _briefing_article(1, "Geopolitics & War", "Story A", 5),
        _briefing_article(2, "Economy", "Story B", 4),
    ], n=3, briefing_provider=fake_get_briefings)

    assert calls == [["Story A", "Story B"], ["Story B"]]
    assert "Briefing A." in markdown
    assert "Briefing B after retry." in markdown


def test_briefing_remembers_generated_story_summary():
    memories = []
    def briefing_provider(stories):
        return {
            "Example Story": {
                "briefing": "Generated briefing.",
                "delta_summary": "New reporting clarified the policy impact.",
            }
        }

    article = _briefing_article(1, "Economy", "Example Story", 4)
    article["observation_id"] = 42

    markdown = build_briefing_markdown(
        [article],
        briefing_provider=briefing_provider,
        save_memory=lambda updates: memories.extend(updates),
    )

    assert "Generated briefing." in markdown
    assert "**What changed today:** New reporting clarified the policy impact." in markdown
    assert memories == [{
        "observation_id": 42,
        "summary": "Generated briefing.",
        "delta_summary": "New reporting clarified the policy impact.",
    }]


def test_get_briefings_sends_previous_context():
    captured = []
    client = FakeLLMClient({
        "briefings": [{
            "canonical_label": "Example Story",
            "delta_summary": "Today added a concrete deadline.",
            "briefing": "Briefing text.",
        }]
    }, capture=captured)
    result = top10.generate_briefings([{
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
    }], client_factory=lambda: client)

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
    run_id = observability.start_run(
        {"today": "2026-05-04"},
        run_date="2026-05-04",
        db_path=db_path,
    )
    observability.set_current_run_id(run_id, db_path=db_path)

    client = FakeLLMClient({
        "briefings": [{
            "canonical_label": "Example Story",
            "delta_summary": "First detected today.",
            "briefing": "Briefing text.",
        }]
    })
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
        first = top10.generate_briefings(stories, client_factory=lambda: client)
        second = top10.generate_briefings(stories, client_factory=lambda: client)
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


def test_briefing_downgrades_confirmed_conflict_without_claim_backing():
    def briefing_provider(stories):
        return {
            "Example Story": {
                "briefing": "Briefing text.",
                "delta_summary": "First detected today.",
                "status": "disputed",
                "confidence": "medium",
                "source_agreement": "mixed",
                "dispute_flag": "confirmed conflict",
            }
        }

    markdown = build_briefing_markdown([
        _briefing_article(1, "Economy", "Example Story", 4),
    ], briefing_provider=briefing_provider)

    assert "**Dispute:** Possible Conflict" in markdown
    assert "**Dispute:** Confirmed Conflict" not in markdown


def test_briefing_default_source_agreement_uses_source_id():
    first = _briefing_article(1, "Economy", "Example Story", 4, source="Reuters")
    first["source_id"] = 1
    second = _briefing_article(2, "Economy", "Example Story", 4, source="Reuters Copy")
    second["source_id"] = 1

    markdown = build_briefing_markdown(
        [first, second],
        briefing_provider=lambda stories: {},
    )

    assert "**Source agreement:** Single Source" in markdown


def test_get_briefings_sends_claims_when_evidence_enabled(tmp_path):
    db_path = tmp_path / "stories.db"
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
    extract_and_save_claims(
        [article],
        db_path=db_path,
        client_factory=lambda: claim_client,
        verify_claim=lambda c, s: True,
    )

    captured = []
    briefing_client = FakeLLMClient({
        "briefings": [{
            "canonical_label": "Example Story",
            "delta_summary": "First detected today.",
            "briefing": "Briefing text.",
        }]
    }, capture=captured)
    top10.generate_briefings(
        [{
            "canonical_label": "Example Story",
            "story_id": 42,
            "articles": [article],
        }],
        include_evidence=True,
        client_factory=lambda: briefing_client,
        claims_provider=lambda story_id, **kwargs: claims_module.get_claims_for_story(
            story_id,
            db_path=db_path,
            **kwargs,
        ),
    )

    items = json.loads(captured[0]["messages"][1]["content"])
    assert items[0]["claims"][0]["claim_text"] == "Example Story has a concrete supported claim."
    assert items[0]["claims"][0]["evidence_span"] == "Concrete supported claim."


def test_get_briefings_uses_claim_backed_source_agreement():
    def claims_provider(story_id, **kwargs):
        return [
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
        ]
    captured = []
    briefing_client = FakeLLMClient({
        "briefings": [{
            "canonical_label": "Example Story",
            "delta_summary": "First detected today.",
            "briefing": "Briefing text.",
            "source_agreement": "broad",
        }]
    }, capture=captured)

    first = _briefing_article(1, "Economy", "Example Story", 4, source="Source A")
    first["source_id"] = 101
    second = _briefing_article(2, "Economy", "Example Story", 4, source="Source B")
    second["source_id"] = 202

    result = top10.generate_briefings(
        [{
            "canonical_label": "Example Story",
            "story_id": 42,
            "articles": [first, second],
        }],
        include_evidence=True,
        client_factory=lambda: briefing_client,
        claims_provider=claims_provider,
    )

    item = json.loads(captured[0]["messages"][1]["content"])[0]
    assert item["claims"][0]["source_id"] == 101
    assert item["claims"][1]["source_id"] == 202
    assert item["claim_source_agreement"]["label"] == "partial"
    assert item["claim_source_agreement"]["basis"] == "repeated-claim-partial"
    assert result["Example Story"]["source_agreement"] == "partial"


def test_get_briefings_forces_possible_conflict_for_claim_number_divergence():
    def claims_provider(story_id, **kwargs):
        return [
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
        ]
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

    first = _briefing_article(1, "Other", "Example Story", 4, source="Source A")
    first["source_id"] = 101
    second = _briefing_article(2, "Other", "Example Story", 4, source="Source B")
    second["source_id"] = 202

    result = top10.generate_briefings(
        [{
            "canonical_label": "Example Story",
            "story_id": 42,
            "articles": [first, second],
        }],
        include_evidence=True,
        client_factory=lambda: briefing_client,
        claims_provider=claims_provider,
    )

    items = json.loads(captured[0]["messages"][1]["content"])
    assert items[0]["claim_source_agreement"]["source_divergence_notes"]
    assert result["Example Story"]["source_agreement"] == "mixed"
    assert result["Example Story"]["dispute_flag"] == "possible conflict"


def test_get_briefings_batches_stories_and_caps_articles():
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

    result = top10.generate_briefings(stories, client_factory=lambda: client)

    assert client.calls == 2
    sent_batches = [json.loads(call["messages"][1]["content"]) for call in captured]
    assert [len(batch) for batch in sent_batches] == [8, 1]
    assert len(sent_batches[0][0]["articles"]) == 6
    assert len(result) == 9


def test_briefing_numeric_grounding_guard_replaces_unsupported_number():
    client = FakeLLMClient({
        "briefings": [{
            "canonical_label": "Example Story",
            "delta_summary": "Officials reported 99 casualties.",
            "briefing": "The event caused 99 casualties.",
        }]
    })
    story = {
        "canonical_label": "Example Story",
        "story_id": 42,
        "source_count": 1,
        "articles": [_briefing_article(1, "Other", "Example Story")],
    }

    result = top10.generate_briefings([story], client_factory=lambda: client)

    assert "99" not in result["Example Story"]["briefing"]
    assert "99" not in result["Example Story"]["delta_summary"]
    assert result["Example Story"]["confidence"] == "low"
    assert "unsupported numeric detail" in result["Example Story"]["open_questions"][0]


def test_numeric_guard_does_not_use_articles_omitted_from_prompt():
    captured = []
    client = FakeLLMClient({
        "briefings": [{
            "canonical_label": "Example Story",
            "delta_summary": "Officials reported 99 casualties.",
            "briefing": "The event caused 99 casualties.",
        }]
    }, capture=captured)
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

    result = top10.generate_briefings([story], client_factory=lambda: client)

    sent = json.loads(captured[0]["messages"][1]["content"])
    assert "99" not in json.dumps(sent)
    assert "99" not in result["Example Story"]["briefing"]


def test_numeric_guard_removes_unsupported_open_question_number():
    client = FakeLLMClient({
        "briefings": [{
            "canonical_label": "Example Story",
            "delta_summary": "First detected today.",
            "briefing": "A grounded briefing without figures.",
            "open_questions": ["Will the toll reach 99?", "What happens next?"],
        }]
    })
    story = {
        "canonical_label": "Example Story",
        "story_id": 42,
        "source_count": 1,
        "articles": [_briefing_article(1, "Other", "Example Story")],
    }

    result = top10.generate_briefings(
        [story],
        client_factory=lambda: client,
    )["Example Story"]

    assert all("99" not in question for question in result["open_questions"])
    assert "What happens next?" in result["open_questions"]
    assert result["confidence"] == "low"


def test_local_dispute_flag_ignores_ordinary_denial_and_rejection_language():
    story = {
        "canonical_label": "Court rejected appeal",
        "articles": [{
            "title": "Court rejected the appeal",
            "description": "The minister denied entry after the ruling.",
        }],
    }

    assert briefing_generation.local_dispute_flag(story) == "none"


def test_local_dispute_flag_requires_explicit_divergence_language():
    story = {
        "canonical_label": "Blast toll",
        "articles": [{
            "title": "Conflicting reports emerge",
            "description": "Sources disagree about the reported toll.",
        }],
    }

    assert briefing_generation.local_dispute_flag(story) == "possible conflict"

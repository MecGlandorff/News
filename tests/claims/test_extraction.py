import sqlite3

import src.claims as claims_module
from src.claims import extract_and_save_claims, get_claims_for_story
from tests.claims.support import ARTICLE, CLAIM_RESPONSE, _fake_client
from tests.fakes import FakeLLMClient


def _extract(db_path, tracked, client, *, verify_claim=None):
    return extract_and_save_claims(
        tracked,
        db_path=db_path,
        client_factory=lambda: client,
        verify_claim=verify_claim,
    )


def _saved_claims(db_path, story_id=42):
    return get_claims_for_story(story_id, db_path=db_path)


def test_extract_and_save_claims_skips_empty_tracked():
    # Should not raise and not call LLM
    extract_and_save_claims([])


def test_extract_saves_claims_and_caches(tmp_path):
    db_path = tmp_path / "stories.db"
    client = _fake_client(CLAIM_RESPONSE)
    _extract(db_path, [ARTICLE], client)

    assert client.calls == 1
    saved = _saved_claims(db_path)
    assert len(saved) == 2
    assert saved[0]["claim_type"] == "number"
    assert "3.67%" in saved[0]["evidence_span"]


def test_extract_uses_full_article_text_and_nano_model(tmp_path):
    db_path = tmp_path / "stories.db"
    full_text = "Full article says Iran submitted a written offer to inspectors."
    response = {
        "claims": [
            {
                "claim_text": "Iran submitted a written offer to inspectors.",
                "claim_type": "fact",
                "entities": ["Iran"],
                "evidence_span": full_text,
                "confidence": 0.9,
            }
        ]
    }
    captured = []
    client = FakeLLMClient(response, capture=captured)

    article = {
        **ARTICLE,
        "id": "article-full-text",
        "description": "RSS summary without the written-offer evidence.",
        "text": full_text,
    }
    _extract(db_path, [article], client)

    saved = _saved_claims(db_path)
    assert captured[0]["model"] == "gpt-5.4-nano"
    assert full_text in captured[0]["messages"][1]["content"]
    assert len(saved) == 1
    assert saved[0]["evidence_span"] == full_text


def test_claim_prompt_targets_reviewed_quality_failures():
    prompt = claims_module.CLAIMS_PROMPT

    assert claims_module.CLAIMS_PROMPT_VERSION == "2026-05-13-v1"
    assert "preserve the attribution" in prompt
    assert "Background identity labels" in prompt
    assert "must not add facts beyond the evidence_span" in prompt
    assert "Split long sentences" in prompt


def test_extract_skips_already_cached(tmp_path):
    db_path = tmp_path / "stories.db"
    client = _fake_client(CLAIM_RESPONSE)
    _extract(db_path, [ARTICLE], client)
    _extract(db_path, [ARTICLE], client)  # second call — should hit cache

    assert client.calls == 1


def test_extract_caches_zero_claim_results(tmp_path):
    db_path = tmp_path / "stories.db"
    client = _fake_client({"claims": []})
    first = _extract(db_path, [ARTICLE], client)
    second = _extract(db_path, [ARTICLE], client)

    assert client.calls == 1
    assert _saved_claims(db_path) == []
    assert first["zero_claim_results"] == 1
    assert second["cached"] == 1


def test_extract_rejects_invalid_or_ungrounded_claims(tmp_path):
    db_path = tmp_path / "stories.db"
    response = {
        "claims": [
            {
                "claim_text": "Officials confirmed the offer.",
                "claim_type": "fact",
                "entities": [],
                "evidence_span": "Officials confirmed the offer.",
                "confidence": 0.8,
            },
            {
                "claim_text": "Iran proposed a deal.",
                "claim_type": "rumor",
                "entities": ["Iran"],
                "evidence_span": "Iran proposed capping enrichment at 3.67%.",
                "confidence": 0.7,
            },
            {
                "claim_text": "Iran proposed a deal.",
                "claim_type": "fact",
                "entities": ["Iran"],
                "evidence_span": "",
                "confidence": 0.7,
            },
            {
                "claim_text": "Iran signed a final agreement.",
                "claim_type": "fact",
                "entities": ["Iran"],
                "evidence_span": "Iran signed a final agreement.",
                "confidence": 0.7,
            },
            {
                "claim_text": "Iran proposed a deal.",
                "claim_type": "fact",
                "entities": ["Iran"],
                "evidence_span": "Iran proposed capping enrichment at 3.67%.",
                "confidence": "high",
            },
            {
                "claim_text": "Iran proposed a deal.",
                "claim_type": "fact",
                "entities": "Iran",
                "evidence_span": "Iran proposed capping enrichment at 3.67%.",
                "confidence": 0.7,
            },
        ]
    }
    client = _fake_client(response)
    _extract(db_path, [ARTICLE], client)

    saved = _saved_claims(db_path)
    assert len(saved) == 1
    assert saved[0]["claim_text"] == "Officials confirmed the offer."
    assert saved[0]["evidence_span"] == "Officials confirmed the offer."


def test_extract_does_not_cache_schema_failures(tmp_path):
    db_path = tmp_path / "stories.db"
    client = _fake_client({"claims": {"claim_text": "not a list"}})
    _extract(db_path, [ARTICLE], client)
    _extract(db_path, [ARTICLE], client)

    assert client.calls == 2
    assert _saved_claims(db_path) == []


def test_content_change_invalidates_stale_claims_before_retry(tmp_path):
    db_path = tmp_path / "stories.db"
    client = _fake_client(CLAIM_RESPONSE)
    _extract(db_path, [ARTICLE], client)
    assert len(_saved_claims(db_path)) == 2

    def raise_llm(kwargs):
        raise RuntimeError("LLM down")

    failing_client = FakeLLMClient(raise_llm)
    _extract(db_path, [{**ARTICLE, "description": "Updated article text."}], failing_client)

    assert _saved_claims(db_path) == []


def test_extract_handles_llm_failure_gracefully(tmp_path):
    db_path = tmp_path / "stories.db"
    def boom(kwargs):
        raise RuntimeError("LLM down")

    client = FakeLLMClient(boom)

    # Should not raise — failure is logged and skipped
    _extract(db_path, [ARTICLE], client)

    assert _saved_claims(db_path) == []


def test_extract_drops_claims_with_number_mismatch_before_calling_verifier(tmp_path):
    db_path = tmp_path / "stories.db"
    article = {
        **ARTICLE,
        "id": "number-mismatch-article",
        "description": "Iran proposed capping enrichment at 5.00%.",
    }
    response = {
        "claims": [
            {
                "claim_text": "Iran proposed capping enrichment at 3.67%.",
                "claim_type": "number",
                "entities": ["Iran"],
                "evidence_span": "Iran proposed capping enrichment at 5.00%.",
                "confidence": 0.9,
            }
        ]
    }
    client = _fake_client(response)

    verifier_called = []
    def verify_claim(claim_text, evidence_span):
        verifier_called.append((claim_text, evidence_span))
        return True

    stats = _extract(db_path, [article], client, verify_claim=verify_claim)

    assert verifier_called == []
    assert _saved_claims(db_path) == []
    assert stats["claim_derivable_accepts"] == 0
    assert stats["claim_verifier_calls"] == 0


def test_extract_calls_verifier_for_paraphrase_and_keeps_supported_claims(tmp_path):
    db_path = tmp_path / "stories.db"
    article = {
        **ARTICLE,
        "id": "paraphrase-article",
        "description": "Senior diplomats expressed concern about regional tensions.",
    }
    response = {
        "claims": [
            {
                "claim_text": "Officials warned about escalation risk.",
                "claim_type": "fact",
                "entities": [],
                "evidence_span": "Senior diplomats expressed concern about regional tensions.",
                "confidence": 0.7,
            }
        ]
    }
    client = _fake_client(response)

    verifier_calls = []

    def fake_verifier(claim_text, evidence_span):
        verifier_calls.append((claim_text, evidence_span))
        return True

    stats = _extract(db_path, [article], client, verify_claim=fake_verifier)

    assert len(verifier_calls) == 1
    saved = _saved_claims(db_path)
    assert len(saved) == 1
    assert saved[0]["claim_text"] == "Officials warned about escalation risk."
    assert stats["claim_verifier_calls"] == 1
    assert stats["claim_verifier_accepts"] == 1
    assert stats["claim_verifier_rejects"] == 0


def test_extract_drops_paraphrase_claims_when_verifier_rejects(tmp_path):
    db_path = tmp_path / "stories.db"
    article = {
        **ARTICLE,
        "id": "paraphrase-rejected",
        "description": "Senior diplomats expressed concern about regional tensions.",
    }
    response = {
        "claims": [
            {
                "claim_text": "Officials warned about escalation risk.",
                "claim_type": "fact",
                "entities": [],
                "evidence_span": "Senior diplomats expressed concern about regional tensions.",
                "confidence": 0.7,
            }
        ]
    }
    client = _fake_client(response)

    stats = _extract(db_path, [article], client, verify_claim=lambda c, s: False)

    assert _saved_claims(db_path) == []
    assert stats["claim_verifier_calls"] == 1
    assert stats["claim_verifier_accepts"] == 0
    assert stats["claim_verifier_rejects"] == 1


def test_extract_routes_weak_entity_overlap_to_verifier(tmp_path):
    db_path = tmp_path / "stories.db"
    article = {
        **ARTICLE,
        "id": "anaphoric-span",
        "description": (
            "The Marek foreign ministry alleged Lydora had moved artillery near "
            "the Kars crossing, a claim Lydora denied."
        ),
    }
    response = {
        "claims": [
            {
                "claim_text": (
                    "Lydora denied the Marek foreign ministry's allegation about "
                    "moving artillery near the Kars crossing."
                ),
                "claim_type": "allegation",
                "entities": ["Lydora", "Marek", "Kars"],
                "evidence_span": "a claim Lydora denied.",
                "confidence": 0.84,
            }
        ]
    }
    client = _fake_client(response)

    verifier_calls = []

    def fake_verifier(claim_text, evidence_span):
        verifier_calls.append((claim_text, evidence_span))
        return False

    stats = _extract(db_path, [article], client, verify_claim=fake_verifier)

    assert len(verifier_calls) == 1
    assert _saved_claims(db_path) == []
    assert stats["claim_derivable_accepts"] == 0
    assert stats["claim_verifier_calls"] == 1
    assert stats["claim_verifier_rejects"] == 1


def test_cheap_accept_counter_increments_only_for_verbatim_claims(tmp_path):
    db_path = tmp_path / "stories.db"
    client = _fake_client(CLAIM_RESPONSE)

    verifier_calls = []
    def verify_claim(claim_text, evidence_span):
        verifier_calls.append((claim_text, evidence_span))
        return True

    stats = _extract(db_path, [ARTICLE], client, verify_claim=verify_claim)

    # Both fixture claims are exact spans and should avoid the verifier.
    assert verifier_calls == []
    assert stats["claim_derivable_accepts"] == 2
    assert stats["claim_verifier_calls"] == 0


def test_validation_policy_change_invalidates_cached_extraction(tmp_path):
    db_path = tmp_path / "stories.db"
    client = _fake_client(CLAIM_RESPONSE)
    _extract(db_path, [ARTICLE], client)

    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE claim_extractions SET validation_version = 'old-policy'"
    )
    conn.execute("UPDATE claims SET validation_version = 'old-policy'")
    conn.commit()
    conn.close()

    _extract(db_path, [ARTICLE], client)

    assert client.calls == 2
    assert len(_saved_claims(db_path)) == 2


def test_extract_strips_html_from_description(tmp_path):
    db_path = tmp_path / "stories.db"

    captured_content = []
    client = FakeLLMClient({"claims": []}, capture=captured_content)

    html_article = {
        **ARTICLE,
        "id": "html-article",
        "description": "<p>Iran <b>offered</b> a deal.</p>",
    }
    _extract(db_path, [html_article], client)

    user_content = captured_content[0]["messages"][1]["content"]
    assert "<p>" not in user_content
    assert "<b>" not in user_content
    assert "Iran" in user_content


def test_claim_extraction_bounds_full_text_and_reports_truncation(tmp_path):
    db_path = tmp_path / "stories.db"
    captured = []
    client = FakeLLMClient({"claims": []}, capture=captured)
    article = {**ARTICLE, "id": "long-article", "text": "word " * 10_000}

    stats = _extract(db_path, [article], client)

    user_content = captured[0]["messages"][1]["content"]
    assert len(user_content) <= claims_module.CLAIMS_CONTENT_CHAR_LIMIT
    assert stats["content_truncations"] == 1

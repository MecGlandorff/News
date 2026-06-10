import json
import sqlite3

import src.claims as claims_module
from src.claims import extract_and_save_claims, get_claims_for_story
from fakes import FakeLLMClient


ARTICLE = {
    "id": "article-abc123",
    "story_id": 42,
    "source": "Reuters",
    "title": "Iran offers uranium deal",
    "description": "Iran proposed capping enrichment at 3.67%. Officials confirmed the offer.",
    "url": "https://reuters.com/iran",
    "published_at": "Fri, 1 May 2026 12:00:00 GMT",
}

CLAIM_RESPONSE = {
    "claims": [
        {
            "claim_text": "Iran proposed capping uranium enrichment at 3.67%.",
            "claim_type": "number",
            "entities": ["Iran"],
            "evidence_span": "Iran proposed capping enrichment at 3.67%.",
            "confidence": 0.95,
        },
        {
            "claim_text": "Officials confirmed the offer.",
            "claim_type": "fact",
            "entities": [],
            "evidence_span": "Officials confirmed the offer.",
            "confidence": 0.8,
        },
    ]
}


def _fake_client(response_content):
    return FakeLLMClient(response_content)


def _fake_response(response_content):
    class Message:
        content = json.dumps(response_content)

    class Choice:
        message = Message()

    class Response:
        choices = [Choice()]

    return Response()


def test_extract_and_save_claims_skips_empty_tracked():
    # Should not raise and not call LLM
    extract_and_save_claims([])


def test_extract_saves_claims_and_caches(tmp_path, monkeypatch):
    monkeypatch.setattr(claims_module, "DB_PATH", tmp_path / "stories.db")

    client = _fake_client(CLAIM_RESPONSE)
    monkeypatch.setattr(claims_module, "get_openai_client", lambda: client)

    extract_and_save_claims([ARTICLE])

    assert client.calls == 1
    saved = get_claims_for_story(42)
    assert len(saved) == 2
    assert saved[0]["claim_type"] == "number"
    assert "3.67%" in saved[0]["evidence_span"]


def test_extract_uses_full_article_text_and_nano_model(tmp_path, monkeypatch):
    monkeypatch.setattr(claims_module, "DB_PATH", tmp_path / "stories.db")

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
    monkeypatch.setattr(claims_module, "get_openai_client", lambda: client)

    article = {
        **ARTICLE,
        "id": "article-full-text",
        "description": "RSS summary without the written-offer evidence.",
        "text": full_text,
    }
    extract_and_save_claims([article])

    saved = get_claims_for_story(42)
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


def test_extract_skips_already_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(claims_module, "DB_PATH", tmp_path / "stories.db")

    client = _fake_client(CLAIM_RESPONSE)
    monkeypatch.setattr(claims_module, "get_openai_client", lambda: client)

    extract_and_save_claims([ARTICLE])
    extract_and_save_claims([ARTICLE])  # second call — should hit cache

    assert client.calls == 1


def test_extract_caches_zero_claim_results(tmp_path, monkeypatch):
    monkeypatch.setattr(claims_module, "DB_PATH", tmp_path / "stories.db")

    client = _fake_client({"claims": []})
    monkeypatch.setattr(claims_module, "get_openai_client", lambda: client)

    first = extract_and_save_claims([ARTICLE])
    second = extract_and_save_claims([ARTICLE])

    assert client.calls == 1
    assert get_claims_for_story(42) == []
    assert first["zero_claim_results"] == 1
    assert second["cached"] == 1


def test_extract_rejects_invalid_or_ungrounded_claims(tmp_path, monkeypatch):
    monkeypatch.setattr(claims_module, "DB_PATH", tmp_path / "stories.db")

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
    monkeypatch.setattr(claims_module, "get_openai_client", lambda: client)

    extract_and_save_claims([ARTICLE])

    saved = get_claims_for_story(42)
    assert len(saved) == 1
    assert saved[0]["claim_text"] == "Officials confirmed the offer."
    assert saved[0]["evidence_span"] == "Officials confirmed the offer."


def test_extract_does_not_cache_schema_failures(tmp_path, monkeypatch):
    monkeypatch.setattr(claims_module, "DB_PATH", tmp_path / "stories.db")

    client = _fake_client({"claims": {"claim_text": "not a list"}})
    monkeypatch.setattr(claims_module, "get_openai_client", lambda: client)

    extract_and_save_claims([ARTICLE])
    extract_and_save_claims([ARTICLE])

    assert client.calls == 2
    assert get_claims_for_story(42) == []


def test_get_claims_for_story_ignores_old_prompt_versions(tmp_path, monkeypatch):
    monkeypatch.setattr(claims_module, "DB_PATH", tmp_path / "stories.db")

    client = _fake_client(CLAIM_RESPONSE)
    monkeypatch.setattr(claims_module, "get_openai_client", lambda: client)
    extract_and_save_claims([ARTICLE])

    conn = sqlite3.connect(tmp_path / "stories.db")
    conn.execute(
        """
        INSERT INTO claims (
            article_id, story_id, claim_text, claim_type, entities,
            evidence_span, confidence, prompt_version
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ARTICLE["id"],
            ARTICLE["story_id"],
            "Old cached claim.",
            "fact",
            "[]",
            "Old cached evidence.",
            0.99,
            "old-version",
        ),
    )
    conn.commit()
    conn.close()

    saved = get_claims_for_story(42)
    assert len(saved) == 2
    assert "Old cached claim." not in [claim["claim_text"] for claim in saved]


def test_cached_claims_follow_story_reassignment(tmp_path, monkeypatch):
    monkeypatch.setattr(claims_module, "DB_PATH", tmp_path / "stories.db")

    client = _fake_client(CLAIM_RESPONSE)
    monkeypatch.setattr(claims_module, "get_openai_client", lambda: client)

    extract_and_save_claims([ARTICLE])
    extract_and_save_claims([{**ARTICLE, "story_id": 84}])

    assert client.calls == 1
    assert get_claims_for_story(42) == []
    assert len(get_claims_for_story(84)) == 2


def test_content_change_invalidates_stale_claims_before_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(claims_module, "DB_PATH", tmp_path / "stories.db")

    client = _fake_client(CLAIM_RESPONSE)
    monkeypatch.setattr(claims_module, "get_openai_client", lambda: client)
    extract_and_save_claims([ARTICLE])
    assert len(get_claims_for_story(42)) == 2

    def raise_llm(kwargs):
        raise RuntimeError("LLM down")

    monkeypatch.setattr(claims_module, "get_openai_client", lambda: FakeLLMClient(raise_llm))
    extract_and_save_claims([{**ARTICLE, "description": "Updated article text."}])

    assert get_claims_for_story(42) == []


def test_extract_handles_llm_failure_gracefully(tmp_path, monkeypatch):
    monkeypatch.setattr(claims_module, "DB_PATH", tmp_path / "stories.db")

    def boom(kwargs):
        raise RuntimeError("LLM down")

    monkeypatch.setattr(claims_module, "get_openai_client", lambda: FakeLLMClient(boom))

    # Should not raise — failure is logged and skipped
    extract_and_save_claims([ARTICLE])

    assert get_claims_for_story(42) == []


def test_get_claims_for_story_returns_empty_for_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(claims_module, "DB_PATH", tmp_path / "stories.db")
    assert get_claims_for_story(9999) == []


def test_derivability_check_rejects_when_claim_number_missing_from_span():
    decision = claims_module._derivability_check(
        "Iran proposed capping enrichment at 3.67%.",
        "Iran proposed capping enrichment at 5.00%.",
        ["Iran"],
    )
    assert decision == "reject"


def test_derivability_check_accepts_entity_overlap_with_strong_lexical_support():
    decision = claims_module._derivability_check(
        "Iran proposed capping enrichment at 3.67%.",
        "Iran proposed capping enrichment at 3.67 percent.",
        ["Iran"],
    )
    assert decision == "accept"


def test_derivability_check_routes_weak_entity_overlap_to_verifier():
    decision = claims_module._derivability_check(
        "Lydora denied the Marek foreign ministry's allegation about moving artillery near the Kars crossing.",
        "a claim Lydora denied.",
        ["Lydora", "Marek", "Kars"],
    )
    assert decision == "uncertain"


def test_derivability_check_accepts_claim_text_contained_in_span():
    decision = claims_module._derivability_check(
        "Officials confirmed the offer.",
        "Officials confirmed the offer.",
        [],
    )
    assert decision == "accept"


def test_derivability_check_uncertain_for_paraphrase_without_entity_overlap():
    decision = claims_module._derivability_check(
        "Officials warned about escalation risk.",
        "Senior diplomats expressed concern about regional tensions.",
        [],
    )
    assert decision == "uncertain"


def test_extract_drops_claims_with_number_mismatch_before_calling_verifier(tmp_path, monkeypatch):
    monkeypatch.setattr(claims_module, "DB_PATH", tmp_path / "stories.db")

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
    monkeypatch.setattr(claims_module, "get_openai_client", lambda: client)

    verifier_called = []
    monkeypatch.setattr(
        claims_module,
        "_verify_claim_with_llm",
        lambda c, s: verifier_called.append((c, s)) or True,
    )

    stats = extract_and_save_claims([article])

    assert verifier_called == []
    assert get_claims_for_story(42) == []
    assert stats["claim_derivable_accepts"] == 0
    assert stats["claim_verifier_calls"] == 0


def test_extract_calls_verifier_for_paraphrase_and_keeps_supported_claims(tmp_path, monkeypatch):
    monkeypatch.setattr(claims_module, "DB_PATH", tmp_path / "stories.db")

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
    monkeypatch.setattr(claims_module, "get_openai_client", lambda: client)

    verifier_calls = []

    def fake_verifier(claim_text, evidence_span):
        verifier_calls.append((claim_text, evidence_span))
        return True

    monkeypatch.setattr(claims_module, "_verify_claim_with_llm", fake_verifier)

    stats = extract_and_save_claims([article])

    assert len(verifier_calls) == 1
    saved = get_claims_for_story(42)
    assert len(saved) == 1
    assert saved[0]["claim_text"] == "Officials warned about escalation risk."
    assert stats["claim_verifier_calls"] == 1
    assert stats["claim_verifier_accepts"] == 1
    assert stats["claim_verifier_rejects"] == 0


def test_extract_drops_paraphrase_claims_when_verifier_rejects(tmp_path, monkeypatch):
    monkeypatch.setattr(claims_module, "DB_PATH", tmp_path / "stories.db")

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
    monkeypatch.setattr(claims_module, "get_openai_client", lambda: client)
    monkeypatch.setattr(claims_module, "_verify_claim_with_llm", lambda c, s: False)

    stats = extract_and_save_claims([article])

    assert get_claims_for_story(42) == []
    assert stats["claim_verifier_calls"] == 1
    assert stats["claim_verifier_accepts"] == 0
    assert stats["claim_verifier_rejects"] == 1


def test_extract_routes_weak_entity_overlap_to_verifier(tmp_path, monkeypatch):
    monkeypatch.setattr(claims_module, "DB_PATH", tmp_path / "stories.db")

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
    monkeypatch.setattr(claims_module, "get_openai_client", lambda: client)

    verifier_calls = []

    def fake_verifier(claim_text, evidence_span):
        verifier_calls.append((claim_text, evidence_span))
        return False

    monkeypatch.setattr(claims_module, "_verify_claim_with_llm", fake_verifier)

    stats = extract_and_save_claims([article])

    assert len(verifier_calls) == 1
    assert get_claims_for_story(42) == []
    assert stats["claim_derivable_accepts"] == 0
    assert stats["claim_verifier_calls"] == 1
    assert stats["claim_verifier_rejects"] == 1


def test_verifier_failure_default_rejects_the_claim(tmp_path, monkeypatch):
    monkeypatch.setattr(claims_module, "DB_PATH", tmp_path / "stories.db")

    article = {
        **ARTICLE,
        "id": "verifier-fail",
        "description": "Senior diplomats expressed concern.",
    }
    response = {
        "claims": [
            {
                "claim_text": "Officials warned about escalation risk.",
                "claim_type": "fact",
                "entities": [],
                "evidence_span": "Senior diplomats expressed concern.",
                "confidence": 0.7,
            }
        ]
    }
    client = _fake_client(response)
    monkeypatch.setattr(claims_module, "get_openai_client", lambda: client)

    def boom(claim_text, evidence_span):
        raise RuntimeError("verifier network error")

    # _verify_claim_with_llm catches errors and returns False, so simulate
    # that contract directly rather than letting the exception escape.
    monkeypatch.setattr(claims_module, "_verify_claim_with_llm", lambda c, s: False)

    stats = extract_and_save_claims([article])

    assert get_claims_for_story(42) == []
    assert stats["claim_verifier_rejects"] == 1


def test_verifier_explicit_false_is_a_reject_not_a_schema_failure(monkeypatch):
    response = _fake_response({"supported": False, "reason": "Not supported."})
    saved = []
    schema_failures = []

    monkeypatch.setattr(
        claims_module,
        "_verifier_completion",
        lambda claim_text, evidence_span: (response, {"cache": "metadata"}, False),
    )
    monkeypatch.setattr(
        claims_module,
        "save_cached_chat_completion",
        lambda metadata, response: saved.append((metadata, response)),
    )
    monkeypatch.setattr(
        claims_module,
        "mark_schema_failure",
        lambda *args, **kwargs: schema_failures.append((args, kwargs)),
    )

    supported = claims_module._verify_claim_with_llm("Claim.", "Evidence.")

    assert supported is False
    assert len(saved) == 1
    assert schema_failures == []


def test_verifier_malformed_supported_field_is_schema_failure_not_cached_false(monkeypatch):
    response = _fake_response({"supported": "false", "reason": "Wrong type."})
    saved = []
    schema_failures = []

    monkeypatch.setattr(
        claims_module,
        "_verifier_completion",
        lambda claim_text, evidence_span: (response, {"cache": "metadata"}, False),
    )
    monkeypatch.setattr(
        claims_module,
        "save_cached_chat_completion",
        lambda metadata, response: saved.append((metadata, response)),
    )
    monkeypatch.setattr(
        claims_module,
        "mark_schema_failure",
        lambda *args, **kwargs: schema_failures.append((args, kwargs)),
    )

    supported = claims_module._verify_claim_with_llm("Claim.", "Evidence.")

    assert supported is False
    assert saved == []
    assert len(schema_failures) == 1


def test_verifier_refreshes_malformed_cached_response(monkeypatch):
    cached_response = _fake_response({"supported": "false", "reason": "Wrong type."})
    fresh_response = _fake_response({"supported": True, "reason": "Supported."})
    saved = []
    refreshes = []

    monkeypatch.setattr(
        claims_module,
        "_verifier_completion",
        lambda claim_text, evidence_span: (cached_response, {"cache": "metadata"}, True),
    )

    def fresh_completion(claim_text, evidence_span):
        refreshes.append((claim_text, evidence_span))
        return fresh_response

    monkeypatch.setattr(claims_module, "_uncached_verifier_completion", fresh_completion)
    monkeypatch.setattr(
        claims_module,
        "save_cached_chat_completion",
        lambda metadata, response: saved.append((metadata, response)),
    )

    supported = claims_module._verify_claim_with_llm("Claim.", "Evidence.")

    assert supported is True
    assert refreshes == [("Claim.", "Evidence.")]
    assert saved == [({"cache": "metadata"}, fresh_response)]


def test_cheap_accept_counter_increments_for_entity_overlap(tmp_path, monkeypatch):
    monkeypatch.setattr(claims_module, "DB_PATH", tmp_path / "stories.db")

    client = _fake_client(CLAIM_RESPONSE)
    monkeypatch.setattr(claims_module, "get_openai_client", lambda: client)

    verifier_calls = []
    monkeypatch.setattr(
        claims_module,
        "_verify_claim_with_llm",
        lambda c, s: verifier_calls.append((c, s)) or True,
    )

    stats = extract_and_save_claims([ARTICLE])

    # Both fixture claims should hit the deterministic accept path.
    assert verifier_calls == []
    assert stats["claim_derivable_accepts"] == 2
    assert stats["claim_verifier_calls"] == 0


def test_extract_strips_html_from_description(tmp_path, monkeypatch):
    monkeypatch.setattr(claims_module, "DB_PATH", tmp_path / "stories.db")

    captured_content = []
    client = FakeLLMClient({"claims": []}, capture=captured_content)
    monkeypatch.setattr(claims_module, "get_openai_client", lambda: client)

    html_article = {
        **ARTICLE,
        "id": "html-article",
        "description": "<p>Iran <b>offered</b> a deal.</p>",
    }
    extract_and_save_claims([html_article])

    user_content = captured_content[0]["messages"][1]["content"]
    assert "<p>" not in user_content
    assert "<b>" not in user_content
    assert "Iran" in user_content

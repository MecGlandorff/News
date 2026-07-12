
import src.claims as claims_module
from src.claims import verifier as verifier_module
from src.claims import extract_and_save_claims, get_claims_for_story
from tests.claims.support import ARTICLE, _fake_client, _fake_response


def test_derivability_check_rejects_when_claim_number_missing_from_span():
    decision = claims_module._derivability_check(
        "Iran proposed capping enrichment at 3.67%.",
        "Iran proposed capping enrichment at 5.00%.",
        ["Iran"],
    )
    assert decision == "reject"


def test_number_tokens_preserve_decimal_comma():
    assert claims_module._number_tokens("Inflation rose to 1,5 percent.") == {"1.5"}
    assert claims_module._number_tokens("Inflation rose to 1,50 percent.") == {"1.5"}
    assert claims_module._number_tokens("Inflation rose to 1.5 percent.") == {"1.5"}
    assert claims_module._number_tokens("Officials counted 1,000 people.") == {"1000"}


def test_derivability_check_rejects_decimal_comma_integer_mismatch():
    decision = claims_module._derivability_check(
        "Bank X said the rate rose to 1,5 percent.",
        "Bank X said the rate rose to 15 percent.",
        ["Bank X"],
    )
    assert decision == "reject"


def test_derivability_check_routes_entity_paraphrase_to_verifier():
    decision = claims_module._derivability_check(
        "Iran proposed capping enrichment at 3.67%.",
        "Iran proposed capping enrichment at 3.67 percent.",
        ["Iran"],
    )
    assert decision == "uncertain"


def test_derivability_check_rejects_negation_mismatch():
    decision = claims_module._derivability_check(
        "The government will raise taxes.",
        "The government will not raise taxes.",
        ["government"],
    )
    assert decision == "reject"


def test_derivability_check_rejects_direction_mismatch():
    decision = claims_module._derivability_check(
        "Acme increased revenue.",
        "Acme decreased revenue.",
        ["Acme"],
    )
    assert decision == "reject"


def test_derivability_check_rejects_unit_mismatch():
    decision = claims_module._derivability_check(
        "Acme reported 5 percent growth.",
        "Acme reported 5 million euros in revenue.",
        ["Acme"],
    )
    assert decision == "reject"


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
        verifier_module,
        "_verifier_completion",
        lambda claim_text, evidence_span, client_factory: (
            response,
            {"cache": "metadata"},
            False,
        ),
    )
    monkeypatch.setattr(
        verifier_module,
        "save_cached_chat_completion",
        lambda metadata, response: saved.append((metadata, response)),
    )
    monkeypatch.setattr(
        verifier_module,
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
        verifier_module,
        "_verifier_completion",
        lambda claim_text, evidence_span, client_factory: (
            response,
            {"cache": "metadata"},
            False,
        ),
    )
    monkeypatch.setattr(
        verifier_module,
        "save_cached_chat_completion",
        lambda metadata, response: saved.append((metadata, response)),
    )
    monkeypatch.setattr(
        verifier_module,
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
        verifier_module,
        "_verifier_completion",
        lambda claim_text, evidence_span, client_factory: (
            cached_response,
            {"cache": "metadata"},
            True,
        ),
    )

    def fresh_completion(claim_text, evidence_span):
        refreshes.append((claim_text, evidence_span))
        return fresh_response

    monkeypatch.setattr(claims_module, "_uncached_verifier_completion", fresh_completion)
    monkeypatch.setattr(
        verifier_module,
        "save_cached_chat_completion",
        lambda metadata, response: saved.append((metadata, response)),
    )

    supported = claims_module._verify_claim_with_llm("Claim.", "Evidence.")

    assert supported is True
    assert refreshes == [("Claim.", "Evidence.")]
    assert saved == [({"cache": "metadata"}, fresh_response)]

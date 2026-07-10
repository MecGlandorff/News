import json

import pytest

from evals import run_claim_quality_eval as claim_eval


def test_claim_eval_compares_rss_and_full_text_inputs(monkeypatch):
    monkeypatch.setattr(claim_eval.claims, "_verify_claim_with_llm", lambda c, s: True)
    case = {
        "case_id": "riverbend",
        "article": {
            "title": "City orders evacuation near dam",
            "description": "Riverbend officials ordered evacuations after cracks were found at North Dam.",
            "text": (
                "Riverbend officials ordered evacuations for three neighborhoods after engineers "
                "found cracks at North Dam. Mayor Elena Cruz said the spillway would stay closed "
                "until Monday."
            ),
        },
        "expected_claims": [
            {
                "id": "evacuation_order",
                "required_terms": ["Riverbend", "evacuations", "North Dam"],
                "available_in": ["rss", "full_text"],
            },
            {
                "id": "spillway_closed",
                "required_terms": ["spillway", "Monday"],
                "available_in": ["full_text"],
            },
        ],
    }
    seen_inputs = []

    def extractor(content, client=None):
        seen_inputs.append(content)
        raw_claims = [
            {
                "claim_text": "Riverbend officials ordered evacuations near North Dam.",
                "claim_type": "fact",
                "entities": ["Riverbend", "North Dam"],
                "evidence_span": "Riverbend officials ordered evacuations after cracks were found at North Dam.",
                "confidence": 0.9,
            }
        ]
        if "spillway" in content:
            raw_claims.append({
                "claim_text": "The spillway would stay closed until Monday.",
                "claim_type": "fact",
                "entities": ["Elena Cruz"],
                "evidence_span": "Mayor Elena Cruz said the spillway would stay closed until Monday.",
                "confidence": 0.8,
            })
            return {
                "raw_claims": raw_claims,
                "latency_ms": 30,
                "prompt_tokens": 140,
                "completion_tokens": 45,
                "cost_eur": 0.002,
            }
        return {
            "raw_claims": raw_claims,
            "latency_ms": 10,
            "prompt_tokens": 80,
            "completion_tokens": 25,
            "cost_eur": 0.001,
        }

    report = claim_eval.run_eval([case], extractor=extractor)

    rss = report["summary"]["variants"]["rss"]
    full_text = report["summary"]["variants"]["full_text"]

    assert "spillway" not in seen_inputs[0]
    assert "spillway" in seen_inputs[1]
    assert rss["available_coverage"] == 1.0
    assert rss["article_coverage"] == 0.5
    assert full_text["available_coverage"] == 1.0
    assert full_text["article_coverage"] == 1.0
    assert report["summary"]["comparison"]["article_coverage_delta"] == 0.5
    assert report["summary"]["comparison"]["prompt_tokens_delta"] == 60
    assert report["summary"]["comparison"]["latency_ms_delta"] == pytest.approx(20, abs=2)


def test_claim_eval_counts_invalid_and_duplicate_claims():
    case = {
        "case_id": "duplicates",
        "article": {
            "title": "Officials confirm offer",
            "description": "Officials confirmed the offer.",
        },
        "expected_claims": [
            {
                "id": "offer_confirmed",
                "required_terms": ["Officials", "confirmed"],
                "available_in": ["rss", "full_text"],
            }
        ],
    }

    def extractor(content, client=None):
        return {
            "raw_claims": [
                {
                    "claim_text": "Officials confirmed the offer.",
                    "claim_type": "fact",
                    "entities": [],
                    "evidence_span": "Officials confirmed the offer.",
                    "confidence": 0.8,
                },
                {
                    "claim_text": "Officials confirmed the offer.",
                    "claim_type": "fact",
                    "entities": [],
                    "evidence_span": "Officials confirmed the offer.",
                    "confidence": 0.7,
                },
                {
                    "claim_text": "Officials signed the offer.",
                    "claim_type": "fact",
                    "entities": [],
                    "evidence_span": "Officials signed the offer.",
                    "confidence": 0.7,
                },
            ],
            "latency_ms": 5,
            "prompt_tokens": 30,
            "completion_tokens": 10,
            "cost_eur": 0.0001,
        }

    result = claim_eval.evaluate_variant(case, "rss", extractor=extractor)

    assert result["raw_claims_count"] == 3
    assert result["valid_claims_count"] == 2
    assert result["invalid_claims_count"] == 1
    assert result["duplicate_claims_count"] == 1
    assert result["evidence_valid_rate"] == pytest.approx(2 / 3)
    assert result["expected_match_rate"] == pytest.approx(1 / 2)


def test_claim_eval_matches_expected_claims_one_to_one():
    claims = [{
        "claim_text": "Officials approved the budget and tax plan.",
        "evidence_span": "Officials approved the budget and tax plan.",
    }]
    expected = [
        {"id": "budget", "required_terms": ["approved", "budget"]},
        {"id": "tax", "required_terms": ["approved", "tax plan"]},
    ]

    matched, matching_claim_count = claim_eval._matched_expected_ids(claims, expected)

    assert matched == ["budget"]
    assert matching_claim_count == 1


def test_claim_eval_one_to_one_matching_is_not_greedy():
    claims = [
        {
            "claim_text": "Officials approved the budget and tax plan.",
            "evidence_span": "Officials approved the budget and tax plan.",
        },
        {
            "claim_text": "Officials approved the budget.",
            "evidence_span": "Officials approved the budget.",
        },
    ]
    expected = [
        {"id": "budget", "required_terms": ["approved", "budget"]},
        {"id": "tax", "required_terms": ["approved", "tax plan"]},
    ]

    matched, matching_claim_count = claim_eval._matched_expected_ids(claims, expected)

    assert matched == ["budget", "tax"]
    assert matching_claim_count == 2


def test_claim_eval_treats_cached_verifier_usage_as_zero_tokens():
    metrics = [{"cache_hit": True, "prompt_tokens": None}]

    assert claim_eval._sum_metric(metrics, "prompt_tokens") == 0


def test_claim_eval_writes_report(tmp_path):
    report = {
        "created_at": "2026-05-10T00:00:00+00:00",
        "dataset": "in-memory",
        "case_count": 0,
        "model": "gpt-5.4-nano",
        "prompt_version": "test",
        "summary": {"variants": {}, "comparison": {}},
        "results": [],
    }

    output_path = claim_eval.write_report(report, tmp_path / "report.json")

    assert output_path.exists()
    assert json.loads(output_path.read_text(encoding="utf-8"))["model"] == "gpt-5.4-nano"


def test_prompt_regression_dataset_loads():
    path = "evals/datasets/claim_prompt_regressions_2026-05-13.jsonl"

    with open(path, encoding="utf-8") as handle:
        cases = [json.loads(line) for line in handle if line.strip()]

    assert len(cases) == 4
    assert {case["case_id"] for case in cases} == {
        "attribution-sensitive-battlefield-report",
        "identity-background-overreach",
        "multi-development-sentence",
        "analysis-thesis-background",
    }
    assert all(case["expected_behavior"] for case in cases)

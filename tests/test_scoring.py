import copy
import json
from pathlib import Path

import pytest

from evals.scoring import score_case

CASES = json.loads((Path(__file__).parents[1] / "evals" / "cases.json").read_text())
BY_ID = {case["id"]: case for case in CASES}


def response_for(case):
    articles = {article["id"]: article for article in case["input"]["articles"]}
    return {
        "events": [
            {
                "title": "Synthetic event label",
                "previous_event_id": case["expected"]["continuations"][group[0]],
                "article_ids": list(group),
                "evidence": [
                    {"article_id": article_id, "quote": articles[article_id]["text"]}
                    for article_id in group
                ],
            }
            for group in case["expected"]["groups"]
        ]
    }


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_labeled_partitions_pass_and_are_explicitly_synthetic(case):
    assert case["description"].startswith("SYNTHETIC:")
    assert all(article["url"].startswith("https://example.test/") for article in case["input"]["articles"])
    score = score_case(case, response_for(case))
    assert score["strict_pass"]
    assert score["valid"]
    assert score["exact_partition"]
    assert score["pairwise_f1"] == 1
    assert score["continuation_accuracy"] == 1
    assert score["evidence_coverage"] == 1
    assert score["evidence_quote_errors"] == 0
    assert not score["errors"]


def test_corpus_case_ids_are_unique():
    assert len(CASES) == len(BY_ID)
    assert 12 <= len(CASES) <= 20


def test_omitting_singleton_cannot_exploit_pairwise_metric():
    case = BY_ID["all_singletons"]
    response = response_for(case)
    del response["events"][0]
    score = score_case(case, response)
    assert score["pairwise_raw_f1"] == 1  # No pairs exist in either partition.
    assert score["pairwise_f1"] == 0
    assert score["omitted_article_ids"] == ["solo-a"]
    assert score["continuation_accuracy"] == pytest.approx(2 / 3)
    assert score["evidence_coverage"] == pytest.approx(2 / 3)
    assert not score["exact_partition"]
    assert not score["strict_pass"]


@pytest.mark.parametrize("duplicate_event", [False, True])
def test_duplicates_do_not_disappear_when_groups_are_converted_to_sets(duplicate_event):
    case = BY_ID["same_event_sources"]
    response = response_for(case)
    if duplicate_event:
        response["events"].append(copy.deepcopy(response["events"][0]))
    else:
        response["events"][0]["article_ids"].append("bridge-a")
    score = score_case(case, response)
    assert "bridge-a" in score["duplicate_article_ids"]
    assert score["pairwise_f1"] == 0
    assert score["continuation_accuracy"] < 1
    assert score["evidence_coverage"] < 1
    assert not score["exact_partition"]
    assert not score["valid"]


def test_unknown_article_is_not_silently_discarded():
    case = BY_ID["same_event_sources"]
    response = response_for(case)
    response["events"][0]["article_ids"].append("invented-id")
    score = score_case(case, response)
    assert score["unknown_article_ids"] == ["invented-id"]
    assert score["pairwise_f1"] == 0
    assert not score["exact_partition"]
    assert not score["strict_pass"]


def test_false_merge_reports_false_positive_pairs():
    case = BY_ID["same_event_sources"]
    response = response_for(case)
    bridge, park = response["events"]
    bridge["article_ids"] += park["article_ids"]
    bridge["evidence"] += park["evidence"]
    response["events"] = [bridge]
    score = score_case(case, response)
    assert score["valid"]  # The contract alone cannot detect a semantic false merge.
    assert score["pairwise_tp"] == 1
    assert score["pairwise_fp"] == 2
    assert score["pairwise_fn"] == 0
    assert score["pairwise_f1"] == pytest.approx(0.5)
    assert not score["exact_partition"]
    assert not score["strict_pass"]


def test_false_split_reports_false_negative_pairs():
    case = BY_ID["contradictory_reports"]
    original = response_for(case)["events"][0]
    response = {"events": []}
    for evidence in original["evidence"]:
        response["events"].append(
            {**original, "article_ids": [evidence["article_id"]], "evidence": [evidence]}
        )
    score = score_case(case, response)
    assert score["valid"]
    assert score["pairwise_tp"] == 0
    assert score["pairwise_fp"] == 0
    assert score["pairwise_fn"] == 1
    assert score["pairwise_f1"] == 0
    assert not score["strict_pass"]


def test_wrong_continuation_is_measured_separately_from_partition():
    case = BY_ID["multiple_memory_continuations"]
    response = response_for(case)
    response["events"][0]["previous_event_id"] = None
    score = score_case(case, response)
    assert score["valid"]
    assert score["exact_partition"]
    assert score["continuation_correct"] == 2
    assert score["continuation_total"] == 4
    assert score["continuation_accuracy"] == 0.5
    assert not score["strict_pass"]


def test_same_prior_event_cannot_be_used_for_two_current_events():
    case = BY_ID["multiple_memory_continuations"]
    response = response_for(case)
    response["events"][1]["previous_event_id"] = "mem-north"
    score = score_case(case, response)
    assert score["continuation_accuracy"] == 0.5
    assert not score["valid"]
    assert "A previous event is assigned to multiple current events" in score["errors"]


@pytest.mark.parametrize("previous", ["invented-event", 0, [], {}])
def test_unknown_or_malformed_prior_event_never_matches(previous):
    case = BY_ID["direct_followup_memory"]
    response = response_for(case)
    response["events"][0]["previous_event_id"] = previous
    score = score_case(case, response)
    assert not score["valid"]
    assert score["continuation_accuracy"] == pytest.approx(1 / 3)


@pytest.mark.parametrize("quote", ["invented quotation", "", "  ", None, [], {}, 12])
def test_non_exact_or_empty_quotes_reduce_coverage(quote):
    case = BY_ID["contradictory_reports"]
    response = response_for(case)
    response["events"][0]["evidence"][0]["quote"] = quote
    score = score_case(case, response)
    assert score["evidence_quote_errors"] == 1
    assert score["evidence_coverage"] == 0.5
    assert not score["valid"]


def test_quote_cannot_be_borrowed_from_title_or_another_article():
    case = BY_ID["same_event_sources"]
    for replacement in (case["input"]["articles"][0]["title"], case["input"]["articles"][1]["text"]):
        response = response_for(case)
        response["events"][0]["evidence"][0]["quote"] = replacement
        score = score_case(case, response)
        assert score["evidence_quote_errors"] == 1
        assert not score["strict_pass"]


def test_quote_cannot_be_borrowed_from_a_different_event():
    case = BY_ID["same_event_sources"]
    response = response_for(case)
    response["events"][0]["evidence"].append(response["events"][1]["evidence"][0])
    score = score_case(case, response)
    assert score["evidence_coverage"] == 1
    assert score["evidence_quote_errors"] == 1
    assert not score["valid"]


def test_exact_substring_does_not_claim_semantic_relevance():
    case = BY_ID["contradictory_reports"]
    response = response_for(case)
    response["events"][0]["evidence"][0]["quote"] = "800"
    response["events"][0]["title"] = "This unverified label could be misleading"
    # Deliberately demonstrates the limit: occurrence checks cannot prove grounding.
    assert score_case(case, response)["strict_pass"]


@pytest.mark.parametrize("response", [None, [], {}, {"events": None}, {"events": []}])
def test_empty_or_missing_output_scores_zero_complete_grouping(response):
    score = score_case(BY_ID["all_singletons"], response)
    assert score["pairwise_f1"] == 0
    assert score["continuation_accuracy"] == 0
    assert score["evidence_coverage"] == 0
    assert not score["strict_pass"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title", ""),
        ("title", []),
        ("article_ids", None),
        ("article_ids", []),
        ("article_ids", [{}]),
        ("evidence", None),
        ("evidence", []),
        ("evidence", [None]),
        ("evidence", [{"article_id": [], "quote": "bad"}]),
        ("evidence", [{"article_id": "crowd-a", "quote": "800", "extra": True}]),
    ],
)
def test_malformed_event_fields_are_rejected_without_crashing(field, value):
    case = BY_ID["contradictory_reports"]
    response = response_for(case)
    response["events"][0][field] = value
    assert not score_case(case, response)["valid"]


@pytest.mark.parametrize("field", ["title", "previous_event_id", "article_ids", "evidence"])
def test_missing_event_field_is_rejected(field):
    case = BY_ID["contradictory_reports"]
    response = response_for(case)
    del response["events"][0][field]
    assert not score_case(case, response)["valid"]


def test_extra_top_level_fields_and_non_object_events_are_rejected():
    case = BY_ID["all_singletons"]
    response = response_for(case)
    response["extra"] = "ignored?"
    assert not score_case(case, response)["valid"]
    response = response_for(case)
    response["events"].append(None)
    assert not score_case(case, response)["valid"]
    assert not score_case(case, response)["exact_partition"]


def test_broken_gold_labels_fail_loudly():
    case = copy.deepcopy(BY_ID["same_event_sources"])
    case["expected"]["groups"][0].append("not-an-input-article")
    with pytest.raises(ValueError, match="Invalid evaluation labels"):
        score_case(case, response_for(BY_ID["same_event_sources"]))

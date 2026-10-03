"""Deterministic checks against synthetic labels, not a semantic quality judge.

`score_case(case, response)` accepts the corpus case and an untrusted decoded
response. Pairwise counts use unique known article IDs. `pairwise_raw_f1` is the
ordinary pairwise score; `pairwise_f1` is zero when article coverage is malformed,
so dropping singleton articles cannot earn a perfect grouping score. Exact quote
checks prove text occurrence, not relevance, truth, or that the label is grounded.
"""

from collections import Counter
from itertools import combinations


def _pairs(groups: list[list[str]]) -> set[tuple[str, str]]:
    return {pair for group in groups for pair in combinations(sorted(set(group)), 2)}


def _gold(case: dict) -> tuple[dict, dict, list[list[str]], dict]:
    """Reject broken labels instead of accidentally measuring against them."""
    articles = case["input"]["articles"]
    by_id = {article["id"]: article for article in articles}
    memory = {event["id"]: event for event in case["input"]["memory"]}
    groups = case["expected"]["groups"]
    continuations = case["expected"]["continuations"]
    counts = Counter(article_id for group in groups for article_id in group)
    if (
        not by_id
        or len(by_id) != len(articles)
        or any(not group for group in groups)
        or counts != Counter({article_id: 1 for article_id in by_id})
        or set(continuations) != set(by_id)
        or any(value is not None and value not in memory for value in continuations.values())
        or any(len({continuations[article_id] for article_id in group}) != 1 for group in groups)
    ):
        raise ValueError("Invalid evaluation labels or article IDs")
    references = [continuations[group[0]] for group in groups]
    references = [reference for reference in references if reference is not None]
    if len(set(references)) != len(references):
        raise ValueError("Gold labels split a prior event across current events")
    return by_id, memory, groups, continuations


def score_case(case: dict, response: object) -> dict:
    """Score grouping, continuation, coverage, and quotes without calling a model."""
    articles, memory, gold_groups, gold_continuations = _gold(case)
    errors = []
    coverage_shape_ok = True
    if not isinstance(response, dict) or set(response) != {"events"}:
        errors.append("Response must contain only events")
    raw_events = response.get("events") if isinstance(response, dict) else None
    if not isinstance(raw_events, list):
        errors.append("events must be a list")
        coverage_shape_ok = False
        raw_events = []

    groups = []
    occurrences = Counter()
    assignments = {}
    previous_ids = []
    evidence_covered = set()
    quote_errors = 0
    for index, event in enumerate(raw_events):
        prefix = f"events[{index}]"
        if not isinstance(event, dict):
            errors.append(f"{prefix} must be an object")
            coverage_shape_ok = False
            continue
        if set(event) != {"title", "previous_event_id", "article_ids", "evidence"}:
            errors.append(f"{prefix} has missing or unexpected fields")
        if not isinstance(event.get("title"), str) or not event["title"].strip():
            errors.append(f"{prefix}.title must be a nonempty string")
        article_ids = event.get("article_ids")
        if not isinstance(article_ids, list) or not article_ids:
            errors.append(f"{prefix}.article_ids must be a nonempty list")
            coverage_shape_ok = False
            article_ids = []
        if any(not isinstance(article_id, str) for article_id in article_ids):
            errors.append(f"{prefix}.article_ids contains a non-string ID")
            coverage_shape_ok = False
        article_ids = [article_id for article_id in article_ids if isinstance(article_id, str)]
        occurrences.update(article_ids)
        known_ids = [article_id for article_id in article_ids if article_id in articles]
        groups.append(known_ids)

        previous = event.get("previous_event_id")
        previous_valid = "previous_event_id" in event and (
            previous is None or isinstance(previous, str) and previous in memory
        )
        if not previous_valid:
            errors.append(f"{prefix}.previous_event_id is missing or unknown")
        if isinstance(previous, str) and previous in memory:
            previous_ids.append(previous)
        for article_id in known_ids:
            assignments[article_id] = (previous, previous_valid)

        evidence = event.get("evidence")
        if not isinstance(evidence, list):
            errors.append(f"{prefix}.evidence must be a list")
            evidence = []
        event_covered = set()
        for quote_index, item in enumerate(evidence):
            quote_prefix = f"{prefix}.evidence[{quote_index}]"
            if not isinstance(item, dict) or set(item) != {"article_id", "quote"}:
                errors.append(f"{quote_prefix} must contain only article_id and quote")
                quote_errors += 1
                continue
            article_id = item["article_id"]
            quote = item["quote"]
            if (
                not isinstance(article_id, str)
                or article_id not in known_ids
                or not isinstance(quote, str)
                or not quote.strip()
                or quote not in articles[article_id]["text"]
            ):
                errors.append(f"{quote_prefix} is not an exact quote from its assigned article")
                quote_errors += 1
            else:
                event_covered.add(article_id)
        evidence_covered.update(event_covered)
        for article_id in sorted(set(known_ids) - event_covered):
            errors.append(f"{prefix} has no exact quote for {article_id}")

    omitted = sorted(set(articles) - set(occurrences))
    unknown = sorted(set(occurrences) - set(articles))
    duplicates = sorted(article_id for article_id, count in occurrences.items() if count > 1)
    for name, ids in (("omitted", omitted), ("unknown", unknown), ("duplicate", duplicates)):
        if ids:
            errors.append(f"{name} article IDs: {', '.join(ids)}")
    if len(previous_ids) != len(set(previous_ids)):
        errors.append("A previous event is assigned to multiple current events")
    coverage_ok = coverage_shape_ok and not (omitted or unknown or duplicates)

    expected_pairs = _pairs(gold_groups)
    actual_pairs = _pairs(groups)
    true_positive = len(actual_pairs & expected_pairs)
    false_positive = len(actual_pairs - expected_pairs)
    false_negative = len(expected_pairs - actual_pairs)
    precision = true_positive / len(actual_pairs) if actual_pairs else float(not expected_pairs)
    recall = true_positive / len(expected_pairs) if expected_pairs else 1.0
    denominator = 2 * true_positive + false_positive + false_negative
    raw_f1 = 2 * true_positive / denominator if denominator else 1.0
    exact_partition = coverage_ok and (
        {frozenset(group) for group in groups} == {frozenset(group) for group in gold_groups}
    )
    continuation_correct = sum(
        occurrences[article_id] == 1
        and article_id in assignments
        and assignments[article_id][1]
        and assignments[article_id][0] == gold_continuations[article_id]
        for article_id in articles
    )
    # Duplicate assignments are not successful coverage, even when one quote is exact.
    evidence_covered = {
        article_id for article_id in evidence_covered if occurrences[article_id] == 1
    }
    valid = not errors
    return {
        "pairwise_tp": true_positive,
        "pairwise_fp": false_positive,
        "pairwise_fn": false_negative,
        "pairwise_precision": precision,
        "pairwise_recall": recall,
        "pairwise_raw_f1": raw_f1,
        "pairwise_f1": raw_f1 if coverage_ok else 0.0,
        "exact_partition": exact_partition,
        "continuation_correct": continuation_correct,
        "continuation_total": len(articles),
        "continuation_accuracy": continuation_correct / len(articles),
        "evidence_articles_covered": len(evidence_covered),
        "evidence_coverage": len(evidence_covered) / len(articles),
        "evidence_quote_errors": quote_errors,
        "omitted_article_ids": omitted,
        "unknown_article_ids": unknown,
        "duplicate_article_ids": duplicates,
        "valid": valid,
        "strict_pass": valid and exact_partition and continuation_correct == len(articles),
        "errors": errors,
    }

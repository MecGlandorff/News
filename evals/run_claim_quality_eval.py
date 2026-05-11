import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from src import claims, pricing
from src.config import CLAIMS_MODEL


VARIANTS = ("rss", "full_text")
DEFAULT_DATASET = Path(__file__).parent / "datasets" / "golden_claims.jsonl"
DEFAULT_REPORT_DIR = Path(__file__).parent / "reports"


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _report_stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _ratio(numerator, denominator):
    if denominator == 0:
        return None
    return numerator / denominator


def _normalize_text(text):
    return " ".join(str(text or "").casefold().split())


def _usage_value(usage, name):
    if usage is None:
        return None
    if isinstance(usage, dict):
        return usage.get(name)
    return getattr(usage, name, None)


def _available_in(expected_claim):
    available = expected_claim.get("available_in") or list(VARIANTS)
    if isinstance(available, str):
        available = [available]
    return [str(item) for item in available]


def _case_id(case, index):
    return case.get("case_id") or f"case-{index + 1}"


def _validate_case(case, path, line_no):
    if not isinstance(case, dict):
        raise ValueError(f"{path}:{line_no} must be a JSON object")
    if not isinstance(case.get("article"), dict):
        raise ValueError(f"{path}:{line_no} must contain an article object")
    expected_claims = case.get("expected_claims")
    if not isinstance(expected_claims, list):
        raise ValueError(f"{path}:{line_no} must contain expected_claims list")
    for expected in expected_claims:
        if not isinstance(expected, dict):
            raise ValueError(f"{path}:{line_no} expected claims must be objects")
        if not expected.get("id"):
            raise ValueError(f"{path}:{line_no} expected claim is missing id")
        terms = expected.get("required_terms")
        if not isinstance(terms, list) or not terms:
            raise ValueError(f"{path}:{line_no} expected claim {expected.get('id')} needs required_terms")
        if not all(isinstance(term, str) and term.strip() for term in terms):
            raise ValueError(f"{path}:{line_no} expected claim {expected.get('id')} has invalid terms")
        invalid_variants = set(_available_in(expected)) - set(VARIANTS)
        if invalid_variants:
            raise ValueError(
                f"{path}:{line_no} expected claim {expected.get('id')} "
                f"has invalid availability: {sorted(invalid_variants)}"
            )


def load_cases(path):
    path = Path(path)
    cases = []
    with path.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            case = json.loads(stripped)
            _validate_case(case, path, line_no)
            cases.append(case)
    return cases


def _content_for_variant(article, variant):
    return claims.article_claim_content(article, include_full_text=variant == "full_text")


def _default_extractor(content, client=None):
    started = time.perf_counter()
    raw_claims, response = claims.call_claim_extractor(content, client=client)
    latency_ms = int((time.perf_counter() - started) * 1000)
    usage = getattr(response, "usage", None)
    prompt_tokens = _usage_value(usage, "prompt_tokens")
    completion_tokens = _usage_value(usage, "completion_tokens")
    cost_eur = None
    if prompt_tokens is not None and completion_tokens is not None:
        cost_eur = pricing.estimate_llm_cost_eur(CLAIMS_MODEL, prompt_tokens, completion_tokens)
    return {
        "raw_claims": raw_claims,
        "latency_ms": latency_ms,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cost_eur": cost_eur,
    }


def _duplicate_count(valid_claims):
    seen = set()
    duplicates = 0
    for claim in valid_claims:
        key = _normalize_text(claim.get("claim_text"))
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
    return duplicates


def _matches_expected_claim(claim, expected_claim):
    text = _normalize_text(
        f"{claim.get('claim_text', '')} {claim.get('evidence_span', '')}"
    )
    return all(_normalize_text(term) in text for term in expected_claim["required_terms"])


def _matched_expected_ids(valid_claims, expected_claims):
    matched = []
    matching_claims = set()
    for expected in expected_claims:
        for index, claim in enumerate(valid_claims):
            if _matches_expected_claim(claim, expected):
                matched.append(expected["id"])
                matching_claims.add(index)
                break
    return matched, len(matching_claims)


def _review_claim(claim):
    return {
        "claim_text": claim.get("claim_text"),
        "claim_type": claim.get("claim_type"),
        "entities": claim.get("entities", []),
        "evidence_span": claim.get("evidence_span"),
        "confidence": claim.get("confidence"),
    }


def evaluate_variant(case, variant, *, index=0, extractor=None, client=None):
    extractor = extractor or _default_extractor
    article = case["article"]
    expected_claims = case.get("expected_claims", [])
    available_expected = [
        expected for expected in expected_claims
        if variant in _available_in(expected)
    ]
    content = _content_for_variant(article, variant)
    rss_content = _content_for_variant(article, "rss")
    full_content = claims.article_claim_content(article, include_full_text=True)
    base = {
        "case_id": _case_id(case, index),
        "variant": variant,
        "input_source": variant,
        "input_chars": len(content),
        "has_full_text": bool(full_content != rss_content),
        "expected_claims_count": len(expected_claims),
        "available_expected_claims_count": len(available_expected),
        "error": None,
    }

    try:
        outcome = extractor(content, client=client)
    except Exception as exc:
        return {
            **base,
            "raw_claims_count": 0,
            "valid_claims_count": 0,
            "invalid_claims_count": 0,
            "duplicate_claims_count": 0,
            "matched_expected_claim_ids": [],
            "matched_available_expected_claim_ids": [],
            "expected_matching_claims_count": 0,
            "article_coverage": _ratio(0, len(expected_claims)),
            "available_coverage": _ratio(0, len(available_expected)),
            "evidence_valid_rate": None,
            "expected_match_rate": None,
            "latency_ms": None,
            "prompt_tokens": None,
            "completion_tokens": None,
            "cost_eur": None,
            "valid_claims": [],
            "error": str(exc),
        }

    raw_claims = outcome.get("raw_claims") or []
    valid_claims, invalid_count = claims.validate_claims_for_content(raw_claims, content)
    matched_ids, matched_claim_count = _matched_expected_ids(valid_claims, expected_claims)
    matched_available_ids, _matched_available_claim_count = _matched_expected_ids(
        valid_claims,
        available_expected,
    )
    duplicate_count = _duplicate_count(valid_claims)

    return {
        **base,
        "raw_claims_count": len(raw_claims),
        "valid_claims_count": len(valid_claims),
        "invalid_claims_count": invalid_count,
        "duplicate_claims_count": duplicate_count,
        "matched_expected_claim_ids": matched_ids,
        "matched_available_expected_claim_ids": matched_available_ids,
        "expected_matching_claims_count": matched_claim_count,
        "article_coverage": _ratio(len(matched_ids), len(expected_claims)),
        "available_coverage": _ratio(len(matched_available_ids), len(available_expected)),
        "evidence_valid_rate": _ratio(len(valid_claims), len(raw_claims)),
        "expected_match_rate": _ratio(matched_claim_count, len(valid_claims)),
        "latency_ms": outcome.get("latency_ms"),
        "prompt_tokens": outcome.get("prompt_tokens"),
        "completion_tokens": outcome.get("completion_tokens"),
        "cost_eur": outcome.get("cost_eur"),
        "valid_claims": [_review_claim(claim) for claim in valid_claims],
    }


def _sum_optional(results, key):
    values = [result.get(key) for result in results]
    if any(value is None for value in values):
        return None
    return sum(values)


def _summarize_variant(results):
    expected = sum(result["expected_claims_count"] for result in results)
    available_expected = sum(result["available_expected_claims_count"] for result in results)
    matched = sum(len(result["matched_expected_claim_ids"]) for result in results)
    matched_available = sum(len(result["matched_available_expected_claim_ids"]) for result in results)
    raw = sum(result["raw_claims_count"] for result in results)
    valid = sum(result["valid_claims_count"] for result in results)
    matching_claims = sum(result["expected_matching_claims_count"] for result in results)
    return {
        "cases": len(results),
        "errors": sum(1 for result in results if result.get("error")),
        "raw_claims": raw,
        "valid_claims": valid,
        "invalid_claims": sum(result["invalid_claims_count"] for result in results),
        "duplicate_claims": sum(result["duplicate_claims_count"] for result in results),
        "expected_claims": expected,
        "available_expected_claims": available_expected,
        "matched_expected_claims": matched,
        "matched_available_expected_claims": matched_available,
        "article_coverage": _ratio(matched, expected),
        "available_coverage": _ratio(matched_available, available_expected),
        "evidence_valid_rate": _ratio(valid, raw),
        "expected_match_rate": _ratio(matching_claims, valid),
        "latency_ms": _sum_optional(results, "latency_ms"),
        "prompt_tokens": _sum_optional(results, "prompt_tokens"),
        "completion_tokens": _sum_optional(results, "completion_tokens"),
        "cost_eur": _sum_optional(results, "cost_eur"),
    }


def _delta(left, right, key):
    left_value = left.get(key)
    right_value = right.get(key)
    if left_value is None or right_value is None:
        return None
    return right_value - left_value


def _comparison(summary):
    rss = summary["variants"].get("rss")
    full_text = summary["variants"].get("full_text")
    if not rss or not full_text:
        return {}
    return {
        "article_coverage_delta": _delta(rss, full_text, "article_coverage"),
        "available_coverage_delta": _delta(rss, full_text, "available_coverage"),
        "evidence_valid_rate_delta": _delta(rss, full_text, "evidence_valid_rate"),
        "valid_claims_delta": _delta(rss, full_text, "valid_claims"),
        "duplicate_claims_delta": _delta(rss, full_text, "duplicate_claims"),
        "latency_ms_delta": _delta(rss, full_text, "latency_ms"),
        "prompt_tokens_delta": _delta(rss, full_text, "prompt_tokens"),
        "completion_tokens_delta": _delta(rss, full_text, "completion_tokens"),
        "cost_eur_delta": _delta(rss, full_text, "cost_eur"),
    }


def run_eval(cases, *, dataset_path=None, extractor=None, client=None):
    if extractor is None and client is None:
        client = claims.get_openai_client()

    results = []
    for index, case in enumerate(cases):
        for variant in VARIANTS:
            results.append(evaluate_variant(
                case,
                variant,
                index=index,
                extractor=extractor,
                client=client,
            ))

    by_variant = {
        variant: _summarize_variant([result for result in results if result["variant"] == variant])
        for variant in VARIANTS
    }
    summary = {
        "variants": by_variant,
    }
    summary["comparison"] = _comparison(summary)
    return {
        "created_at": _utc_now(),
        "dataset": str(dataset_path) if dataset_path else None,
        "case_count": len(cases),
        "model": CLAIMS_MODEL,
        "prompt_version": claims.CLAIMS_PROMPT_VERSION,
        "summary": summary,
        "results": results,
    }


def write_report(report, output_path=None):
    if output_path is None:
        output_path = DEFAULT_REPORT_DIR / f"claim_quality_{_report_stamp()}.json"
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output_path


def _percent(value):
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%"


def _cost(value):
    return pricing.format_eur(value) if value is not None else "n/a"


def format_summary(report):
    lines = [
        "Claim quality eval",
        f"Dataset: {report['dataset'] or 'in-memory'}",
        f"Model: {report['model']} ({report['prompt_version']})",
        f"Cases: {report['case_count']}",
    ]
    for variant in VARIANTS:
        item = report["summary"]["variants"][variant]
        lines.append(
            f"{variant}: "
            f"article coverage {_percent(item['article_coverage'])}, "
            f"available coverage {_percent(item['available_coverage'])}, "
            f"valid evidence {_percent(item['evidence_valid_rate'])}, "
            f"duplicates {item['duplicate_claims']}, "
            f"tokens {item['prompt_tokens'] or 'n/a'}/{item['completion_tokens'] or 'n/a'}, "
            f"latency {item['latency_ms'] or 'n/a'}ms, "
            f"cost {_cost(item['cost_eur'])}"
        )
    comparison = report["summary"]["comparison"]
    lines.append(
        "full_text minus rss: "
        f"article coverage {_percent(comparison.get('article_coverage_delta'))}, "
        f"tokens {comparison.get('prompt_tokens_delta') if comparison.get('prompt_tokens_delta') is not None else 'n/a'}, "
        f"latency {comparison.get('latency_ms_delta') if comparison.get('latency_ms_delta') is not None else 'n/a'}ms, "
        f"cost {_cost(comparison.get('cost_eur_delta'))}"
    )
    return "\n".join(lines)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Compare RSS-only and full-text claim extraction quality."
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Print summary without writing a JSON report",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    cases = load_cases(args.dataset)
    if args.limit is not None:
        cases = cases[:args.limit]
    report = run_eval(cases, dataset_path=args.dataset)
    print(format_summary(report))
    if not args.no_write:
        output_path = write_report(report, args.output)
        print(f"Report written: {output_path}")
    return report


if __name__ == "__main__":
    main()

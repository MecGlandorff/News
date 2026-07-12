from pathlib import Path

from src import pricing
from src.observability.audit import novelty_audit
from src.observability.costs import llm_cost_summary
from src.observability.runs import get_run_report_data


RUN_ARTIFACTS_DIR = Path("run_artifacts")


def _markdown_number(value):
    return f"{int(value or 0):,}"


def _markdown_cost(value):
    return pricing.format_eur(value)


def _markdown_audit_story(item):
    reasons = ", ".join(item.get("penalty_reasons") or [])
    return (
        f"| {item['label']} | {item['theme']} | "
        f"{item['source_count']} | {item['importance_avg']:.1f} | "
        f"{item['score']:.1f} | {item.get('selection_score', item['score']):.1f} | "
        f"{item.get('selection_penalty', 0):.1f} | {reasons} |"
    )


def _markdown_audit_new_parent(item):
    development = item.get("development_label") or item["label"]
    return (
        f"| {item['label']} | {development} | {item['theme']} | "
        f"{item['source_count']} | {item['article_count']} | "
        f"{item['importance_avg']:.1f} | {item['score']:.1f} |"
    )


def _markdown_audit_candidate(item):
    return (
        f"| {item['label']} | {item['candidate_label']} | "
        f"{item['relationship']} | {item['confidence']} | "
        f"{item['source_count']} | {item['importance_avg']:.1f} |"
    )


def _markdown_audit_rejected(item):
    return (
        f"| {item['today_label']} | {item['candidate_label']} | "
        f"{item['relationship']} | {item['confidence']} |"
    )


def _markdown_audit_arc_attachment(item):
    score = "n/a" if item.get("chosen_score") is None else f"{item['chosen_score']}"
    return (
        f"| {item['today_label']} | {item['arc_label'] or item['arc_id']} | "
        f"{item['relationship']} | {item['confidence']} | "
        f"{score} | {item['arc_child_count']} |"
    )


def _markdown_audit_arc_rejected(item):
    if item["proposed_arc_label"]:
        target = item["proposed_arc_label"]
    elif item["arc_id"] is not None:
        target = f"arc {item['arc_id']}"
    else:
        target = "NEW_ARC"
    return (
        f"| {item['today_label']} | {target} | "
        f"{item['relationship']} | {item['confidence']} |"
    )


def _run_artifact_name(row):
    run_date = row["run_date"] or "unknown-date"
    return f"run_{run_date}_{row['run_id']}.md"


def run_report_markdown(run_id):
    row = get_run_report_data(run_id)
    if row is None:
        return f"# Run Report\n\nRun #{run_id} was not found.\n"

    seconds = (row["total_latency_ms"] or 0) / 1000
    cost = llm_cost_summary(run_id)
    undated_included = (
        (row["feed_items_missing_timestamp_included"] or 0)
        + (row["feed_items_unparseable_timestamp_included"] or 0)
    )
    undated_skipped = (
        (row["feed_items_missing_timestamp_skipped"] or 0)
        + (row["feed_items_unparseable_timestamp_skipped"] or 0)
    )
    lines = [
        f"# Run Report: {row['run_date'] or 'unknown date'}",
        "",
        "| Field | Value |",
        "|---|---:|",
        f"| Run | #{row['run_id']} |",
        f"| Date | {row['run_date'] or 'unknown date'} |",
        f"| Status | {row['status']} |",
        f"| Duration | {seconds:.1f}s |",
        "",
        "## Pipeline Totals",
        "",
        "| Metric | Count |",
        "|---|---:|",
        f"| Articles returned | {_markdown_number(row['articles_returned'])} |",
        f"| Duplicate URLs skipped | {_markdown_number(row['duplicate_url_skips'])} |",
        f"| Feed fetch failures | {_markdown_number(row['feed_fetch_failures'])} |",
        f"| Feed items outside date skipped | {_markdown_number(row['feed_items_outside_date_skipped'])} |",
        f"| Undated feed items included | {_markdown_number(undated_included)} |",
        f"| Undated feed items skipped | {_markdown_number(undated_skipped)} |",
        f"| Missing-timestamp feed items included | {_markdown_number(row['feed_items_missing_timestamp_included'])} |",
        f"| Unparseable-timestamp feed items included | {_markdown_number(row['feed_items_unparseable_timestamp_included'])} |",
        f"| Missing-timestamp feed items skipped | {_markdown_number(row['feed_items_missing_timestamp_skipped'])} |",
        f"| Unparseable-timestamp feed items skipped | {_markdown_number(row['feed_items_unparseable_timestamp_skipped'])} |",
        f"| Article text fetched | {_markdown_number(row['article_text_fetch_successes'])} |",
        f"| Article text failures | {_markdown_number(row['article_text_fetch_failures'])} |",
        f"| Claims saved | {_markdown_number(row['claims_saved'])} |",
        f"| Claims extracted | {_markdown_number(row['claim_articles_extracted'])} |",
        f"| Claims cached | {_markdown_number(row['claim_articles_cached'])} |",
        f"| Claims invalid | {_markdown_number(row['claim_invalid_dropped'])} |",
        f"| Claim failures | {_markdown_number(row['claim_extraction_failures'])} |",
        f"| Zero-claim results | {_markdown_number(row['claim_zero_results'])} |",
        f"| Claim cheap accepts | {_markdown_number(row['claim_derivable_accepts'])} |",
        f"| Claim verifier calls | {_markdown_number(row['claim_verifier_calls'])} |",
        f"| Claim verifier accepts | {_markdown_number(row['claim_verifier_accepts'])} |",
        f"| Claim verifier rejects | {_markdown_number(row['claim_verifier_rejects'])} |",
        f"| Claim input truncations | {_markdown_number(row['claim_content_truncations'])} |",
        f"| Stories touched | {_markdown_number(row['stories_touched'])} |",
        f"| Developments saved | {_markdown_number(row['story_developments_saved'])} |",
        f"| Parent attachments | {_markdown_number(row['story_parent_attachments'])} |",
        f"| Arc assignments | {_markdown_number(row['story_arc_assignments'])} |",
        f"| Arc attachments | {_markdown_number(row['story_arc_attachments'])} |",
        f"| New arcs | {_markdown_number(row['story_new_arcs'])} |",
        f"| New parent arcs | {_markdown_number(row['story_new_parent_arcs'])} |",
        f"| Unmatched new stories | {_markdown_number(row['story_unmatched_new_stories'])} |",
        f"| Story match checks | {_markdown_number(row['story_match_verifications'])} |",
        f"| Story match accepted | {_markdown_number(row['story_match_accepts'])} |",
        f"| Story match rejected | {_markdown_number(row['story_match_rejections'])} |",
        "",
        "## LLM Totals",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| LLM calls | {_markdown_number(row['llm_calls_count'])} |",
        f"| LLM errors | {_markdown_number(row['llm_errors_count'])} |",
        f"| LLM cache hits | {_markdown_number(row['llm_cache_hits'])} |",
        f"| Classification cache hits | {_markdown_number(row['classification_cache_hits'])} |",
        f"| Claim cache hits | {_markdown_number(row['claim_cache_hits'])} |",
        f"| Verifier cache hits | {_markdown_number(row['verifier_cache_hits'])} |",
        f"| Matching cache hits | {_markdown_number(row['matching_cache_hits'])} |",
        f"| Briefing cache hits | {_markdown_number(row['briefing_cache_hits'])} |",
        f"| Other cache hits | {_markdown_number(row['other_cache_hits'])} |",
        f"| Schema failures | {_markdown_number(row['schema_failures'])} |",
        f"| Application retries | {_markdown_number(row['retry_count'])} |",
        "| SDK retries | not exposed by client |",
        f"| Prompt tokens | {_markdown_number(row['prompt_tokens'])} |",
        f"| Completion tokens | {_markdown_number(row['completion_tokens'])} |",
    ]
    if cost["unpriced_models"]:
        lines.append(
            "| Estimated cost | "
            f"{_markdown_cost(cost['priced_cost_eur'])} priced; "
            f"unpriced models: {', '.join(cost['unpriced_models'])} |"
        )
    else:
        lines.append(f"| Estimated cost | {_markdown_cost(cost['total_cost_eur'])} |")

    lines.extend([
        "",
        "## LLM Calls By Purpose",
        "",
        "| Purpose | Calls | Prompt Tokens | Completion Tokens | Latency | Estimated Cost |",
        "|---|---:|---:|---:|---:|---:|",
    ])
    for item in cost["by_purpose"]:
        suffix = ""
        if item["unpriced_models"]:
            suffix = f" (unpriced: {', '.join(item['unpriced_models'])})"
        lines.append(
            f"| {item['purpose']} | "
            f"{_markdown_number(item['calls'])} | "
            f"{_markdown_number(item['prompt_tokens'])} | "
            f"{_markdown_number(item['completion_tokens'])} | "
            f"{(item['latency_ms'] or 0) / 1000:.1f}s | "
            f"{_markdown_cost(item['cost_eur'])}{suffix} |"
        )
    if not cost["by_purpose"]:
        lines.append("| None | 0 | 0 | 0 | 0.0s | EUR 0.0000 |")

    audit = novelty_audit(run_id)
    ratio = audit.get("new_parent_ratio")
    ratio_text = "n/a" if ratio is None else f"{ratio * 100:.1f}%"
    lines.extend([
        "",
        "## Novelty Audit",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| New parent arcs | {_markdown_number(audit.get('new_parent_arcs'))} |",
        f"| Developments | {_markdown_number(audit.get('developments'))} |",
        f"| New parent ratio | {ratio_text} |",
        "",
        "### High-Signal Not Displayed",
        "",
        "| Story | Theme | Sources | Importance | Base Score | Selection Score | Penalty | Penalty Reason |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ])
    if audit["high_signal_not_displayed"]:
        lines.extend(_markdown_audit_story(item) for item in audit["high_signal_not_displayed"])
    else:
        lines.append("| None |  | 0 | 0.0 | 0.0 | 0.0 | 0.0 |  |")

    lines.extend([
        "",
        "### High-Signal New Parent Arcs",
        "",
        "| Parent | Development | Theme | Sources | Articles | Importance | Score |",
        "|---|---|---|---:|---:|---:|---:|",
    ])
    if audit["high_signal_new_parent_arcs"]:
        lines.extend(_markdown_audit_new_parent(item) for item in audit["high_signal_new_parent_arcs"])
    else:
        lines.append("| None |  |  | 0 | 0 | 0.0 | 0.0 |")

    lines.extend([
        "",
        "### New Parent Arcs With Prior Candidates",
        "",
        "| New Parent | Prior Candidate | Relationship | Confidence | Sources | Importance |",
        "|---|---|---|---|---:|---:|",
    ])
    if audit["new_parent_arcs_with_candidates"]:
        lines.extend(_markdown_audit_candidate(item) for item in audit["new_parent_arcs_with_candidates"])
    else:
        lines.append("| None |  |  |  | 0 | 0.0 |")

    lines.extend([
        "",
        "### Rejected Related Matches",
        "",
        "| Today Label | Candidate | Relationship | Confidence |",
        "|---|---|---|---|",
    ])
    if audit["rejected_related_matches"]:
        lines.extend(_markdown_audit_rejected(item) for item in audit["rejected_related_matches"])
    else:
        lines.append("| None |  |  |  |")

    lines.extend([
        "",
        "### Arc Attachments To Review",
        "",
        "| Today Label | Arc | Relationship | Confidence | Chosen Score | Stories In Arc |",
        "|---|---|---|---|---:|---:|",
    ])
    if audit["arc_attachments_review"]:
        lines.extend(_markdown_audit_arc_attachment(item) for item in audit["arc_attachments_review"])
    else:
        lines.append("| None |  |  |  | 0 | 0 |")

    lines.extend([
        "",
        "### Rejected Arc Decisions",
        "",
        "| Today Label | Proposed Arc | Relationship | Confidence |",
        "|---|---|---|---|",
    ])
    if audit["rejected_arc_decisions"]:
        lines.extend(_markdown_audit_arc_rejected(item) for item in audit["rejected_arc_decisions"])
    else:
        lines.append("| None |  |  |  |")

    if row["error_message"]:
        lines.extend([
            "",
            "## Error",
            "",
            str(row["error_message"]),
        ])

    return "\n".join(lines) + "\n"


def write_run_report_artifact(run_id, output_dir=None):
    row = get_run_report_data(run_id)
    if row is None:
        return None
    output_dir = RUN_ARTIFACTS_DIR if output_dir is None else Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / _run_artifact_name(row)
    output_path.write_text(run_report_markdown(run_id), encoding="utf-8")
    return output_path

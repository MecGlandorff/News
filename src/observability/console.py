from src import pricing
from src.observability.audit import novelty_audit
from src.observability.costs import llm_cost_summary
from src.observability.runs import get_run_report_data


def _audit_ratio_line(audit):
    ratio = audit.get("new_parent_ratio")
    if ratio is None:
        return "New parent ratio:      n/a"
    return (
        "New parent ratio:      "
        f"{audit.get('new_parent_arcs', 0)}/{audit.get('developments', 0)} "
        f"({ratio * 100:.1f}%)"
    )


def _audit_story_line(item):
    penalty = ""
    if item.get("selection_penalty"):
        reasons = ", ".join(item.get("penalty_reasons") or ["selection penalty"])
        penalty = (
            f", adjusted {item['selection_score']:.1f}, "
            f"penalty {item['selection_penalty']:.1f} ({reasons})"
        )
    return (
        f"    - {item['label']} "
        f"({item['theme']}, score {item['score']:.1f}, "
        f"{item['source_count']} sources, importance {item['importance_avg']:.1f}"
        f"{penalty})"
    )


def _audit_new_parent_line(item):
    development = item.get("development_label") or item["label"]
    label = item["label"]
    if development != label:
        label = f"{label} / {development}"
    return (
        f"    - {label} "
        f"({item['theme']}, score {item['score']:.1f}, "
        f"{item['source_count']} sources, {item['article_count']} articles, "
        f"importance {item['importance_avg']:.1f})"
    )


def _audit_candidate_line(item):
    return (
        f"    - {item['label']} -> {item['candidate_label']} "
        f"({item['relationship']}, {item['confidence']})"
    )


def _audit_rejected_line(item):
    return (
        f"    - {item['today_label']} -> {item['candidate_label']} "
        f"({item['relationship']}, {item['confidence']})"
    )


def _audit_arc_attachment_line(item):
    score = "score n/a" if item.get("chosen_score") is None else f"score {item['chosen_score']}"
    arc = item["arc_label"] or f"arc {item['arc_id']}"
    return (
        f"    - {item['today_label']} -> {arc} "
        f"({item['relationship']}, {item['confidence']}, {score}, "
        f"{item['arc_child_count']} stories in arc)"
    )


def _audit_arc_rejected_line(item):
    if item["proposed_arc_label"]:
        target = item["proposed_arc_label"]
    elif item["arc_id"] is not None:
        target = f"arc {item['arc_id']}"
    else:
        target = "NEW_ARC"
    return (
        f"    - {item['today_label']} -> {target} "
        f"({item['relationship']}, {item['confidence']})"
    )


def novelty_audit_lines(run_id, limit=5):
    audit = novelty_audit(run_id, limit=limit)
    sections = [
        ("High-signal not displayed", audit["high_signal_not_displayed"], _audit_story_line),
        ("High-signal new parent arcs", audit["high_signal_new_parent_arcs"], _audit_new_parent_line),
        ("New parent arcs with prior candidates", audit["new_parent_arcs_with_candidates"], _audit_candidate_line),
        ("Rejected related matches", audit["rejected_related_matches"], _audit_rejected_line),
        ("Arc attachments to review", audit["arc_attachments_review"], _audit_arc_attachment_line),
        ("Rejected arc decisions", audit["rejected_arc_decisions"], _audit_arc_rejected_line),
    ]

    lines = ["Novelty audit:", _audit_ratio_line(audit)]
    for title, items, formatter in sections:
        lines.append(f"{title}: {len(items)}")
        for item in items:
            lines.append(formatter(item))
    return lines


def pipeline_report(run_id):
    row = get_run_report_data(run_id)
    if row is None:
        return f"Run #{run_id} not found."

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
        f"Run #{row['run_id']} ({row['run_date'] or 'unknown date'}, {row['status']}, {seconds:.1f}s)",
        f"Articles returned:      {row['articles_returned'] or 0}",
        f"Duplicate URLs skipped: {row['duplicate_url_skips'] or 0}",
        f"Feed fetch failures:    {row['feed_fetch_failures'] or 0}",
        f"Outside date skipped:   {row['feed_items_outside_date_skipped'] or 0}",
        (
            "Undated included:      "
            f"{undated_included} "
            f"({row['feed_items_missing_timestamp_included'] or 0} missing, "
            f"{row['feed_items_unparseable_timestamp_included'] or 0} unparseable)"
        ),
        (
            "Undated skipped:       "
            f"{undated_skipped} "
            f"({row['feed_items_missing_timestamp_skipped'] or 0} missing, "
            f"{row['feed_items_unparseable_timestamp_skipped'] or 0} unparseable)"
        ),
        f"Article text fetched:   {row['article_text_fetch_successes'] or 0}",
        f"Article text failures:  {row['article_text_fetch_failures'] or 0}",
        f"Claims saved:           {row['claims_saved'] or 0}",
        f"Claims extracted:       {row['claim_articles_extracted'] or 0}",
        f"Claims cached:          {row['claim_articles_cached'] or 0}",
        f"Claims invalid:         {row['claim_invalid_dropped'] or 0}",
        f"Claim failures:         {row['claim_extraction_failures'] or 0}",
        f"Zero-claim results:     {row['claim_zero_results'] or 0}",
        f"Claim cheap accepts:    {row['claim_derivable_accepts'] or 0}",
        f"Claim verifier calls:   {row['claim_verifier_calls'] or 0}",
        f"Claim verifier accepts: {row['claim_verifier_accepts'] or 0}",
        f"Claim verifier rejects: {row['claim_verifier_rejects'] or 0}",
        f"Claim input truncation:  {row['claim_content_truncations'] or 0}",
        f"Stories touched:        {row['stories_touched'] or 0}",
        f"Developments saved:     {row['story_developments_saved'] or 0}",
        f"Parent attachments:     {row['story_parent_attachments'] or 0}",
        f"Arc assignments:        {row['story_arc_assignments'] or 0}",
        f"Arc attachments:        {row['story_arc_attachments'] or 0}",
        f"New arcs:               {row['story_new_arcs'] or 0}",
        f"New parent arcs:        {row['story_new_parent_arcs'] or 0}",
        f"Unmatched new stories:  {row['story_unmatched_new_stories'] or 0}",
        f"Story match checks:     {row['story_match_verifications'] or 0}",
        f"Story match accepted:   {row['story_match_accepts'] or 0}",
        f"Story match rejected:   {row['story_match_rejections'] or 0}",
        f"LLM calls:              {row['llm_calls_count'] or 0}",
        f"LLM errors:             {row['llm_errors_count'] or 0}",
        f"LLM cache hits:         {row['llm_cache_hits'] or 0}",
        f"  classification:       {row['classification_cache_hits'] or 0}",
        f"  claims:               {row['claim_cache_hits'] or 0}",
        f"  verifier:             {row['verifier_cache_hits'] or 0}",
        f"  matching:             {row['matching_cache_hits'] or 0}",
        f"  briefing:             {row['briefing_cache_hits'] or 0}",
        f"  other:                {row['other_cache_hits'] or 0}",
        f"Schema failures:        {row['schema_failures'] or 0}",
        f"Application retries:    {row['retry_count'] or 0}",
        "SDK retries:            not exposed by client",
        (
            "Tokens:                 "
            f"prompt {row['prompt_tokens'] or 0} / completion {row['completion_tokens'] or 0}"
        ),
    ]
    if cost["unpriced_models"]:
        lines.append(
            "Estimated cost:         "
            f"{pricing.format_eur(cost['priced_cost_eur'])} priced; "
            f"unpriced models: {', '.join(cost['unpriced_models'])}"
        )
    else:
        lines.append(f"Estimated cost:         {pricing.format_eur(cost['total_cost_eur'])}")
    for item in cost["by_purpose"]:
        suffix = ""
        if item["unpriced_models"]:
            suffix = f" (unpriced: {', '.join(item['unpriced_models'])})"
        lines.append(
            f"  {item['purpose']}: "
            f"{item['calls']} calls, "
            f"tokens {item['prompt_tokens']}/{item['completion_tokens']}, "
            f"latency {(item['latency_ms'] or 0) / 1000:.1f}s, "
            f"{pricing.format_eur(item['cost_eur'])}{suffix}"
        )
    lines.extend(novelty_audit_lines(run_id))
    if row["error_message"]:
        lines.append(f"Error:                  {row['error_message']}")
    return "\n".join(lines)

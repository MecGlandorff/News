

import src.observability as observability
from tests.observability.support import _run_args


def test_pipeline_report_includes_story_match_verifier_totals(tmp_path):
    db_path = tmp_path / "stories.db"

    run_id = observability.start_run(
        _run_args(), run_date="2026-05-07", db_path=db_path
    )
    observability.update_run_totals(
        run_id,
        story_match_verifications=6,
        story_match_accepts=4,
        story_match_rejections=2,
        db_path=db_path,
    )
    observability.finish_run(run_id, status="ok", db_path=db_path)

    report = observability.pipeline_report(run_id, db_path=db_path)

    assert "Story match checks:     6" in report
    assert "Story match accepted:   4" in report
    assert "Story match rejected:   2" in report


def test_pipeline_report_includes_story_development_totals(tmp_path):
    db_path = tmp_path / "stories.db"

    run_id = observability.start_run(
        _run_args(), run_date="2026-05-07", db_path=db_path
    )
    observability.update_run_totals(
        run_id,
        story_developments_saved=8,
        story_parent_attachments=3,
        story_arc_assignments=5,
        story_arc_attachments=3,
        story_new_arcs=2,
        story_new_parent_arcs=2,
        story_unmatched_new_stories=2,
        db_path=db_path,
    )
    observability.finish_run(run_id, status="ok", db_path=db_path)

    report = observability.pipeline_report(run_id, db_path=db_path)

    assert "Developments saved:     8" in report
    assert "Parent attachments:     3" in report
    assert "Arc assignments:        5" in report
    assert "Arc attachments:        3" in report
    assert "New arcs:               2" in report
    assert "New parent arcs:        2" in report
    assert "Unmatched new stories:  2" in report


def test_pipeline_report_includes_scraper_claim_and_cost_totals(tmp_path):
    db_path = tmp_path / "stories.db"

    run_id = observability.start_run(
        _run_args(), run_date="2026-05-07", db_path=db_path
    )
    observability.update_run_totals(
        run_id,
        duplicate_url_skips=2,
        feed_fetch_failures=1,
        feed_items_outside_date_skipped=9,
        feed_items_missing_timestamp_skipped=3,
        feed_items_unparseable_timestamp_skipped=2,
        feed_items_missing_timestamp_included=4,
        feed_items_unparseable_timestamp_included=1,
        article_text_fetch_successes=7,
        article_text_fetch_failures=3,
        claim_articles_extracted=4,
        claim_articles_cached=5,
        claim_invalid_dropped=6,
        claim_extraction_failures=1,
        claim_zero_results=2,
        db_path=db_path,
    )
    observability.record_llm_call(
        run_id=run_id,
        model="gpt-5.4-nano",
        purpose="claim",
        usage={"prompt_tokens": 1000, "completion_tokens": 500},
        latency_ms=1200,
        db_path=db_path,
    )
    observability.finish_run(run_id, status="ok", db_path=db_path)

    report = observability.pipeline_report(run_id, db_path=db_path)

    assert "Duplicate URLs skipped: 2" in report
    assert "Feed fetch failures:    1" in report
    assert "Outside date skipped:   9" in report
    assert "Undated included:      5 (4 missing, 1 unparseable)" in report
    assert "Undated skipped:       5 (3 missing, 2 unparseable)" in report
    assert "Article text fetched:   7" in report
    assert "Article text failures:  3" in report
    assert "Claims extracted:       4" in report
    assert "Claims cached:          5" in report
    assert "Claims invalid:         6" in report
    assert "Claim failures:         1" in report
    assert "Zero-claim results:     2" in report
    assert "Estimated cost:         EUR 0.0007" in report
    assert "claim: 1 calls, tokens 1000/500, latency 1.2s, EUR 0.0007" in report


def test_write_run_report_artifact_outputs_markdown_overview(tmp_path):
    db_path = tmp_path / "stories.db"

    run_id = observability.start_run(
        _run_args(), run_date="2026-05-10", db_path=db_path
    )
    observability.update_run_totals(
        run_id,
        articles_returned=345,
        feed_fetch_failures=1,
        feed_items_outside_date_skipped=12,
        feed_items_missing_timestamp_included=2,
        feed_items_unparseable_timestamp_included=1,
        stories_touched=164,
        llm_cache_hits=4,
        db_path=db_path,
    )
    observability.record_llm_call(
        run_id=run_id,
        model="gpt-5.5",
        purpose="brief",
        usage={"prompt_tokens": 33200, "completion_tokens": 7365},
        latency_ms=145000,
        db_path=db_path,
    )
    observability.finish_run(run_id, status="ok", db_path=db_path)

    artifact = observability.write_run_report_artifact(
        run_id,
        output_dir=tmp_path / "run_artifacts",
        db_path=db_path,
    )

    assert artifact == tmp_path / "run_artifacts" / f"run_2026-05-10_{run_id}.md"
    markdown = artifact.read_text(encoding="utf-8")
    assert "# Run Report: 2026-05-10" in markdown
    assert "| Articles returned | 345 |" in markdown
    assert "| Feed fetch failures | 1 |" in markdown
    assert "| Feed items outside date skipped | 12 |" in markdown
    assert "| Undated feed items included | 3 |" in markdown
    assert "| Stories touched | 164 |" in markdown
    assert "| LLM cache hits | 4 |" in markdown
    assert "| brief | 1 | 33,200 | 7,365 | 145.0s |" in markdown

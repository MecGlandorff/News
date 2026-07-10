import argparse
from contextlib import contextmanager, nullcontext
import logging
import sqlite3
import tempfile
from pathlib import Path

import src.article_cache as article_cache
import src.claims as claims
import src.llm_response_cache as llm_response_cache
import src.observability as observability
import src.replay as replay
import src.scraper as scraper
import src.sources as sources
from src.claims import extract_and_save_claims
from src.classifier import classify_articles
from src.digest import write_digest
from src.llm import require_openai_api_key
from src.rendering.newspaper import write_newspaper_pdf
from src.scraper import scrape_all
from src.top10 import build_briefing_package, write_top10
import src.tracker as tracker
from src.article_dates import editorial_today
from src.tracker import track

logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(description="Run the news intelligence pipeline.")
    parser.add_argument("--max-per-source", type=int, default=None)
    parser.add_argument("--today", "--date", dest="today", default=None, help="Override tracking date as YYYY-MM-DD")
    parser.add_argument(
        "--include-undated",
        action="store_true",
        help="Include feed items with missing or unparseable published dates in the selected run date",
    )
    parser.add_argument("--skip-digest", action="store_true")
    parser.add_argument("--skip-briefing", action="store_true")
    parser.add_argument("--skip-pdf", action="store_true")
    parser.add_argument(
        "--db-off",
        action="store_true",
        help="Use a temporary database/cache for this run, leaving data/stories.db untouched",
    )
    parser.add_argument(
        "--top-developments",
        "--briefing-per-theme",
        dest="top_developments",
        type=int,
        default=3,
        help="Number of lead stories in the briefing, clamped to 3-8",
    )
    parser.add_argument("--fetch-article-text", action="store_true", help="Fetch full article pages in addition to RSS metadata")
    parser.add_argument(
        "--show-evidence",
        action="store_true",
        help="Extract claims with full article text when available and append evidence spans to briefing",
    )
    parser.add_argument(
        "--verify-story-matches",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Verify candidate story matches with full article text and gpt-5.4-nano before reusing story memory",
    )
    parser.add_argument("--pipeline-report", action="store_true", help="Print run totals, LLM calls, latency, token usage, and estimated cost")
    parser.add_argument(
        "--replay",
        metavar="YYYY-MM-DD",
        help="Rebuild derived tracking state from this date using stored snapshots only",
    )
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser.parse_args()


@contextmanager
def temporary_database_paths():
    """Route DB-backed state to a temporary directory for one run."""
    original_article_cache_db = article_cache.DB_PATH
    original_tracker_db = tracker.DB_PATH
    original_tracker_data_dir = tracker.DATA_DIR
    original_claims_db = claims.DB_PATH
    original_llm_response_cache_db = llm_response_cache.DB_PATH
    original_sources_db = sources.DB_PATH
    original_observability_db = observability.DB_PATH

    with tempfile.TemporaryDirectory(prefix="news-db-off-") as tmp:
        tmp_path = Path(tmp)
        temp_db = tmp_path / "stories.db"
        article_cache.DB_PATH = temp_db
        tracker.DB_PATH = temp_db
        tracker.DATA_DIR = tmp_path / "daily"
        claims.DB_PATH = temp_db
        llm_response_cache.DB_PATH = temp_db
        sources.DB_PATH = temp_db
        observability.DB_PATH = temp_db
        logger.info("DB off: using temporary database at %s", temp_db)
        try:
            yield
        finally:
            article_cache.DB_PATH = original_article_cache_db
            tracker.DB_PATH = original_tracker_db
            tracker.DATA_DIR = original_tracker_data_dir
            claims.DB_PATH = original_claims_db
            llm_response_cache.DB_PATH = original_llm_response_cache_db
            sources.DB_PATH = original_sources_db
            observability.DB_PATH = original_observability_db


def configure_logging(log_level):
    logging.basicConfig(
        level=getattr(logging, log_level),
        format="%(levelname)s:%(name)s:%(message)s",
    )
    logging.getLogger("urllib3.connectionpool").setLevel(logging.ERROR)


def scrape_articles(args, run_date):
    scraper.reset_scrape_stats()
    articles = scrape_all(
        max_per_source=args.max_per_source,
        fetch_article_text=args.fetch_article_text or args.show_evidence,
        target_date=run_date,
        include_undated=getattr(args, "include_undated", False),
    )
    observability.update_run_totals(**scraper.last_scrape_stats())
    return articles


def seed_source_metadata():
    sources.seed_sources()


def classify_scraped_articles(articles):
    return classify_articles(articles)


def track_stories(classified, run_date, verify_story_matches=True):
    return track(classified, today=run_date, verify_story_matches=verify_story_matches)


def maybe_extract_claims(args, tracked):
    if args.show_evidence:
        return extract_and_save_claims(tracked)
    return claims._empty_claim_stats()


def write_pipeline_outputs(args, tracked):
    outputs = []
    if not args.skip_digest:
        outputs.append(write_digest(tracked))

    briefing_package = None
    if not args.skip_briefing or not args.skip_pdf:
        briefing_package = build_briefing_package(
            tracked,
            n=args.top_developments,
            include_evidence=args.show_evidence,
        )
    if not args.skip_briefing:
        outputs.append(write_top10(
            tracked,
            n=args.top_developments,
            package=briefing_package,
            show_evidence=args.show_evidence,
        ))
    if not args.skip_pdf:
        outputs.append(write_newspaper_pdf(
            tracked,
            n=args.top_developments,
            package=briefing_package,
        ))
    return outputs


def run_pipeline(args, run_date=None):
    run_date = run_date or args.today or str(editorial_today())
    seed_source_metadata()
    articles = scrape_articles(args, run_date)
    observability.update_run_totals(articles_returned=len(articles))
    classified = classify_scraped_articles(articles)
    tracked = track_stories(
        classified,
        run_date,
        verify_story_matches=getattr(args, "verify_story_matches", True),
    )
    stories_touched = len({
        article.get("story_id")
        for article in tracked
        if article.get("story_id") is not None
    })
    observability.update_run_totals(stories_touched=stories_touched)
    claim_stats = maybe_extract_claims(args, tracked)
    observability.update_run_totals(
        claims_saved=claim_stats.get("claims_saved", 0),
        claim_articles_extracted=claim_stats.get("articles_extracted", 0),
        claim_articles_cached=claim_stats.get("cached", 0),
        claim_invalid_dropped=claim_stats.get("invalid", 0),
        claim_extraction_failures=claim_stats.get("failed", 0),
        claim_zero_results=claim_stats.get("zero_claim_results", 0),
        claim_derivable_accepts=claim_stats.get("claim_derivable_accepts", 0),
        claim_verifier_calls=claim_stats.get("claim_verifier_calls", 0),
        claim_verifier_accepts=claim_stats.get("claim_verifier_accepts", 0),
        claim_verifier_rejects=claim_stats.get("claim_verifier_rejects", 0),
        claim_content_truncations=claim_stats.get("content_truncations", 0),
    )
    return write_pipeline_outputs(args, tracked)


def run_replay(start_date):
    result = replay.rebuild_from_date(tracker.DB_PATH, start_date)
    observability.update_run_totals(stories_touched=result.stories_rebuilt)
    logger.info(
        "Replay rebuilt %s occurrence(s) across %s day(s), %s through %s",
        result.occurrences_rebuilt,
        result.dates_rebuilt,
        result.start_date,
        result.end_date,
    )
    return result


def main():
    args = parse_args()
    configure_logging(args.log_level)
    replay_date = getattr(args, "replay", None)
    if replay_date and args.today:
        raise ValueError("--replay cannot be combined with --today/--date")
    if replay_date and args.db_off:
        raise ValueError("--replay requires the stored database and cannot use --db-off")
    if not replay_date:
        require_openai_api_key()

    db_context = temporary_database_paths() if args.db_off else nullcontext()
    with db_context:
        run_date = replay_date or args.today or str(editorial_today())
        run_id = observability.start_run(args, run_date=run_date)
        observability.set_current_run_id(run_id)
        try:
            outputs = (
                [run_replay(replay_date)]
                if replay_date
                else run_pipeline(args, run_date=run_date)
            )
            observability.finish_run(run_id, status="ok")
            try:
                pruned = llm_response_cache.prune_cache()
                if pruned:
                    logger.info("Pruned %s expired or excess exact LLM cache entries", pruned)
            except sqlite3.Error as exc:
                logger.warning("Could not prune exact LLM response cache: %s", exc)
            observability.write_run_report_artifact(run_id)
            if getattr(args, "pipeline_report", False):
                print(observability.pipeline_report(run_id))
            return outputs
        except Exception as exc:
            observability.finish_run(run_id, status="error", error_message=str(exc))
            observability.write_run_report_artifact(run_id)
            if getattr(args, "pipeline_report", False):
                print(observability.pipeline_report(run_id))
            raise
        finally:
            observability.clear_current_run_id()


if __name__ == "__main__":
    main()

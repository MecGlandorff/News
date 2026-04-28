import argparse
from contextlib import contextmanager, nullcontext
import logging
import tempfile
from pathlib import Path

import src.article_cache as article_cache
from src.classifier import classify_articles
from src.digest import write_digest
from src.llm import require_openai_api_key
from src.newspaper import write_newspaper_pdf
from src.scraper import scrape_all
from src.top10 import build_briefing_package, write_top10
import src.tracker as tracker
from src.tracker import track


def parse_args():
    parser = argparse.ArgumentParser(description="Run the news scraper pipeline.")
    parser.add_argument("--max-per-source", type=int, default=None)
    parser.add_argument("--today", default=None, help="Override tracking date as YYYY-MM-DD")
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
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser.parse_args()


@contextmanager
def temporary_database_paths():
    """Route DB-backed state to a temporary directory for one run."""
    original_article_cache_db = article_cache.DB_PATH
    original_tracker_db = tracker.DB_PATH
    original_tracker_data_dir = tracker.DATA_DIR

    with tempfile.TemporaryDirectory(prefix="news-db-off-") as tmp:
        tmp_path = Path(tmp)
        temp_db = tmp_path / "stories.db"
        article_cache.DB_PATH = temp_db
        tracker.DB_PATH = temp_db
        tracker.DATA_DIR = tmp_path / "daily"
        print(f"DB off: using temporary database at {temp_db}")
        try:
            yield
        finally:
            article_cache.DB_PATH = original_article_cache_db
            tracker.DB_PATH = original_tracker_db
            tracker.DATA_DIR = original_tracker_data_dir


def main():
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(levelname)s:%(name)s:%(message)s",
    )
    logging.getLogger("urllib3.connectionpool").setLevel(logging.ERROR)

    require_openai_api_key()

    db_context = temporary_database_paths() if args.db_off else nullcontext()
    with db_context:
        articles = scrape_all(max_per_source=args.max_per_source, fetch_article_text=args.fetch_article_text)
        classified = classify_articles(articles)
        tracked = track(classified, today=args.today)

        outputs = []
        if not args.skip_digest:
            outputs.append(write_digest(tracked))
        briefing_package = None
        if not args.skip_briefing or not args.skip_pdf:
            briefing_package = build_briefing_package(tracked, n=args.top_developments)
        if not args.skip_briefing:
            outputs.append(write_top10(tracked, n=args.top_developments, package=briefing_package))
        if not args.skip_pdf:
            outputs.append(write_newspaper_pdf(tracked, n=args.top_developments, package=briefing_package))

    return outputs


if __name__ == "__main__":
    main()

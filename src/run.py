import argparse
import logging

from src.classifier import classify_articles
from src.digest import write_digest
from src.llm import require_openai_api_key
from src.scraper import scrape_all
from src.top10 import write_top10
from src.tracker import track


def parse_args():
    parser = argparse.ArgumentParser(description="Run the news scraper pipeline.")
    parser.add_argument("--max-per-source", type=int, default=None)
    parser.add_argument("--today", default=None, help="Override tracking date as YYYY-MM-DD")
    parser.add_argument("--skip-digest", action="store_true")
    parser.add_argument("--skip-briefing", action="store_true")
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


def main():
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(levelname)s:%(name)s:%(message)s",
    )
    logging.getLogger("urllib3.connectionpool").setLevel(logging.ERROR)

    require_openai_api_key()

    articles = scrape_all(max_per_source=args.max_per_source, fetch_article_text=args.fetch_article_text)
    classified = classify_articles(articles)
    tracked = track(classified, today=args.today)

    outputs = []
    if not args.skip_digest:
        outputs.append(write_digest(tracked))
    if not args.skip_briefing:
        outputs.append(write_top10(tracked, n=args.top_developments))

    return outputs


if __name__ == "__main__":
    main()

import logging
import re
import time
import hashlib
import requests
from collections import defaultdict
from bs4 import BeautifulSoup
from datetime import date
from requests.adapters import HTTPAdapter
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib3.util.retry import Retry

from src.article_dates import editorial_date

SOURCES = [
    # --- Dutch politics & general ---
    ("NOS",              "nl", "https://feeds.nos.nl/nosnieuwsalgemeen"),
    ("Nieuwsuur",        "nl", "https://feeds.nos.nl/nosnieuwsnieuwsuur"),
    ("RTL Nieuws",       "nl", "https://www.rtlnieuws.nl/rss.xml"),
    ("NU.nl",            "nl", "https://www.nu.nl/rss/algemeen"),
    ("de Volkskrant",    "nl", "https://www.volkskrant.nl/voorpagina/rss.xml"),
    ("NRC",              "nl", "https://www.nrc.nl/rss.php"),
    ("Trouw",            "nl", "https://www.trouw.nl/voorpagina/rss.xml"),
    ("AD",               "nl", "https://www.ad.nl/home/rss.xml"),
    ("Telegraaf",        "nl", "https://www.telegraaf.nl/rss"),
    ("Het Parool",       "nl", "https://www.parool.nl/voorpagina/rss.xml"),
    ("FD",               "nl", "https://fd.nl/?rss"),
    ("Follow the Money", "nl", "https://www.ftm.nl/feed/"),
    # --- USA politics ---
    ("Politico",         "en", "https://rss.politico.com/politics-news.xml"),
    ("Washington Post",  "en", "https://feeds.washingtonpost.com/rss/world"),
    ("NYT",              "en", "https://rss.nytimes.com/services/xml/rss/nyt/World.xml"),
    # --- International / geopolitics ---
    ("BBC News",         "en", "https://feeds.bbci.co.uk/news/rss.xml"),
    ("The Guardian",     "en", "https://www.theguardian.com/world/rss"),
    ("Al Jazeera",       "en", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("Foreign Policy",   "en", "https://foreignpolicy.com/feed/"),
    ("Der Spiegel",      "en", "https://www.spiegel.de/international/index.rss"),
    ("DW",               "en", "https://rss.dw.com/rdf/rss-en-all"),
]

MAX_ARTICLES_PER_SOURCE = None
DELAY                   = 0.5
FETCH_ARTICLE_TEXT      = False

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}
SKIP_TAGS = {"nav", "footer", "header", "aside", "script", "style", "noscript", "form"}
logger = logging.getLogger(__name__)
TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid"}
_LAST_SCRAPE_STATS: dict[str, int] = {}


def _new_scrape_stats():
    return {
        "duplicate_url_skips": 0,
        "feed_fetch_failures": 0,
        "feed_items_outside_date_skipped": 0,
        "feed_items_missing_timestamp_skipped": 0,
        "feed_items_unparseable_timestamp_skipped": 0,
        "feed_items_missing_timestamp_included": 0,
        "feed_items_unparseable_timestamp_included": 0,
        "article_text_fetch_successes": 0,
        "article_text_fetch_failures": 0,
    }


def last_scrape_stats():
    return dict(_LAST_SCRAPE_STATS)


def reset_scrape_stats():
    global _LAST_SCRAPE_STATS
    _LAST_SCRAPE_STATS = _new_scrape_stats()


def _session():
    session = requests.Session()
    session.headers.update(HEADERS)
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def _parse_rss(url, session=None):
    session = session or _session()
    resp = session.get(url, timeout=10)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.content, "xml")
    items = []
    for item in soup.find_all("item"):
        items.append({
            "title":        item.find("title").get_text(strip=True) if item.find("title") else "",
            "url":          item.find("link").get_text(strip=True) if item.find("link") else "",
            "description":  item.find("description").get_text(strip=True) if item.find("description") else "",
            "published_at": item.find("pubDate").get_text(strip=True) if item.find("pubDate") else "",
        })
    return items


def _normalize_url(url):
    parsed = urlsplit(url.strip())
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key not in TRACKING_QUERY_PARAMS
        and not any(key.startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES)
    ]
    return urlunsplit((
        parsed.scheme.lower(),
        parsed.netloc.lower(),
        parsed.path.rstrip("/") or parsed.path,
        urlencode(sorted(query), doseq=True),
        "",
    ))


def _article_id(url):
    return hashlib.sha256(_normalize_url(url).encode("utf-8")).hexdigest()[:16]


def _parse_published_at(value):
    return editorial_date(value)


def _published_date_filter_reason(value, target_date):
    raw_value = str(value or "").strip()
    if not raw_value:
        return "missing_timestamp"
    published = _parse_published_at(raw_value)
    if published is None:
        return "unparseable_timestamp"
    expected = date.fromisoformat(str(target_date))
    if published != expected:
        return "outside_date"
    return None


def _published_on_target_date(value, target_date):
    if target_date is None:
        return True
    return _published_date_filter_reason(value, target_date) is None


def _extract_text(url, session=None):
    session = session or _session()
    resp = session.get(url, timeout=10)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    for tag in soup(SKIP_TAGS):
        tag.decompose()
    body = soup.find("article") or soup.find("main")
    if not body:
        return ""
    return re.sub(r"\n{3,}", "\n\n", body.get_text(separator="\n")).strip()


def fetch_article_text(url, session=None):
    return _extract_text(url, session=session)


def scrape_all(
    sources=None,
    max_per_source=None,
    fetch_article_text=FETCH_ARTICLE_TEXT,
    target_date=None,
    include_undated=False,
):
    global _LAST_SCRAPE_STATS
    sources = sources or SOURCES
    if max_per_source is None:
        max_per_source = MAX_ARTICLES_PER_SOURCE

    articles = []
    stats = _new_scrape_stats()
    _LAST_SCRAPE_STATS = stats
    seen_urls = set()
    skipped_outside_date = 0
    skipped_missing_timestamp = 0
    skipped_unparseable_timestamp = 0
    timestamp_skips_by_source = defaultdict(lambda: {
        "missing_timestamp": 0,
        "unparseable_timestamp": 0,
    })
    session = _session()

    for source_name, lang, rss_url in sources:
        logger.info("[%s] fetching feed...", source_name)
        try:
            feed_items = _parse_rss(rss_url, session=session)
        except Exception as e:
            stats["feed_fetch_failures"] += 1
            logger.warning("Feed fetch failed for %s: %s", source_name, e)
            logger.debug("Feed fetch traceback for %s", source_name, exc_info=True)
            continue

        items = []
        for item in feed_items:
            filter_reason = (
                _published_date_filter_reason(item.get("published_at"), target_date)
                if target_date is not None
                else None
            )
            if filter_reason:
                if filter_reason == "outside_date":
                    stats["feed_items_outside_date_skipped"] += 1
                    skipped_outside_date += 1
                elif filter_reason == "missing_timestamp":
                    if include_undated:
                        stats["feed_items_missing_timestamp_included"] += 1
                        items.append(item)
                        if max_per_source is not None and len(items) >= max_per_source:
                            break
                        continue
                    stats["feed_items_missing_timestamp_skipped"] += 1
                    skipped_missing_timestamp += 1
                    timestamp_skips_by_source[source_name]["missing_timestamp"] += 1
                elif filter_reason == "unparseable_timestamp":
                    if include_undated:
                        stats["feed_items_unparseable_timestamp_included"] += 1
                        items.append(item)
                        if max_per_source is not None and len(items) >= max_per_source:
                            break
                        continue
                    stats["feed_items_unparseable_timestamp_skipped"] += 1
                    skipped_unparseable_timestamp += 1
                    timestamp_skips_by_source[source_name]["unparseable_timestamp"] += 1
                continue
            items.append(item)
            if max_per_source is not None and len(items) >= max_per_source:
                break

        for item in items:
            normalized_url = _normalize_url(item["url"])
            if normalized_url in seen_urls:
                stats["duplicate_url_skips"] += 1
                continue
            seen_urls.add(normalized_url)
            text = ""
            if fetch_article_text:
                try:
                    text = _extract_text(item["url"], session=session)
                    if text:
                        stats["article_text_fetch_successes"] += 1
                    else:
                        stats["article_text_fetch_failures"] += 1
                except Exception as e:
                    stats["article_text_fetch_failures"] += 1
                    logger.warning("Article text extraction failed for %s: %s", item["url"], e)
            article_id = _article_id(item["url"])
            articles.append({
                "id":           article_id,
                "source":       source_name,
                "language":     lang,
                "title":        item["title"],
                "description":  item["description"],
                "url":          item["url"],
                "published_at": item["published_at"],
                "text":         text,
            })
            logger.debug("  [%s] %s", article_id, item["title"][:70])
            time.sleep(DELAY)

    if target_date is not None:
        logger.info("Skipped %s feed items outside %s", skipped_outside_date, target_date)
        timestamp_skips = skipped_missing_timestamp + skipped_unparseable_timestamp
        logger.info(
            "Skipped "
            "%s feed items without a usable timestamp "
            "(%s missing, %s unparseable)",
            timestamp_skips,
            skipped_missing_timestamp,
            skipped_unparseable_timestamp,
        )
        timestamp_includes = (
            stats["feed_items_missing_timestamp_included"]
            + stats["feed_items_unparseable_timestamp_included"]
        )
        if timestamp_includes:
            logger.info(
                "Included "
                "%s feed items without a usable timestamp "
                "because --include-undated is enabled "
                "(%s missing, %s unparseable)",
                timestamp_includes,
                stats["feed_items_missing_timestamp_included"],
                stats["feed_items_unparseable_timestamp_included"],
            )
        if timestamp_skips_by_source:
            parts = []
            for source, counts in sorted(timestamp_skips_by_source.items()):
                total = counts["missing_timestamp"] + counts["unparseable_timestamp"]
                parts.append(
                    f"{source}: {total} "
                    f"({counts['missing_timestamp']} missing, "
                    f"{counts['unparseable_timestamp']} unparseable)"
                )
            logger.info("Timestamp skips by source: %s", "; ".join(parts))
    logger.info("Total: %s articles", len(articles))
    _LAST_SCRAPE_STATS = stats
    return articles

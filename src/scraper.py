import logging
import re
import time
import hashlib
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib3.util.retry import Retry

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
LOGGER = logging.getLogger(__name__)
TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid"}


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


def scrape_all(sources=None, max_per_source=None, fetch_article_text=FETCH_ARTICLE_TEXT):
    sources = sources or SOURCES
    if max_per_source is None:
        max_per_source = MAX_ARTICLES_PER_SOURCE

    articles = []
    seen_urls = set()
    session = _session()

    for source_name, lang, rss_url in sources:
        print(f"[{source_name}] fetching feed...", flush=True)
        try:
            feed_items = _parse_rss(rss_url, session=session)
        except Exception as e:
            LOGGER.warning("Feed fetch failed for %s: %s", source_name, e)
            LOGGER.debug("Feed fetch traceback for %s", source_name, exc_info=True)
            print(f"  ERR feed: {e}", flush=True)
            continue

        items = feed_items if max_per_source is None else feed_items[:max_per_source]
        for item in items:
            normalized_url = _normalize_url(item["url"])
            if normalized_url in seen_urls:
                continue
            seen_urls.add(normalized_url)
            text = ""
            if fetch_article_text:
                try:
                    text = _extract_text(item["url"], session=session)
                except Exception as e:
                    LOGGER.warning("Article text extraction failed for %s: %s", item["url"], e)
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
            print(f"  [{article_id}] {item['title'][:70]}", flush=True)
            time.sleep(DELAY)

    print(f"\nTotal: {len(articles)} articles", flush=True)
    return articles

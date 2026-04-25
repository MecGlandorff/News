import hashlib
import sqlite3
from pathlib import Path


DB_PATH = Path("data/stories.db")


def _get_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS article_classifications (
            article_id       TEXT PRIMARY KEY,
            url              TEXT NOT NULL,
            title            TEXT,
            description      TEXT,
            content_hash     TEXT NOT NULL,
            theme            TEXT NOT NULL,
            story_label      TEXT NOT NULL,
            importance       INTEGER NOT NULL,
            classifier_model TEXT NOT NULL,
            prompt_version   TEXT NOT NULL,
            classified_at    TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    return conn


def article_content_hash(article):
    content = "\n".join([
        article.get("title", ""),
        article.get("description", ""),
    ])
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def get_cached_classifications(articles, classifier_model, prompt_version):
    if not articles:
        return {}

    conn = _get_db()
    cached = {}
    try:
        for article in articles:
            article_id = str(article["id"])
            row = conn.execute(
                """
                SELECT theme, story_label, importance, content_hash
                FROM article_classifications
                WHERE article_id = ?
                  AND classifier_model = ?
                  AND prompt_version = ?
                """,
                (article_id, classifier_model, prompt_version),
            ).fetchone()
            if not row or row["content_hash"] != article_content_hash(article):
                continue
            cached[article_id] = {
                "theme": row["theme"],
                "story_label": row["story_label"],
                "importance": row["importance"],
            }
    finally:
        conn.close()
    return cached


def save_classifications(articles, classifications, classifier_model, prompt_version):
    if not articles:
        return

    conn = _get_db()
    try:
        for article in articles:
            article_id = str(article["id"])
            classification = classifications.get(article_id)
            if not classification:
                continue
            conn.execute(
                """
                INSERT INTO article_classifications (
                    article_id, url, title, description, content_hash,
                    theme, story_label, importance, classifier_model, prompt_version
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(article_id) DO UPDATE SET
                    url = excluded.url,
                    title = excluded.title,
                    description = excluded.description,
                    content_hash = excluded.content_hash,
                    theme = excluded.theme,
                    story_label = excluded.story_label,
                    importance = excluded.importance,
                    classifier_model = excluded.classifier_model,
                    prompt_version = excluded.prompt_version,
                    classified_at = CURRENT_TIMESTAMP
                """,
                (
                    article_id,
                    article.get("url", ""),
                    article.get("title", ""),
                    article.get("description", ""),
                    article_content_hash(article),
                    classification["theme"],
                    classification["story_label"],
                    classification["importance"],
                    classifier_model,
                    prompt_version,
                ),
            )
        conn.commit()
    finally:
        conn.close()

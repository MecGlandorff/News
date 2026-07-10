import sqlite3

import src.scraper as scraper
import src.sources as sources_module
from src.sources import list_sources, seed_sources


def test_seed_sources_creates_rows_for_configured_rss_feeds(tmp_path, monkeypatch):
    monkeypatch.setattr(sources_module, "DB_PATH", tmp_path / "stories.db")

    seed_sources()

    rows = list_sources()
    expected = {name: (language, rss_url) for name, language, rss_url in scraper.SOURCES}
    actual = {row["name"]: (row["language"], row["rss_url"]) for row in rows}

    assert len(rows) == len(scraper.SOURCES)
    assert actual == expected
    assert {row["type"] for row in rows} == {"publication"}
    assert {row["reliability"] for row in rows} == {"unknown"}
    assert {row["bias_notes"] for row in rows} == {""}


def test_seed_sources_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(sources_module, "DB_PATH", tmp_path / "stories.db")
    configured = [
        ("Example", "en", "https://example.com/rss"),
        ("Example NL", "nl", "https://example.nl/rss"),
    ]

    seed_sources(configured)
    seed_sources(configured)

    rows = list_sources()
    assert len(rows) == 2
    assert {row["name"] for row in rows} == {"Example", "Example NL"}


def test_seed_sources_preserves_manual_metadata(tmp_path, monkeypatch):
    db_path = tmp_path / "stories.db"
    monkeypatch.setattr(sources_module, "DB_PATH", db_path)

    seed_sources([("Example", "en", "https://example.com/old-rss")])
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            UPDATE sources
            SET type = ?, reliability = ?, bias_notes = ?
            WHERE name = ?
            """,
            ("blog", "medium", "Manually reviewed source.", "Example"),
        )
        conn.commit()
    finally:
        conn.close()

    seed_sources([("Example", "nl", "https://example.com/new-rss")])

    row = list_sources()[0]
    assert row["rss_url"] == "https://example.com/new-rss"
    assert row["language"] == "nl"
    assert row["type"] == "blog"
    assert row["reliability"] == "medium"
    assert row["bias_notes"] == "Manually reviewed source."


def test_seed_sources_migrates_older_nullable_schema(tmp_path, monkeypatch):
    db_path = tmp_path / "stories.db"
    monkeypatch.setattr(sources_module, "DB_PATH", db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript("""
            CREATE TABLE sources (
                source_id   INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL UNIQUE,
                rss_url     TEXT NOT NULL,
                language    TEXT NOT NULL,
                type        TEXT NOT NULL DEFAULT 'unknown',
                reliability TEXT NOT NULL DEFAULT 'unknown',
                bias_notes  TEXT,
                created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at  TEXT DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.execute(
            """
            INSERT INTO sources (
                name, rss_url, language, type, reliability, bias_notes
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("Example", "https://example.com/old-rss", "en", "blog", "medium", None),
        )
        conn.commit()
    finally:
        conn.close()

    seed_sources([("Example", "en", "https://example.com/new-rss")])

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        columns = {row["name"]: row for row in conn.execute("PRAGMA table_info(sources)")}
        row = conn.execute("SELECT * FROM sources WHERE name = ?", ("Example",)).fetchone()
    finally:
        conn.close()

    assert columns["type"]["dflt_value"] is None
    assert columns["bias_notes"]["notnull"] == 1
    assert columns["bias_notes"]["dflt_value"] == "''"
    assert row["rss_url"] == "https://example.com/new-rss"
    assert row["type"] == "blog"
    assert row["reliability"] == "medium"
    assert row["bias_notes"] == ""


def test_source_schema_migration_preserves_referencing_articles(tmp_path, monkeypatch):
    db_path = tmp_path / "stories.db"
    monkeypatch.setattr(sources_module, "DB_PATH", db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript("""
            CREATE TABLE sources (
                source_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                rss_url TEXT NOT NULL,
                language TEXT NOT NULL,
                type TEXT NOT NULL DEFAULT 'unknown',
                reliability TEXT NOT NULL DEFAULT 'unknown',
                bias_notes TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE articles (
                id TEXT,
                source_id INTEGER REFERENCES sources(source_id)
            );
            INSERT INTO sources (
                source_id, name, rss_url, language, type, reliability
            ) VALUES (
                1, 'Example', 'https://example.com/old-rss', 'en',
                'publication', 'unknown'
            );
            INSERT INTO articles (id, source_id) VALUES ('article-1', 1);
        """)
        conn.commit()
    finally:
        conn.close()

    seed_sources([("Example", "en", "https://example.com/new-rss")])

    conn = sqlite3.connect(db_path)
    try:
        article_source = conn.execute(
            "SELECT source_id FROM articles WHERE id = 'article-1'"
        ).fetchone()[0]
        source_name = conn.execute(
            "SELECT name FROM sources WHERE source_id = ?", (article_source,)
        ).fetchone()[0]
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        conn.close()

    assert article_source == 1
    assert source_name == "Example"
    assert violations == []


def test_sources_schema_requires_explicit_type_and_defaults_empty_bias_notes(tmp_path, monkeypatch):
    db_path = tmp_path / "stories.db"
    monkeypatch.setattr(sources_module, "DB_PATH", db_path)
    seed_sources([])

    conn = sqlite3.connect(db_path)
    try:
        try:
            conn.execute(
                """
                INSERT INTO sources (name, rss_url, language, reliability)
                VALUES (?, ?, ?, ?)
                """,
                ("Missing Type", "https://example.com/rss", "en", "unknown"),
            )
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("sources.type should be explicit")

        conn.execute(
            """
            INSERT INTO sources (name, rss_url, language, type, reliability)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("No Bias Notes", "https://example.com/notes-rss", "en", "publication", "unknown"),
        )
        row = conn.execute(
            "SELECT bias_notes FROM sources WHERE name = ?",
            ("No Bias Notes",),
        ).fetchone()
    finally:
        conn.close()

    assert row[0] == ""


def test_seed_sources_uses_current_scraper_source_list(tmp_path, monkeypatch):
    monkeypatch.setattr(sources_module, "DB_PATH", tmp_path / "stories.db")
    monkeypatch.setattr(
        scraper,
        "SOURCES",
        [("Patched Source", "en", "https://example.com/patched-rss")],
    )

    seed_sources()

    rows = list_sources()
    assert [row["name"] for row in rows] == ["Patched Source"]

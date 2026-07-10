import sqlite3

import src.llm_response_cache as llm_response_cache


def test_llm_response_cache_uses_exact_request_hash(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_response_cache, "DB_PATH", tmp_path / "stories.db")

    first = llm_response_cache.cache_metadata(
        purpose="match-crossday",
        model="test-model",
        prompt_version="v1",
        messages=[{"role": "user", "content": "first"}],
        response_format={"type": "json_object"},
    )
    second = llm_response_cache.cache_metadata(
        purpose="match-crossday",
        model="test-model",
        prompt_version="v1",
        messages=[{"role": "user", "content": "second"}],
        response_format={"type": "json_object"},
    )

    llm_response_cache.save_response(first, '{"ok": true}')

    assert llm_response_cache.get_cached_response(first) == '{"ok": true}'
    assert llm_response_cache.get_cached_response(second) is None

    conn = sqlite3.connect(tmp_path / "stories.db")
    try:
        hit_count = conn.execute(
            "SELECT hit_count FROM llm_response_cache"
        ).fetchone()[0]
    finally:
        conn.close()

    assert hit_count == 1


def test_prune_cache_enforces_age_and_entry_bounds(tmp_path, monkeypatch):
    db_path = tmp_path / "stories.db"
    monkeypatch.setattr(llm_response_cache, "DB_PATH", db_path)
    for index in range(4):
        metadata = llm_response_cache.cache_metadata(
            purpose="brief",
            model="test-model",
            prompt_version="v1",
            messages=[{"role": "user", "content": str(index)}],
        )
        llm_response_cache.save_response(metadata, f'{{"index": {index}}}')

    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE llm_response_cache SET created_at = '2020-01-01 00:00:00' WHERE cache_id = 1"
    )
    conn.commit()
    conn.close()

    deleted = llm_response_cache.prune_cache(max_age_days=30, max_entries=2)

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT cache_id FROM llm_response_cache ORDER BY cache_id"
        ).fetchall()
    finally:
        conn.close()
    assert deleted == 2
    assert rows == [(3,), (4,)]


def test_refreshing_cached_response_resets_usage_metadata(tmp_path, monkeypatch):
    db_path = tmp_path / "stories.db"
    monkeypatch.setattr(llm_response_cache, "DB_PATH", db_path)
    metadata = llm_response_cache.cache_metadata(
        purpose="brief",
        model="test-model",
        prompt_version="v1",
        messages=[{"role": "user", "content": "input"}],
    )
    llm_response_cache.save_response(metadata, '{"version": 1}')
    assert llm_response_cache.get_cached_response(metadata) == '{"version": 1}'

    llm_response_cache.save_response(metadata, '{"version": 2}')

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT response_content, hit_count, last_used_at FROM llm_response_cache"
        ).fetchone()
    finally:
        conn.close()
    assert row == ('{"version": 2}', 0, None)

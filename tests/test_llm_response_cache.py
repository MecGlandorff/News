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

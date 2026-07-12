from src.observability.database import get_db as _get_db
from src.observability.runs import _utc_now
from src.observability.state import (
    LAST_LLM_CALL_ID as _LAST_LLM_CALL_ID,
    current_run_id,
)


def _usage_value(usage, name):
    if usage is None:
        return None
    if isinstance(usage, dict):
        return usage.get(name)
    return getattr(usage, name, None)


def record_llm_call(
    *,
    model,
    purpose,
    prompt_version=None,
    latency_ms=None,
    usage=None,
    schema_failure=False,
    retry_count=0,
    error_type=None,
    error_message=None,
    run_id=None,
):
    run_id = current_run_id() if run_id is None else run_id
    if run_id is None:
        return None

    prompt_tokens = _usage_value(usage, "prompt_tokens")
    completion_tokens = _usage_value(usage, "completion_tokens")
    conn = _get_db()
    try:
        with conn:
            cur = conn.execute(
                """
                INSERT INTO llm_calls (
                    run_id, model, purpose, prompt_version, latency_ms,
                    prompt_tokens, completion_tokens, schema_failure,
                    retry_count, error_type, error_message, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    model,
                    purpose,
                    prompt_version,
                    latency_ms,
                    prompt_tokens,
                    completion_tokens,
                    1 if schema_failure else 0,
                    retry_count,
                    error_type,
                    error_message,
                    _utc_now(),
                ),
            )
            call_id = cur.lastrowid
    finally:
        conn.close()

    _LAST_LLM_CALL_ID.set(call_id)
    return call_id


def mark_last_call_schema_failure(error_message=None):
    call_id = _LAST_LLM_CALL_ID.get()
    mark_call_schema_failure(call_id, error_message)


def mark_call_schema_failure(call_id, error_message=None):
    if call_id is None:
        return
    conn = _get_db()
    try:
        with conn:
            conn.execute(
                """
                UPDATE llm_calls
                SET schema_failure = 1,
                    error_type = COALESCE(error_type, ?),
                    error_message = COALESCE(error_message, ?)
                WHERE call_id = ?
                """,
                ("schema", error_message, call_id),
            )
    finally:
        conn.close()

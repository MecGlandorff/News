from __future__ import annotations

from pathlib import Path
from typing import Any

from src.observability import audit as _audit
from src.observability import console as _console
from src.observability import costs as _costs
from src.observability import llm_calls as _llm_calls
from src.observability import markdown as _markdown
from src.observability import runs as _runs
from src.observability import state as _state


DB_PATH = Path("data/stories.db")
RUN_ARTIFACTS_DIR = Path("run_artifacts")


def _resolve_db_path(db_path: str | Path | None) -> Path:
    if db_path is not None:
        return Path(db_path)
    return _state.active_db_path() or DB_PATH


def start_run(cli_args: Any, run_date: str | None = None, *, db_path: str | Path | None = None):
    with _state.use_db_path(_resolve_db_path(db_path)):
        return _runs.start_run(cli_args, run_date=run_date)


def set_current_run_id(run_id: int, *, db_path: str | Path | None = None) -> None:
    _state.set_current_run_id(run_id, _resolve_db_path(db_path))


def clear_current_run_id() -> None:
    _state.clear_current_run_id()


def current_run_id() -> int | None:
    return _state.current_run_id()


def update_run_totals(run_id: int | None = None, *, db_path=None, **totals) -> None:
    with _state.use_db_path(_resolve_db_path(db_path)):
        _runs.update_run_totals(run_id, **totals)


def increment_run_totals(run_id: int | None = None, *, db_path=None, **totals) -> None:
    with _state.use_db_path(_resolve_db_path(db_path)):
        _runs.increment_run_totals(run_id, **totals)


def increment_cache_hits(
    count=1,
    run_id=None,
    *,
    layer="other",
    purpose=None,
    db_path=None,
) -> None:
    with _state.use_db_path(_resolve_db_path(db_path)):
        _runs.increment_cache_hits(count, run_id, layer=layer, purpose=purpose)


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
    db_path=None,
):
    with _state.use_db_path(_resolve_db_path(db_path)):
        return _llm_calls.record_llm_call(
            model=model,
            purpose=purpose,
            prompt_version=prompt_version,
            latency_ms=latency_ms,
            usage=usage,
            schema_failure=schema_failure,
            retry_count=retry_count,
            error_type=error_type,
            error_message=error_message,
            run_id=run_id,
        )


def mark_last_call_schema_failure(error_message=None, *, db_path=None) -> None:
    with _state.use_db_path(_resolve_db_path(db_path)):
        _llm_calls.mark_last_call_schema_failure(error_message)


def mark_call_schema_failure(call_id, error_message=None, *, db_path=None) -> None:
    with _state.use_db_path(_resolve_db_path(db_path)):
        _llm_calls.mark_call_schema_failure(call_id, error_message)


def finish_run(run_id, status="ok", error_message=None, *, db_path=None) -> None:
    with _state.use_db_path(_resolve_db_path(db_path)):
        _runs.finish_run(run_id, status=status, error_message=error_message)


def get_run_report_data(run_id, *, db_path=None):
    with _state.use_db_path(_resolve_db_path(db_path)):
        return _runs.get_run_report_data(run_id)


def novelty_audit(run_id, limit=5, *, db_path=None):
    with _state.use_db_path(_resolve_db_path(db_path)):
        return _audit.novelty_audit(run_id, limit=limit)


def llm_cost_summary(run_id, *, db_path=None):
    with _state.use_db_path(_resolve_db_path(db_path)):
        return _costs.llm_cost_summary(run_id)


def novelty_audit_lines(run_id, limit=5, *, db_path=None):
    with _state.use_db_path(_resolve_db_path(db_path)):
        return _console.novelty_audit_lines(run_id, limit=limit)


def pipeline_report(run_id, *, db_path=None) -> str:
    with _state.use_db_path(_resolve_db_path(db_path)):
        return _console.pipeline_report(run_id)


def run_report_markdown(run_id, *, db_path=None) -> str:
    with _state.use_db_path(_resolve_db_path(db_path)):
        return _markdown.run_report_markdown(run_id)


def write_run_report_artifact(run_id, output_dir=None, *, db_path=None):
    output_dir = RUN_ARTIFACTS_DIR if output_dir is None else output_dir
    with _state.use_db_path(_resolve_db_path(db_path)):
        return _markdown.write_run_report_artifact(run_id, output_dir=output_dir)


__all__ = [
    "DB_PATH",
    "RUN_ARTIFACTS_DIR",
    "clear_current_run_id",
    "current_run_id",
    "finish_run",
    "get_run_report_data",
    "increment_cache_hits",
    "increment_run_totals",
    "llm_cost_summary",
    "mark_call_schema_failure",
    "mark_last_call_schema_failure",
    "novelty_audit",
    "novelty_audit_lines",
    "pipeline_report",
    "record_llm_call",
    "run_report_markdown",
    "set_current_run_id",
    "start_run",
    "update_run_totals",
    "write_run_report_artifact",
]

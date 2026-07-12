from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Iterator


CURRENT_RUN_ID: ContextVar[int | None] = ContextVar("current_run_id", default=None)
LAST_LLM_CALL_ID: ContextVar[int | None] = ContextVar("last_llm_call_id", default=None)
_ACTIVE_DB_PATH: ContextVar[Path | None] = ContextVar("active_observability_db", default=None)
_CALL_DB_PATH: ContextVar[Path | None] = ContextVar("observability_call_db", default=None)


def set_current_run_id(run_id: int, db_path: Path) -> None:
    CURRENT_RUN_ID.set(run_id)
    LAST_LLM_CALL_ID.set(None)
    _ACTIVE_DB_PATH.set(db_path)


def clear_current_run_id() -> None:
    CURRENT_RUN_ID.set(None)
    LAST_LLM_CALL_ID.set(None)
    _ACTIVE_DB_PATH.set(None)


def current_run_id() -> int | None:
    return CURRENT_RUN_ID.get()


def active_db_path() -> Path | None:
    return _ACTIVE_DB_PATH.get()


def current_db_path() -> Path:
    path = _CALL_DB_PATH.get() or _ACTIVE_DB_PATH.get()
    if path is None:
        raise RuntimeError("Observability database path is not configured")
    return path


@contextmanager
def use_db_path(db_path: Path) -> Iterator[None]:
    token = _CALL_DB_PATH.set(db_path)
    try:
        yield
    finally:
        _CALL_DB_PATH.reset(token)

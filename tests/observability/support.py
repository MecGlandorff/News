import sqlite3
from types import SimpleNamespace


def _row(db_path, query, params=()):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return dict(conn.execute(query, params).fetchone())
    finally:
        conn.close()


def _run_args():
    return SimpleNamespace(today="2026-05-07", pipeline_report=True)

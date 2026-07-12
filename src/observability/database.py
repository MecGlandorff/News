from __future__ import annotations

import sqlite3

from src.observability.schema import _create_schema
from src.observability.state import current_db_path


def get_db() -> sqlite3.Connection:
    db_path = current_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _create_schema(conn)
    conn.commit()
    return conn

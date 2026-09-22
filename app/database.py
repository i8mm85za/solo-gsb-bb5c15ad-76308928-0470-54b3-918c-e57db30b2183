"""SQLite persistence. One connection per request; WAL mode for concurrency."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from typing import Iterator

DB_PATH = os.environ.get("ALIGN_DB_PATH", "/data/alignments.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id                  TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    reference_beats_ms  TEXT NOT NULL,
    onset_times_ms      TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'pending',
    error               TEXT,
    params              TEXT NOT NULL,
    pairs               TEXT,
    intervals           TEXT,
    stats               TEXT,
    created_at          TEXT NOT NULL,
    aligned_at          TEXT
);
"""


def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    with get_conn() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def loads(value: str | None, default=None):
    if value is None:
        return default
    return json.loads(value)

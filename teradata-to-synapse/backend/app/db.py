"""SQLite persistence for jobs and their discovered objects."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    repo_url    TEXT NOT NULL,
    status      TEXT NOT NULL,
    error       TEXT,
    source_dir  TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS objects (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id         TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    rel_path       TEXT NOT NULL,
    object_type    TEXT NOT NULL,
    object_name    TEXT NOT NULL,
    status         TEXT NOT NULL,
    output_path    TEXT,
    rules          TEXT NOT NULL DEFAULT '[]',
    warnings       TEXT NOT NULL DEFAULT '[]',
    manual_reason  TEXT,
    UNIQUE (job_id, rel_path)
);
CREATE INDEX IF NOT EXISTS ix_objects_job ON objects(job_id);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def _object_row(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["rules"] = json.loads(d["rules"])
    d["warnings"] = json.loads(d["warnings"])
    return d


def insert_job(job_id: str, repo_url: str, status: str) -> None:
    ts = now()
    with connect() as conn:
        conn.execute(
            "INSERT INTO jobs (id, repo_url, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (job_id, repo_url, status, ts, ts),
        )


def update_job(job_id: str, **fields: Any) -> None:
    fields["updated_at"] = now()
    cols = ", ".join(f"{k} = ?" for k in fields)
    with connect() as conn:
        conn.execute(f"UPDATE jobs SET {cols} WHERE id = ?", (*fields.values(), job_id))


def get_job(job_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


def insert_objects(job_id: str, objects: list[dict[str, Any]]) -> None:
    with connect() as conn:
        conn.executemany(
            "INSERT INTO objects (job_id, rel_path, object_type, object_name, status) VALUES (?, ?, ?, ?, ?)",
            [(job_id, o["rel_path"], o["object_type"], o["object_name"], o["status"]) for o in objects],
        )


def list_objects(job_id: str) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM objects WHERE job_id = ? ORDER BY rel_path", (job_id,)).fetchall()
    return [_object_row(r) for r in rows]


def get_object(job_id: str, object_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM objects WHERE job_id = ? AND id = ?", (job_id, object_id)).fetchone()
    return _object_row(row) if row else None


def update_object(object_id: int, **fields: Any) -> None:
    for key in ("rules", "warnings"):
        if key in fields:
            fields[key] = json.dumps(fields[key])
    cols = ", ".join(f"{k} = ?" for k in fields)
    with connect() as conn:
        conn.execute(f"UPDATE objects SET {cols} WHERE id = ?", (*fields.values(), object_id))

"""SQLite schema and connection helpers for the harness."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    goal TEXT,
    verify_cmd TEXT,
    complexity TEXT DEFAULT 'medium',
    priority INTEGER DEFAULT 50,
    status TEXT DEFAULT 'pending',
    working_dir TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stages (
    stage_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    stage_type TEXT NOT NULL,
    stage_order INTEGER NOT NULL,
    model_role TEXT NOT NULL,
    assigned_model TEXT,
    assigned_provider TEXT,
    status TEXT DEFAULT 'pending',
    handoff_doc_path TEXT,
    result_summary TEXT,
    token_used INTEGER DEFAULT 0,
    duration_sec REAL DEFAULT 0,
    started_at TEXT,
    finished_at TEXT,
    retry_count INTEGER DEFAULT 0,
    verify_cmd TEXT,
    metadata TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS permission_requests (
    request_id TEXT PRIMARY KEY,
    stage_id TEXT NOT NULL REFERENCES stages(stage_id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    context TEXT,
    risk_level TEXT NOT NULL,
    decision TEXT,
    voters TEXT DEFAULT '[]',
    decided_at TEXT
);

CREATE TABLE IF NOT EXISTS quota_events (
    event_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    account_email TEXT,
    event_type TEXT NOT NULL,
    details TEXT DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_status_priority
    ON tasks(status, priority DESC, created_at ASC);

CREATE INDEX IF NOT EXISTS idx_stages_task_order
    ON stages(task_id, stage_order ASC);

CREATE INDEX IF NOT EXISTS idx_stages_task_status
    ON stages(task_id, status, stage_order ASC);
"""


class HarnessDB:
    """Small wrapper around a SQLite database file."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

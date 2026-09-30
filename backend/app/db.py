"""SQLite access layer. Uses the stdlib ``sqlite3`` module."""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = os.environ.get("POOL_DB_PATH", str(Path(__file__).resolve().parent.parent / "data" / "pooling.db"))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_db_path() -> str:
    return DB_PATH


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS batches (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT NOT NULL UNIQUE,
    num_pools         INTEGER NOT NULL,
    max_pool_volume   REAL NOT NULL,
    min_transfer      REAL NOT NULL,
    created_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS samples (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id          INTEGER NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    name              TEXT NOT NULL,
    concentration     REAL NOT NULL,
    available_volume  REAL NOT NULL,
    target_amount     REAL NOT NULL,
    index_seq         TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    UNIQUE(batch_id, name)
);

CREATE TABLE IF NOT EXISTS plans (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id          INTEGER NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    version           INTEGER NOT NULL,
    created_at        TEXT NOT NULL,
    trigger          TEXT NOT NULL,
    summary           TEXT NOT NULL,
    UNIQUE(batch_id, version)
);

CREATE TABLE IF NOT EXISTS pools (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id          INTEGER NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    plan_id           INTEGER NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    pool_no           INTEGER NOT NULL,
    locked            INTEGER NOT NULL DEFAULT 0,
    locked_at         TEXT,
    recipe_json       TEXT,
    UNIQUE(batch_id, pool_no)
);

CREATE TABLE IF NOT EXISTS assignments (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    pool_id           INTEGER NOT NULL REFERENCES pools(id) ON DELETE CASCADE,
    sample_id         INTEGER NOT NULL REFERENCES samples(id) ON DELETE CASCADE,
    pool_no           INTEGER NOT NULL,
    transfer_volume   REAL NOT NULL,
    concentration     REAL NOT NULL,
    target_amount     REAL NOT NULL,
    index_seq         TEXT NOT NULL,
    UNIQUE(sample_id)
);

CREATE TABLE IF NOT EXISTS unassigned (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id           INTEGER NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    sample_id         INTEGER REFERENCES samples(id) ON DELETE SET NULL,
    name              TEXT NOT NULL,
    index_seq         TEXT NOT NULL,
    concentration     REAL NOT NULL,
    transfer_need     REAL NOT NULL,
    reasons           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS plan_versions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id           INTEGER NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    batch_id          INTEGER NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    version           INTEGER NOT NULL,
    created_at        TEXT NOT NULL,
    trigger          TEXT NOT NULL,
    note              TEXT NOT NULL,
    warnings_json     TEXT NOT NULL
);
"""


def init_db() -> None:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()

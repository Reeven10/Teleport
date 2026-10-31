"""SQLite schema definitions and migrations for history store (P3)."""

from __future__ import annotations

import sqlite3
import time

CURRENT_SCHEMA_VERSION = 1

INIT_SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS devices (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    os TEXT NOT NULL,
    arch TEXT NOT NULL,
    cpu_cores INTEGER NOT NULL,
    ram_mb INTEGER NOT NULL,
    gpu TEXT,
    disk_free_mb INTEGER NOT NULL,
    agent_version TEXT NOT NULL,
    data_json TEXT NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
    id TEXT PRIMARY KEY,
    ts REAL NOT NULL,
    workload_id TEXT NOT NULL,
    trigger TEXT NOT NULL,
    decision TEXT NOT NULL,
    reasons_json TEXT NOT NULL,
    migration_id TEXT,
    data_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS migrations (
    id TEXT PRIMARY KEY,
    workload_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    phase TEXT NOT NULL,
    trigger TEXT NOT NULL,
    link TEXT NOT NULL,
    decision TEXT,
    bytes_total INTEGER NOT NULL,
    bytes_done INTEGER NOT NULL,
    started_at REAL NOT NULL,
    ended_at REAL,
    data_json TEXT NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_decisions_ts ON decisions(ts);
CREATE INDEX IF NOT EXISTS idx_migrations_started ON migrations(started_at);
CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at);
"""


def initialize_database(conn: sqlite3.Connection) -> int:
    """Apply schema migrations and return the current schema version."""
    cursor = conn.cursor()
    cursor.executescript(INIT_SCHEMA_SQL)

    cursor.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1;")
    row = cursor.fetchone()
    if row is None:
        now = time.time()
        cursor.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (?, ?);",
            (CURRENT_SCHEMA_VERSION, now),
        )
        conn.commit()
        return CURRENT_SCHEMA_VERSION
    return int(row[0])


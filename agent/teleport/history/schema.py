"""SQLite schema definitions and migrations for history store (P3)."""

from __future__ import annotations

import sqlite3
import time

CURRENT_SCHEMA_VERSION = 2

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
    first_seen REAL NOT NULL DEFAULT 0,
    last_seen REAL NOT NULL DEFAULT 0,
    link_types_json TEXT NOT NULL DEFAULT '[]',
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
    snapshots_json TEXT NOT NULL DEFAULT '[]',
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
CREATE INDEX IF NOT EXISTS idx_migrations_source ON migrations(source_id);
CREATE INDEX IF NOT EXISTS idx_migrations_target ON migrations(target_id);
CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at);
"""


def initialize_database(conn: sqlite3.Connection) -> int:
    """Apply schema migrations and return the current schema version."""
    cursor = conn.cursor()
    cursor.executescript(INIT_SCHEMA_SQL)

    # Check and apply migrations for existing tables if needed
    cursor.execute("PRAGMA table_info(devices);")
    dev_cols = {row[1] for row in cursor.fetchall()}
    if "first_seen" not in dev_cols:
        cursor.execute("ALTER TABLE devices ADD COLUMN first_seen REAL NOT NULL DEFAULT 0;")
    if "last_seen" not in dev_cols:
        cursor.execute("ALTER TABLE devices ADD COLUMN last_seen REAL NOT NULL DEFAULT 0;")
    if "link_types_json" not in dev_cols:
        cursor.execute("ALTER TABLE devices ADD COLUMN link_types_json TEXT NOT NULL DEFAULT '[]';")

    cursor.execute("PRAGMA table_info(migrations);")
    mig_cols = {row[1] for row in cursor.fetchall()}
    if "snapshots_json" not in mig_cols:
        cursor.execute("ALTER TABLE migrations ADD COLUMN snapshots_json TEXT NOT NULL DEFAULT '[]';")

    cursor.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1;")
    row = cursor.fetchone()
    now = time.time()
    if row is None:
        cursor.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (?, ?);",
            (CURRENT_SCHEMA_VERSION, now),
        )
        conn.commit()
        return CURRENT_SCHEMA_VERSION

    current_ver = int(row[0])
    if current_ver < CURRENT_SCHEMA_VERSION:
        cursor.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (?, ?);",
            (CURRENT_SCHEMA_VERSION, now),
        )
        conn.commit()
        return CURRENT_SCHEMA_VERSION

    return current_ver

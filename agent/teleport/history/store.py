"""SQLite-backed HistoryStore implementation (P3).

Persists devices, migrations, decisions with reasons, and bus events.
Subscribes to live event bus events and supports history querying.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
from collections.abc import Callable
from pathlib import Path

from contract.contract import (
    AuthorityChangeEvent,
    DecisionLog,
    DecisionLoggedEvent,
    DeviceInfo,
    DevicePairedEvent,
    MigrationStatus,
    MigrationStatusEvent,
)

from ..core.context import Context
from .schema import initialize_database


class SqliteHistoryStore:
    """Persistent SQLite history store under TELEPORT_HOME."""

    def __init__(self, ctx: Context, db_path: Path | None = None) -> None:
        self.ctx = ctx
        if db_path is not None:
            self.db_path = db_path
        elif hasattr(ctx, "settings") and hasattr(ctx.settings, "home"):
            self.db_path = ctx.settings.home / "teleport_history.db"
        else:
            self.db_path = Path.home() / ".teleport" / "teleport_history.db"

        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()
        self._unsub_callbacks: list[Callable[[], None]] = []

    def _get_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                timeout=30.0,
            )
            initialize_database(self._conn)
        return self._conn

    async def startup(self) -> None:
        """Initialize database schema and register event bus subscriptions."""
        await asyncio.to_thread(self._get_connection)

        if hasattr(self.ctx, "bus"):
            self._unsub_callbacks.append(
                self.ctx.bus.subscribe(DevicePairedEvent, self._on_device_paired)
            )
            self._unsub_callbacks.append(
                self.ctx.bus.subscribe(DecisionLoggedEvent, self._on_decision_logged)
            )
            self._unsub_callbacks.append(
                self.ctx.bus.subscribe(MigrationStatusEvent, self._on_migration_status)
            )
            self._unsub_callbacks.append(
                self.ctx.bus.subscribe(AuthorityChangeEvent, self._on_authority_change)
            )

    async def shutdown(self) -> None:
        """Unsubscribe handlers and close the SQLite database connection."""
        for unsub in self._unsub_callbacks:
            try:
                unsub()
            except Exception:
                pass
        self._unsub_callbacks.clear()

        def _close() -> None:
            with self._lock:
                if self._conn is not None:
                    try:
                        self._conn.close()
                    except Exception:
                        pass
                    self._conn = None

        await asyncio.to_thread(_close)

    # ------------------------------------------------------------ Event Handlers

    async def _on_device_paired(self, event: DevicePairedEvent) -> None:
        await self._persist_device(event.device)

    async def _on_decision_logged(self, event: DecisionLoggedEvent) -> None:
        await self._persist_decision(event.log)

    async def _on_migration_status(self, event: MigrationStatusEvent) -> None:
        await self._persist_migration(event.status)

    async def _on_authority_change(self, event: AuthorityChangeEvent) -> None:
        now = time.time()
        payload = event.authority.model_dump_json()

        def _insert() -> None:
            with self._lock:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO events (event_type, payload_json, created_at) VALUES (?, ?, ?);",
                    ("authority.change", payload, now),
                )
                conn.commit()

        await asyncio.to_thread(_insert)

    # ------------------------------------------------------------ Persistence Internals

    async def _persist_device(self, device: DeviceInfo) -> None:
        now = time.time()
        data_json = device.model_dump_json()

        def _upsert() -> None:
            with self._lock:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO devices (
                        id, name, os, arch, cpu_cores, ram_mb, gpu, disk_free_mb,
                        agent_version, data_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        name = excluded.name,
                        os = excluded.os,
                        arch = excluded.arch,
                        cpu_cores = excluded.cpu_cores,
                        ram_mb = excluded.ram_mb,
                        gpu = excluded.gpu,
                        disk_free_mb = excluded.disk_free_mb,
                        agent_version = excluded.agent_version,
                        data_json = excluded.data_json,
                        updated_at = excluded.updated_at;
                    """,
                    (
                        device.id,
                        device.name,
                        device.os,
                        device.arch,
                        device.cpuCores,
                        device.ramMb,
                        device.gpu,
                        device.diskFreeMb,
                        device.agentVersion,
                        data_json,
                        now,
                    ),
                )
                conn.commit()

        await asyncio.to_thread(_upsert)

    async def _persist_decision(self, log: DecisionLog) -> None:
        data_json = log.model_dump_json()
        reasons_json = json.dumps([r.model_dump() for r in log.reasons])

        def _insert() -> None:
            with self._lock:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO decisions (
                        id, ts, workload_id, trigger, decision, reasons_json, migration_id, data_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        log.id,
                        log.ts,
                        log.workloadId,
                        log.trigger,
                        log.decision,
                        reasons_json,
                        log.migrationId,
                        data_json,
                    ),
                )
                conn.commit()

        await asyncio.to_thread(_insert)

    async def _persist_migration(self, status: MigrationStatus) -> None:
        now = time.time()
        data_json = status.model_dump_json()

        def _upsert() -> None:
            with self._lock:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO migrations (
                        id, workload_id, source_id, target_id, phase, trigger, link, decision,
                        bytes_total, bytes_done, started_at, ended_at, data_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        phase = excluded.phase,
                        decision = excluded.decision,
                        bytes_total = excluded.bytes_total,
                        bytes_done = excluded.bytes_done,
                        ended_at = excluded.ended_at,
                        data_json = excluded.data_json,
                        updated_at = excluded.updated_at;
                    """,
                    (
                        status.id,
                        status.workloadId,
                        status.sourceId,
                        status.targetId,
                        status.phase,
                        status.trigger,
                        status.link,
                        status.decision,
                        status.bytesTotal,
                        status.bytesDone,
                        status.startedAt,
                        status.endedAt,
                        data_json,
                        now,
                    ),
                )
                conn.commit()

        await asyncio.to_thread(_upsert)

    # ------------------------------------------------------------ HistoryStore Protocol API

    async def log_decision(self, log: DecisionLog) -> None:
        """Persist a decision and publish decision.logged to the event bus."""
        await self._persist_decision(log)
        if hasattr(self.ctx, "bus"):
            await self.ctx.bus.publish(DecisionLoggedEvent(log=log))

    async def list_devices(self) -> list[DeviceInfo]:
        """Return all known devices ordered by most recently seen."""
        def _query() -> list[DeviceInfo]:
            with self._lock:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT data_json FROM devices ORDER BY updated_at DESC;")
                rows = cursor.fetchall()
                return [DeviceInfo.model_validate_json(row[0]) for row in rows]

        return await asyncio.to_thread(_query)

    async def list_migrations(self) -> list[MigrationStatus]:
        """Return all recorded migrations ordered by start time descending."""
        def _query() -> list[MigrationStatus]:
            with self._lock:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT data_json FROM migrations ORDER BY started_at DESC;")
                rows = cursor.fetchall()
                return [MigrationStatus.model_validate_json(row[0]) for row in rows]

        return await asyncio.to_thread(_query)

    async def list_decisions(self) -> list[DecisionLog]:
        """Return all logged feasibility and migration decisions ordered by timestamp descending."""
        def _query() -> list[DecisionLog]:
            with self._lock:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT data_json FROM decisions ORDER BY ts DESC;")
                rows = cursor.fetchall()
                return [DecisionLog.model_validate_json(row[0]) for row in rows]

        return await asyncio.to_thread(_query)


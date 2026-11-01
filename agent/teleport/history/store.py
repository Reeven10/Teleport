"""SQLite-backed HistoryStore implementation (P3).

Persists devices, migrations, decisions with reasons, and bus events.
Subscribes to live event bus events and supports history querying, filtering,
revisit, bounded replay snapshots, and full JSON export.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

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
from .router import build_history_router
from .schema import CURRENT_SCHEMA_VERSION, initialize_database

MAX_REPLAY_SNAPSHOTS = 100
log = logging.getLogger("teleport.history")


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
        self._last_snapshot_ts: dict[str, float] = {}

        # Mountable FastAPI router for automatic app integration (P3-11)
        self.router = build_history_router(ctx)

    def _get_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                self._conn = sqlite3.connect(
                    str(self.db_path),
                    check_same_thread=False,
                    timeout=30.0,
                )
                initialize_database(self._conn)
            except sqlite3.DatabaseError as exc:
                log.warning(
                    "Teleport history database at %s is corrupted (%s); "
                    "backing up and rebuilding a fresh database.",
                    self.db_path,
                    exc,
                )
                if self._conn is not None:
                    try:
                        self._conn.close()
                    except Exception:
                        pass
                    self._conn = None
                corrupt_backup = self.db_path.with_name(
                    f"{self.db_path.name}.corrupted.{int(time.time())}"
                )
                try:
                    self.db_path.rename(corrupt_backup)
                except Exception:
                    pass
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
        await self._log_raw_event("device.paired", event.device.model_dump_json())

    async def _on_decision_logged(self, event: DecisionLoggedEvent) -> None:
        await self._persist_decision(event.log)
        await self._log_raw_event("decision.logged", event.log.model_dump_json())

    async def _on_migration_status(self, event: MigrationStatusEvent) -> None:
        await self._persist_migration(event.status)
        await self._log_raw_event("migration.status", event.status.model_dump_json())

    async def _on_authority_change(self, event: AuthorityChangeEvent) -> None:
        payload = event.authority.model_dump_json()
        await self._log_raw_event("authority.change", payload)

    async def _log_raw_event(self, event_type: str, payload_json: str) -> None:
        now = time.time()

        def _insert() -> None:
            with self._lock:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO events (event_type, payload_json, created_at) VALUES (?, ?, ?);",
                    (event_type, payload_json, now),
                )
                conn.commit()

        await asyncio.to_thread(_insert)

    async def clear_all(self) -> dict[str, int]:
        """Start fresh: delete every recorded device, migration, decision and event. The store keeps
        recording from now on; only the old rows go."""

        def _clear() -> dict[str, int]:
            with self._lock:
                conn = self._get_connection()
                counts = {}
                for table in ("devices", "migrations", "decisions", "events"):
                    counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table};").fetchone()[0]
                    conn.execute(f"DELETE FROM {table};")
                conn.commit()
                self._last_snapshot_ts.clear()
                return counts

        return await asyncio.to_thread(_clear)

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
                        agent_version, data_json, first_seen, last_seen, link_types_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        last_seen = excluded.last_seen,
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
                        now,
                        "[]",
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

                # Snapshot sampling: at most once per second or terminal state
                last_snap = self._last_snapshot_ts.get(status.id, 0.0)
                is_terminal = str(status.phase).upper() in ("COMPLETED", "FAILED", "ABORTED")
                should_snap = (now - last_snap >= 1.0) or (last_snap == 0.0) or is_terminal

                # Load existing snapshots
                cursor.execute("SELECT snapshots_json FROM migrations WHERE id = ?;", (status.id,))
                row = cursor.fetchone()
                snapshots: list[dict[str, Any]] = []
                if row and row[0]:
                    try:
                        snapshots = json.loads(row[0])
                    except Exception:
                        snapshots = []

                if should_snap:
                    snap_item = {
                        "ts": now,
                        "phase": str(status.phase),
                        "bytesDone": status.bytesDone,
                        "bytesTotal": status.bytesTotal,
                        "link": str(status.link),
                        "interruptionMs": status.interruptionMs,
                        "error": status.error,
                    }
                    snapshots.append(snap_item)
                    # Keep bounded size (max 100 snapshots, keeping initial and latest)
                    if len(snapshots) > MAX_REPLAY_SNAPSHOTS:
                        snapshots = [snapshots[0]] + snapshots[-(MAX_REPLAY_SNAPSHOTS - 1):]
                    self._last_snapshot_ts[status.id] = now

                snapshots_json = json.dumps(snapshots)

                cursor.execute(
                    """
                    INSERT INTO migrations (
                        id, workload_id, source_id, target_id, phase, trigger, link, decision,
                        bytes_total, bytes_done, started_at, ended_at, data_json, snapshots_json,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        phase = excluded.phase,
                        decision = excluded.decision,
                        bytes_total = excluded.bytes_total,
                        bytes_done = excluded.bytes_done,
                        ended_at = excluded.ended_at,
                        data_json = excluded.data_json,
                        snapshots_json = excluded.snapshots_json,
                        updated_at = excluded.updated_at;
                    """,
                    (
                        status.id,
                        status.workloadId,
                        status.sourceId,
                        status.targetId,
                        str(status.phase),
                        status.trigger,
                        str(status.link),
                        status.decision,
                        status.bytesTotal,
                        status.bytesDone,
                        status.startedAt,
                        status.endedAt,
                        data_json,
                        snapshots_json,
                        now,
                    ),
                )

                # Track link type used on source and target devices
                link_val = str(status.link)
                for dev_id in (status.sourceId, status.targetId):
                    cursor.execute("SELECT link_types_json FROM devices WHERE id = ?;", (dev_id,))
                    d_row = cursor.fetchone()
                    if d_row:
                        try:
                            ltypes: list[str] = json.loads(d_row[0]) if d_row[0] else []
                        except Exception:
                            ltypes = []
                        if link_val not in ltypes:
                            ltypes.append(link_val)
                            cursor.execute(
                                "UPDATE devices SET link_types_json = ?, last_seen = ? WHERE id = ?;",
                                (json.dumps(ltypes), now, dev_id),
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

    async def list_migrations(
        self,
        device: str | None = None,
        workload: str | None = None,
        decision: str | None = None,
        outcome: str | None = None,
        since: float | None = None,
        until: float | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MigrationStatus]:
        """Return migrations with optional filtering and paging, ordered newest first."""

        def _query() -> list[MigrationStatus]:
            with self._lock:
                conn = self._get_connection()
                cursor = conn.cursor()
                conditions: list[str] = []
                params: list[Any] = []

                if device is not None:
                    conditions.append("(source_id = ? OR target_id = ?)")
                    params.extend([device, device])
                if workload is not None:
                    conditions.append("workload_id = ?")
                    params.append(workload)
                if decision is not None:
                    conditions.append("decision = ?")
                    params.append(decision)
                if outcome is not None:
                    conditions.append("phase = ?")
                    params.append(outcome)
                if since is not None:
                    conditions.append("started_at >= ?")
                    params.append(since)
                if until is not None:
                    conditions.append("started_at <= ?")
                    params.append(until)

                where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
                sql = (
                    f"SELECT data_json FROM migrations {where_clause} "
                    "ORDER BY started_at DESC LIMIT ? OFFSET ?;"
                )
                params.extend([limit, offset])
                cursor.execute(sql, params)
                rows = cursor.fetchall()
                return [MigrationStatus.model_validate_json(row[0]) for row in rows]

        return await asyncio.to_thread(_query)

    async def list_decisions(
        self,
        limit: int = 100,
        offset: int = 0,
        workload: str | None = None,
    ) -> list[DecisionLog]:
        """Return logged decisions ordered by timestamp descending."""

        def _query() -> list[DecisionLog]:
            with self._lock:
                conn = self._get_connection()
                cursor = conn.cursor()
                if workload:
                    cursor.execute(
                        "SELECT data_json FROM decisions WHERE workload_id = ? "
                        "ORDER BY ts DESC LIMIT ? OFFSET ?;",
                        (workload, limit, offset),
                    )
                else:
                    cursor.execute(
                        "SELECT data_json FROM decisions ORDER BY ts DESC LIMIT ? OFFSET ?;",
                        (limit, offset),
                    )
                rows = cursor.fetchall()
                return [DecisionLog.model_validate_json(row[0]) for row in rows]

        return await asyncio.to_thread(_query)

    # ------------------------------------------------------------ Device Revisit & Summaries

    async def list_device_summaries(self) -> list[dict[str, Any]]:
        """Return every device ever seen with first/last seen, link types, and migration count."""

        def _query() -> list[dict[str, Any]]:
            with self._lock:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT d.id, d.first_seen, d.last_seen, d.link_types_json, d.data_json,
                           (SELECT COUNT(*) FROM migrations m WHERE m.source_id = d.id OR m.target_id = d.id)
                    FROM devices d
                    ORDER BY d.last_seen DESC;
                    """
                )
                results = []
                for row in cursor.fetchall():
                    dev_id, first_seen, last_seen, ltypes_json, data_json, mig_count = row
                    device_dict = json.loads(data_json)
                    try:
                        link_types = json.loads(ltypes_json) if ltypes_json else []
                    except Exception:
                        link_types = []
                    results.append(
                        {
                            "id": dev_id,
                            "firstSeen": first_seen or device_dict.get("updatedAt", 0),
                            "lastSeen": last_seen or device_dict.get("updatedAt", 0),
                            "device": device_dict,
                            "linkTypes": link_types,
                            "migrationCount": mig_count,
                        }
                    )
                return results

        return await asyncio.to_thread(_query)

    async def get_device_detail(self, device_id: str) -> dict[str, Any] | None:
        """Return device history detail with all migrations to and from that device."""

        def _query() -> dict[str, Any] | None:
            with self._lock:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT d.id, d.first_seen, d.last_seen, d.link_types_json, d.data_json
                    FROM devices d WHERE d.id = ?;
                    """,
                    (device_id,),
                )
                row = cursor.fetchone()
                if not row:
                    return None

                dev_id, first_seen, last_seen, ltypes_json, data_json = row
                device_dict = json.loads(data_json)
                try:
                    link_types = json.loads(ltypes_json) if ltypes_json else []
                except Exception:
                    link_types = []

                # Migrations to and from this device
                cursor.execute(
                    "SELECT data_json FROM migrations WHERE source_id = ? OR target_id = ? "
                    "ORDER BY started_at DESC;",
                    (device_id, device_id),
                )
                mig_rows = cursor.fetchall()
                migrations = [json.loads(r[0]) for r in mig_rows]

                return {
                    "id": dev_id,
                    "firstSeen": first_seen,
                    "lastSeen": last_seen,
                    "device": device_dict,
                    "linkTypes": link_types,
                    "migrationCount": len(migrations),
                    "migrations": migrations,
                }

        return await asyncio.to_thread(_query)

    # ------------------------------------------------------------ Full Record & Export

    async def get_migration(self, migration_id: str) -> dict[str, Any] | None:
        """Return the complete migration record including manifest summary, authority timeline,

        metrics, errors, chronological event timeline, and replay snapshots.
        """

        def _query() -> dict[str, Any] | None:
            with self._lock:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT data_json, snapshots_json FROM migrations WHERE id = ?;",
                    (migration_id,),
                )
                row = cursor.fetchone()
                if not row:
                    return None

                status_dict = json.loads(row[0])
                snapshots: list[dict[str, Any]] = []
                if row[1]:
                    try:
                        snapshots = json.loads(row[1])
                    except Exception:
                        snapshots = []

                workload_id = status_dict.get("workloadId", "")
                source_id = status_dict.get("sourceId", "")
                target_id = status_dict.get("targetId", "")

                # Manifest summary
                manifest_summary: dict[str, Any] = {"id": workload_id, "name": workload_id}
                if hasattr(self.ctx, "workloads"):
                    try:
                        for w in self.ctx.workloads.list():
                            if w.id == workload_id:
                                manifest_summary = {
                                    "id": w.id,
                                    "name": w.name,
                                    "command": w.command,
                                    "runtime": f"{w.runtime.name} {w.runtime.minVersion}",
                                    "minRamMb": w.minRamMb,
                                    "minCpuCores": w.minCpuCores,
                                }
                                break
                    except Exception:
                        pass

                # Source and target device summaries
                def _get_dev_info(d_id: str) -> dict[str, Any]:
                    cursor.execute("SELECT data_json FROM devices WHERE id = ?;", (d_id,))
                    d_row = cursor.fetchone()
                    if d_row:
                        try:
                            return cast(dict[str, Any], json.loads(d_row[0]))
                        except Exception:
                            pass
                    return {"id": d_id}

                source_info = _get_dev_info(source_id)
                target_info = _get_dev_info(target_id)

                # Decision and reasons
                reasons = status_dict.get("reasons") or []
                decision = status_dict.get("decision")
                if not reasons:
                    cursor.execute(
                        "SELECT decision, reasons_json FROM decisions "
                        "WHERE migration_id = ? OR workload_id = ? ORDER BY ts DESC LIMIT 1;",
                        (migration_id, workload_id),
                    )
                    dec_row = cursor.fetchone()
                    if dec_row:
                        if not decision:
                            decision = dec_row[0]
                        try:
                            reasons = json.loads(dec_row[1])
                        except Exception:
                            pass

                # Authority timeline
                cursor.execute(
                    "SELECT payload_json, created_at FROM events "
                    "WHERE event_type = 'authority.change' ORDER BY created_at ASC;"
                )
                auth_timeline: list[dict[str, Any]] = []
                for p_json, c_at in cursor.fetchall():
                    try:
                        p_data = json.loads(p_json)
                        if p_data.get("workloadId") == workload_id:
                            auth_timeline.append({"ts": c_at, "authority": p_data})
                    except Exception:
                        pass

                # Event timeline in chronological order
                cursor.execute(
                    "SELECT id, event_type, payload_json, created_at FROM events "
                    "ORDER BY created_at ASC, id ASC;"
                )
                event_timeline: list[dict[str, Any]] = []
                for ev_id, ev_type, p_json, c_at in cursor.fetchall():
                    try:
                        p_data = json.loads(p_json)
                        # Filter to events mentioning this migration or workload
                        matches_migration = (
                            p_data.get("id") == migration_id
                            or p_data.get("migrationId") == migration_id
                            or p_data.get("workloadId") == workload_id
                        )
                        if matches_migration:
                            event_timeline.append(
                                {
                                    "id": ev_id,
                                    "type": ev_type,
                                    "payload": p_data,
                                    "createdAt": c_at,
                                }
                            )
                    except Exception:
                        pass

                # Metrics calculation
                started_at = status_dict.get("startedAt", 0.0)
                ended_at = status_dict.get("endedAt")
                duration = (ended_at - started_at) if ended_at else max(0.0, time.time() - started_at)
                bytes_done = status_dict.get("bytesDone", 0)
                throughput_mbps = (
                    round((bytes_done * 8) / (duration * 1_000_000), 2)
                    if duration > 0 and bytes_done > 0
                    else 0.0
                )

                metrics = {
                    "bytesTotal": status_dict.get("bytesTotal", 0),
                    "bytesDone": bytes_done,
                    "durationSec": round(duration, 3),
                    "throughputMbps": throughput_mbps,
                    "snapshotCount": len(snapshots),
                }

                error = status_dict.get("error")
                errors = [error] if error else []

                return {
                    "id": migration_id,
                    "workloadId": workload_id,
                    "manifestSummary": manifest_summary,
                    "source": source_info,
                    "target": target_info,
                    "trigger": status_dict.get("trigger", "user_command"),
                    "link": status_dict.get("link", "direct"),
                    "decision": decision,
                    "reasons": reasons,
                    "checkpoints": status_dict.get("checkpoints", []),
                    "authorityTimeline": auth_timeline,
                    "interruptionMs": status_dict.get("interruptionMs"),
                    "metrics": metrics,
                    "errors": errors,
                    "eventTimeline": event_timeline,
                    "snapshots": snapshots,
                }

        return await asyncio.to_thread(_query)

    async def export_history(self) -> dict[str, Any]:
        """Export the full history database as a JSON dictionary for backup and demo."""

        def _query() -> dict[str, Any]:
            with self._lock:
                conn = self._get_connection()
                cursor = conn.cursor()

                # Devices
                cursor.execute(
                    """
                    SELECT d.id, d.first_seen, d.last_seen, d.link_types_json, d.data_json,
                           (SELECT COUNT(*) FROM migrations m WHERE m.source_id = d.id OR m.target_id = d.id)
                    FROM devices d;
                    """
                )
                devices = []
                for row in cursor.fetchall():
                    dev_id, first_seen, last_seen, ltypes_json, data_json, mig_count = row
                    dev_dict = json.loads(data_json)
                    try:
                        ltypes = json.loads(ltypes_json) if ltypes_json else []
                    except Exception:
                        ltypes = []
                    devices.append(
                        {
                            "id": dev_id,
                            "firstSeen": first_seen,
                            "lastSeen": last_seen,
                            "device": dev_dict,
                            "linkTypes": ltypes,
                            "migrationCount": mig_count,
                        }
                    )

                # Migrations
                cursor.execute("SELECT id, data_json, snapshots_json FROM migrations;")
                migrations = []
                for row in cursor.fetchall():
                    m_dict = json.loads(row[1])
                    try:
                        m_dict["snapshots"] = json.loads(row[2]) if row[2] else []
                    except Exception:
                        m_dict["snapshots"] = []
                    migrations.append(m_dict)

                # Decisions
                cursor.execute("SELECT data_json FROM decisions ORDER BY ts ASC;")
                decisions = [json.loads(r[0]) for r in cursor.fetchall()]

                # Events
                cursor.execute("SELECT id, event_type, payload_json, created_at FROM events ORDER BY id ASC;")
                events = []
                for ev_id, ev_type, p_json, c_at in cursor.fetchall():
                    try:
                        events.append(
                            {
                                "id": ev_id,
                                "type": ev_type,
                                "payload": json.loads(p_json),
                                "createdAt": c_at,
                            }
                        )
                    except Exception:
                        pass

                return {
                    "version": CURRENT_SCHEMA_VERSION,
                    "exportedAt": time.time(),
                    "devices": devices,
                    "migrations": migrations,
                    "decisions": decisions,
                    "events": events,
                }

        return await asyncio.to_thread(_query)

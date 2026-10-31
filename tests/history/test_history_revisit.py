"""Comprehensive tests for history revisit, filtering, paging, bounded replay,

REST endpoints, export round-trip, and schema migrations (P3).
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from contract.contract import (
    Authority,
    AuthorityChangeEvent,
    CheckpointRecord,
    DecisionLog,
    DeviceInfo,
    DevicePairedEvent,
    MigrationStatus,
    MigrationStatusEvent,
    Phase,
    Reason,
    WorkloadManifest,
    WorkloadRun,
)
from teleport.core.context import Context
from teleport.core.settings import Settings
from teleport.history.router import build_history_router
from teleport.history.schema import CURRENT_SCHEMA_VERSION, initialize_database
from teleport.history.store import SqliteHistoryStore


class FakeWorkloads:
    def __init__(self, manifests: list[WorkloadManifest]) -> None:
        self._manifests = manifests

    def list(self) -> list[WorkloadManifest]:
        return self._manifests

    def runs(self) -> list[WorkloadRun]:
        return []


def make_context(tmp_path: Path, manifests: list[WorkloadManifest] | None = None) -> Context:
    settings = Settings(home=tmp_path)
    ctx = Context(settings=settings, device_id="local-dev")
    ctx.register("workloads", FakeWorkloads(manifests or []))
    return ctx


def make_device(device_id: str, name: str = "Test Host") -> DeviceInfo:
    return DeviceInfo(
        id=device_id,
        name=name,
        os="linux",
        arch="x86_64",
        cpuCores=8,
        ramMb=16384,
        gpu=None,
        diskFreeMb=50000,
        runtimes={"python": "3.11.9"},
        libs=["numpy"],
        addrs=[],
        agentVersion="0.1.0",
    )


def make_migration(
    migration_id: str,
    workload_id: str = "w-1",
    source_id: str = "dev-1",
    target_id: str = "dev-2",
    phase: Phase = "COMPLETED",
    trigger: str = "low_battery",
    link: str = "wifi",
    decision: str = "MIGRATE",
    bytes_total: int = 50_000_000,
    bytes_done: int = 50_000_000,
    interruption_ms: int = 120,
    started_at: float | None = None,
    ended_at: float | None = None,
    error: str | None = None,
) -> MigrationStatus:
    now = time.time()
    st = started_at if started_at is not None else now - 10.0
    et = ended_at if ended_at is not None else now
    return MigrationStatus(
        id=migration_id,
        workloadId=workload_id,
        sourceId=source_id,
        targetId=target_id,
        phase=phase,
        trigger=trigger,
        link=link,
        decision=decision,
        reasons=[
            Reason(code="r_ram", severity="pass", text="RAM capacity sufficient."),
            Reason(code="r_net", severity="pass", text="Link latency acceptable."),
        ],
        checkpoints=[
            CheckpointRecord(
                id="cp-1", seq=1, sizeBytes=25_000_000, sha256="abc", createdAt=st, sent=True, validated=True
            ),
            CheckpointRecord(
                id="cp-2", seq=2, sizeBytes=25_000_000, sha256="def", createdAt=st, sent=True, validated=True
            ),
        ],
        bytesTotal=bytes_total,
        bytesDone=bytes_done,
        authority=Authority(workloadId=workload_id, holder=target_id, epoch=2, state="TARGET"),
        interruptionMs=interruption_ms,
        error=error,
        startedAt=st,
        endedAt=et,
    )


class TestSchemaVersionAndMigration:
    def test_schema_version_is_v2(self, tmp_path: Path) -> None:
        db_file = tmp_path / "schema_v2.db"
        import sqlite3

        conn = sqlite3.connect(str(db_file))
        ver = initialize_database(conn)
        assert ver == CURRENT_SCHEMA_VERSION
        assert ver == 2
        conn.close()

    def test_upgrade_from_v1(self, tmp_path: Path) -> None:
        db_file = tmp_path / "upgrade_test.db"
        import sqlite3

        conn = sqlite3.connect(str(db_file))
        cursor = conn.cursor()
        # Create minimal v1 schema
        cursor.executescript(
            """
            CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at REAL NOT NULL);
            INSERT INTO schema_version VALUES (1, 1000.0);
            CREATE TABLE devices (
                id TEXT PRIMARY KEY, name TEXT, os TEXT, arch TEXT, cpu_cores INT,
                ram_mb INT, gpu TEXT, disk_free_mb INT, agent_version TEXT,
                data_json TEXT, updated_at REAL
            );
            CREATE TABLE migrations (
                id TEXT PRIMARY KEY, workload_id TEXT, source_id TEXT, target_id TEXT,
                phase TEXT, trigger TEXT, link TEXT, decision TEXT, bytes_total INT,
                bytes_done INT, started_at REAL, ended_at REAL, data_json TEXT, updated_at REAL
            );
            """
        )
        conn.commit()

        # Run initialize_database: it should add new columns and upgrade version to 2
        new_ver = initialize_database(conn)
        assert new_ver == 2

        # Verify added columns exist
        cursor.execute("PRAGMA table_info(devices);")
        dev_cols = {r[1] for r in cursor.fetchall()}
        assert "first_seen" in dev_cols
        assert "last_seen" in dev_cols
        assert "link_types_json" in dev_cols

        cursor.execute("PRAGMA table_info(migrations);")
        mig_cols = {r[1] for r in cursor.fetchall()}
        assert "snapshots_json" in mig_cols
        conn.close()


@pytest.mark.asyncio
class TestHistoryRevisitAndFiltering:
    async def test_filtering_and_paging(self, tmp_path: Path) -> None:
        ctx = make_context(tmp_path)
        store = SqliteHistoryStore(ctx)
        await store.startup()

        # Seed 5 migrations with varying properties
        base_time = 1000.0
        m1 = make_migration("m1", workload_id="w-A", source_id="d1", target_id="d2",
                            decision="MIGRATE", phase="COMPLETED", started_at=base_time + 10)
        m2 = make_migration("m2", workload_id="w-A", source_id="d2", target_id="d3",
                            decision="MIGRATE", phase="COMPLETED", started_at=base_time + 20)
        m3 = make_migration("m3", workload_id="w-B", source_id="d1", target_id="d3",
                            decision="REMOTE_ACCESS", phase="FAILED", started_at=base_time + 30)
        m4 = make_migration("m4", workload_id="w-B", source_id="d3", target_id="d1",
                            decision="STAY", phase="ROLLED_BACK", started_at=base_time + 40)
        m5 = make_migration("m5", workload_id="w-C", source_id="d4", target_id="d5",
                            decision="MIGRATE", phase="COMPLETED", started_at=base_time + 50)

        for m in (m1, m2, m3, m4, m5):
            await store._persist_migration(m)

        # 1. Filter by workload
        res_w = await store.list_migrations(workload="w-A")
        assert len(res_w) == 2
        assert {m.id for m in res_w} == {"m1", "m2"}

        # 2. Filter by device (source or target)
        res_d = await store.list_migrations(device="d1")
        assert len(res_d) == 3
        assert {m.id for m in res_d} == {"m1", "m3", "m4"}

        # 3. Filter by decision
        res_dec = await store.list_migrations(decision="REMOTE_ACCESS")
        assert len(res_dec) == 1
        assert res_dec[0].id == "m3"

        # 4. Filter by outcome (phase)
        res_out = await store.list_migrations(outcome="COMPLETED")
        assert len(res_out) == 3

        # 5. Filter by date range (since, until)
        res_date = await store.list_migrations(since=base_time + 15, until=base_time + 35)
        assert len(res_date) == 2
        assert {m.id for m in res_date} == {"m2", "m3"}

        # 6. Paging: limit and offset
        paged_1 = await store.list_migrations(limit=2, offset=0)
        assert len(paged_1) == 2
        assert paged_1[0].id == "m5"
        assert paged_1[1].id == "m4"

        paged_2 = await store.list_migrations(limit=2, offset=2)
        assert len(paged_2) == 2
        assert paged_2[0].id == "m3"
        assert paged_2[1].id == "m2"

        await store.shutdown()

    async def test_bounded_replay_snapshots(self, tmp_path: Path) -> None:
        ctx = make_context(tmp_path)
        store = SqliteHistoryStore(ctx)
        await store.startup()

        # Simulate rapidly arriving migration status events (e.g. 150 events)
        m_id = "mig-snap-test"
        # Reset last snap ts for test
        store._last_snapshot_ts.clear()

        # First status creates initial snapshot
        s1 = make_migration(m_id, phase="CONNECTING", bytes_done=0)
        await store._persist_migration(s1)

        # Immediate follow-ups within 1.0 second should NOT record extra snapshots
        s2 = make_migration(m_id, phase="TRANSFERRING", bytes_done=100)
        await store._persist_migration(s2)
        s3 = make_migration(m_id, phase="TRANSFERRING", bytes_done=200)
        await store._persist_migration(s3)

        rec = await store.get_migration(m_id)
        assert rec is not None
        assert len(rec["snapshots"]) == 1

        # Simulate 120 updates spaced out past 1.0s to test upper bound (100)
        for i in range(120):
            store._last_snapshot_ts[m_id] = 0.0  # simulate >1s elapsed
            st = make_migration(m_id, phase="TRANSFERRING", bytes_done=1000 + i)
            await store._persist_migration(st)

        rec_bound = await store.get_migration(m_id)
        assert rec_bound is not None
        # Snapshots must never exceed 100
        assert len(rec_bound["snapshots"]) <= 100
        assert len(rec_bound["snapshots"]) > 50

        await store.shutdown()

    async def test_full_record_and_timeline_order(self, tmp_path: Path) -> None:
        manifest = WorkloadManifest(
            id="workload-demo",
            name="Video Processor",
            command="python run.py",
            runtime={"name": "python", "minVersion": "3.11"},  # type: ignore
            arch=["x86_64"],
            os=["linux"],
            minRamMb=2048,
            minCpuCores=4,
            minDiskMb=5000,
            needsGpu=False,
            libs=[],
            checkpoints=[],
            remoteCapable=True,
        )
        ctx = make_context(tmp_path, manifests=[manifest])
        store = SqliteHistoryStore(ctx)
        ctx.register("history", store)
        await store.startup()

        # 1. Pair devices
        d1 = make_device("dev-alpha", "Alpha Host")
        d2 = make_device("dev-beta", "Beta Host")
        await store.ctx.bus.publish(DevicePairedEvent(device=d1))
        await store.ctx.bus.publish(DevicePairedEvent(device=d2))

        # 2. Log decision
        t0 = time.time()
        dec = DecisionLog(
            id="dec-1",
            ts=t0,
            workloadId="workload-demo",
            trigger="low_battery",
            decision="MIGRATE",
            reasons=[Reason(code="r1", severity="pass", text="All prerequisites satisfied.")],
            migrationId="mig-1",
        )
        await store.log_decision(dec)

        # 3. Publish authority change
        auth = Authority(workloadId="workload-demo", holder="dev-beta", epoch=2, state="TARGET")
        await store.ctx.bus.publish(AuthorityChangeEvent(authority=auth))

        # 4. Publish migration status
        m = make_migration(
            migration_id="mig-1",
            workload_id="workload-demo",
            source_id="dev-alpha",
            target_id="dev-beta",
            phase="COMPLETED",
            link="cable",
            interruption_ms=88,
        )
        await store.ctx.bus.publish(MigrationStatusEvent(status=m))

        # Fetch full record
        full = await store.get_migration("mig-1")
        assert full is not None
        assert full["id"] == "mig-1"
        assert full["workloadId"] == "workload-demo"
        assert full["manifestSummary"]["name"] == "Video Processor"
        assert full["source"]["id"] == "dev-alpha"
        assert full["target"]["id"] == "dev-beta"
        assert full["link"] == "cable"
        assert full["interruptionMs"] == 88
        assert full["metrics"]["bytesTotal"] == m.bytesTotal
        assert len(full["authorityTimeline"]) == 1
        assert full["authorityTimeline"][0]["authority"]["holder"] == "dev-beta"

        # Verify timeline order (created_at strictly non-decreasing)
        timeline = full["eventTimeline"]
        assert len(timeline) >= 2
        for i in range(len(timeline) - 1):
            assert timeline[i]["createdAt"] <= timeline[i + 1]["createdAt"]

        await store.shutdown()

    async def test_device_revisit_and_export_roundtrip(self, tmp_path: Path) -> None:
        ctx = make_context(tmp_path)
        store = SqliteHistoryStore(ctx)
        await store.startup()

        d_src = make_device("dev-laptop", "Dev Laptop")
        d_tgt = make_device("dev-server", "Home Server")
        await store._persist_device(d_src)
        await store._persist_device(d_tgt)

        # Two migrations involving dev-laptop
        m1 = make_migration("mig-101", source_id="dev-laptop", target_id="dev-server", link="wifi")
        m2 = make_migration("mig-102", source_id="dev-server", target_id="dev-laptop", link="cable")
        await store._persist_migration(m1)
        await store._persist_migration(m2)

        # Device summaries
        summaries = await store.list_device_summaries()
        assert len(summaries) == 2
        laptop_summary = next(s for s in summaries if s["id"] == "dev-laptop")
        assert laptop_summary["migrationCount"] == 2
        assert "wifi" in laptop_summary["linkTypes"]
        assert "cable" in laptop_summary["linkTypes"]

        # Device revisit detail
        detail = await store.get_device_detail("dev-laptop")
        assert detail is not None
        assert detail["id"] == "dev-laptop"
        assert len(detail["migrations"]) == 2

        # Export round trip
        export = await store.export_history()
        assert export["version"] == 2
        assert "exportedAt" in export
        assert len(export["devices"]) == 2
        assert len(export["migrations"]) == 2

        await store.shutdown()


@pytest.mark.asyncio
class TestHistoryRESTEndpoints:
    async def test_rest_client_reconstructs_two_migrations(self, tmp_path: Path) -> None:
        ctx = make_context(tmp_path)
        store = SqliteHistoryStore(ctx)
        ctx.register("history", store)
        await store.startup()

        # Seed two migrations
        d1 = make_device("dev-mac", "MacBook Pro")
        d2 = make_device("dev-desktop", "Ubuntu Workstation")
        await store._persist_device(d1)
        await store._persist_device(d2)

        m1 = make_migration(
            "mig-001",
            workload_id="ml-train",
            source_id="dev-mac",
            target_id="dev-desktop",
            phase="COMPLETED",
            link="cable",
            trigger="low_battery",
            decision="MIGRATE",
        )
        m2 = make_migration(
            "mig-002",
            workload_id="ml-infer",
            source_id="dev-desktop",
            target_id="dev-mac",
            phase="FAILED",
            link="wifi",
            trigger="cpu_pressure",
            decision="REMOTE_ACCESS",
            error="Connection timed out during handover",
        )
        await store._persist_migration(m1)
        await store._persist_migration(m2)

        # Build FastAPI test client
        app = FastAPI()
        app.include_router(build_history_router(ctx))
        client = TestClient(app)

        # 1. GET /api/history/devices
        res_devs = client.get("/api/history/devices")
        assert res_devs.status_code == 200
        dev_list = res_devs.json()
        assert len(dev_list) == 2
        assert {d["id"] for d in dev_list} == {"dev-mac", "dev-desktop"}

        # 2. GET /api/history/devices/{id} (device revisit)
        res_single_dev = client.get("/api/history/devices/dev-mac")
        assert res_single_dev.status_code == 200
        mac_detail = res_single_dev.json()
        assert mac_detail["id"] == "dev-mac"
        assert mac_detail["migrationCount"] == 2
        assert len(mac_detail["migrations"]) == 2

        # 3. GET /api/history/migrations (list with filters)
        res_migs = client.get("/api/history/migrations")
        assert res_migs.status_code == 200
        m_list = res_migs.json()
        assert len(m_list) == 2

        res_filtered = client.get("/api/history/migrations?decision=REMOTE_ACCESS")
        assert res_filtered.status_code == 200
        f_list = res_filtered.json()
        assert len(f_list) == 1
        assert f_list[0]["id"] == "mig-002"

        # 4. GET /api/history/migrations/{id} (full record and why)
        res_rec = client.get("/api/history/migrations/mig-001")
        assert res_rec.status_code == 200
        full_rec = res_rec.json()
        assert full_rec["id"] == "mig-001"
        assert full_rec["trigger"] == "low_battery"
        assert full_rec["decision"] == "MIGRATE"
        assert len(full_rec["reasons"]) >= 1
        assert "RAM capacity sufficient." in [r["text"] for r in full_rec["reasons"]]
        assert "metrics" in full_rec
        assert "snapshots" in full_rec

        # 5. GET /api/history/export
        res_export = client.get("/api/history/export")
        assert res_export.status_code == 200
        exp_data = res_export.json()
        assert exp_data["version"] == 2
        assert len(exp_data["devices"]) == 2
        assert len(exp_data["migrations"]) == 2

        await store.shutdown()

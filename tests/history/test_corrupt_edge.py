"""Performance benchmarks and edge case tests for History Store (P3).

Requirements:
- History queries under 100 ms with 1,000 records.
- Very long history (1,000+ records).
- Corrupted history file (recover or rebuild with a clear warning message).
"""

from __future__ import annotations

import builtins
import time
from pathlib import Path

import pytest

from contract.contract import (
    Authority,
    CheckpointRecord,
    DecisionLog,
    DeviceInfo,
    MigrationStatus,
    Phase,
    Reason,
    WorkloadManifest,
    WorkloadRun,
)
from teleport.core.context import Context
from teleport.core.settings import Settings
from teleport.history.store import SqliteHistoryStore


class DummyWorkloads:
    def __init__(self) -> None:
        pass

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    def list(self) -> builtins.list[WorkloadManifest]:
        return []

    def runs(self) -> builtins.list[WorkloadRun]:
        return []


def _make_context(tmp_path: Path) -> Context:
    settings = Settings(home=tmp_path)
    ctx = Context(settings=settings, device_id="local-dev")
    ctx.register("workloads", DummyWorkloads())
    return ctx


def _make_decision(dec_id: str, ts: float) -> DecisionLog:
    return DecisionLog(
        id=dec_id,
        ts=ts,
        workloadId="w-bench",
        trigger="low_battery",
        decision="MIGRATE",
        reasons=[Reason(code="r_bench", severity="pass", text="Performance benchmark test.")],
    )


def _make_migration(mig_id: str, ts: float, phase: Phase = "COMPLETED") -> MigrationStatus:
    return MigrationStatus(
        id=mig_id,
        workloadId="w-bench",
        sourceId="dev-source",
        targetId="dev-target",
        phase=phase,
        trigger="low_battery",
        link="wifi",
        decision="MIGRATE",
        reasons=[Reason(code="r_bench", severity="pass", text="Benchmark test reason.")],
        checkpoints=[
            CheckpointRecord(
                id="cp-1",
                seq=1,
                sizeBytes=10_000,
                sha256="abc",
                createdAt=ts,
                sent=True,
                validated=True,
            )
        ],
        bytesTotal=10_000,
        bytesDone=10_000,
        authority=Authority(workloadId="w-bench", holder="dev-target", epoch=1, state="TARGET"),
        startedAt=ts,
        endedAt=ts + 5.0,
    )


class TestHistoryPerformanceAndLongHistory:
    @pytest.mark.asyncio
    async def test_history_queries_under_100ms_with_1000_records(self, tmp_path: Path) -> None:
        """Requirement: History queries under 100 ms with 1,000 records."""
        ctx = _make_context(tmp_path)
        db_path = tmp_path / "long_history_bench.db"
        store = SqliteHistoryStore(ctx, db_path=db_path)
        await store.startup()

        # Seed 1,000 migrations and 1,000 decisions
        base_time = 1_700_000_000.0
        conn = store._get_connection()
        cursor = conn.cursor()

        # Fast batch insertion
        mig_tuples = []
        dec_tuples = []
        for i in range(1000):
            t = base_time + i
            mig = _make_migration(f"mig-{i:04d}", t)
            dec = _make_decision(f"dec-{i:04d}", t)
            mig_tuples.append((
                mig.id,
                mig.workloadId,
                mig.sourceId,
                mig.targetId,
                mig.phase,
                mig.trigger,
                mig.link,
                mig.decision,
                mig.bytesTotal,
                mig.bytesDone,
                mig.startedAt,
                mig.endedAt,
                mig.model_dump_json(),
                "[]",
                t,
            ))
            dec_tuples.append((
                dec.id,
                dec.ts,
                dec.workloadId,
                dec.trigger,
                dec.decision,
                "[]",
                None,
                dec.model_dump_json(),
            ))

        cursor.executemany(
            """INSERT INTO migrations (id, workload_id, source_id, target_id, phase, trigger, link,
               decision, bytes_total, bytes_done, started_at, ended_at, data_json, snapshots_json, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);""",
            mig_tuples,
        )
        cursor.executemany(
            """INSERT INTO decisions
               (id, ts, workload_id, trigger, decision, reasons_json, migration_id, data_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?);""",
            dec_tuples,
        )
        conn.commit()

        # 1. Benchmark list_migrations query with 1,000 records
        t0 = time.perf_counter()
        migrations = await store.list_migrations(limit=100, offset=0)
        t_query_migs = time.perf_counter() - t0

        assert len(migrations) == 100
        assert t_query_migs < 0.100, f"list_migrations took {t_query_migs * 1000:.2f} ms (budget: 100 ms)"

        # 2. Benchmark list_decisions query with 1,000 records
        t1 = time.perf_counter()
        decisions = await store.list_decisions(limit=100, offset=0)
        t_query_decs = time.perf_counter() - t1

        assert len(decisions) == 100
        assert t_query_decs < 0.100, f"list_decisions took {t_query_decs * 1000:.2f} ms (budget: 100 ms)"

        # 3. Filtered query across date range and workload
        t2 = time.perf_counter()
        filtered = await store.list_migrations(
            workload="w-bench",
            decision="MIGRATE",
            since=base_time + 100,
            until=base_time + 600,
            limit=50,
        )
        t_filter = time.perf_counter() - t2
        assert len(filtered) == 50
        assert t_filter < 0.100, f"filtered list_migrations took {t_filter * 1000:.2f} ms (budget: 100 ms)"

        await store.shutdown()


class TestHistoryCorruptionRecovery:
    @pytest.mark.asyncio
    async def test_corrupted_history_file_rebuilds_with_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Edge Case: Corrupted history file (recover or rebuild with a clear warning message).

        When SQLite database file contains garbage bytes, startup must:
        1. Catch the sqlite3.DatabaseError.
        2. Move the corrupt file to .corrupted.<timestamp>.
        3. Emit a clear warning in the logs.
        4. Reinitialize a fresh schema so normal operations succeed.
        """
        db_path = tmp_path / "corrupt_test.db"

        # Create corrupted SQLite file containing random garbage
        db_path.write_bytes(b"CORRUPTED_NON_SQLITE_GARBAGE_BYTES_0123456789\x00\xff\xfe\xfd")

        ctx = _make_context(tmp_path)
        store = SqliteHistoryStore(ctx, db_path=db_path)

        # Must not raise sqlite3.DatabaseError, but recover gracefully
        await store.startup()

        # Check that warning message was logged
        warning_logged = any(
            "corrupted" in record.message.lower() or "rebuilding" in record.message.lower()
            for record in caplog.records
        )
        assert warning_logged, "No clear warning logged during corruption recovery"

        # Check backup file exists
        corrupted_backups = list(tmp_path.glob("corrupt_test.db.corrupted.*"))
        assert len(corrupted_backups) == 1, "Backup of corrupted database was not created"

        # Verify fresh database operates normally
        dev = DeviceInfo(
            id="dev-recovered",
            name="Recovered Host",
            os="linux",
            arch="x86_64",
            cpuCores=4,
            ramMb=8192,
            gpu=None,
            diskFreeMb=20000,
            runtimes={},
            libs=[],
            addrs=[],
            agentVersion="0.1.0",
        )
        await store._persist_device(dev)
        devices = await store.list_devices()
        assert len(devices) == 1
        assert devices[0].id == "dev-recovered"

        await store.shutdown()

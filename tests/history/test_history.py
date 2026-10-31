"""Tests for SQLite history store persistence, event bus subscriptions, and upserts (P3)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from agent.teleport.core.bus import EventBus
from agent.teleport.core.context import Context
from agent.teleport.core.settings import Settings
from agent.teleport.history.schema import CURRENT_SCHEMA_VERSION, initialize_database
from agent.teleport.history.store import SqliteHistoryStore
from contract.contract import (
    Authority,
    AuthorityChangeEvent,
    DecisionLog,
    DecisionLoggedEvent,
    DeviceInfo,
    DevicePairedEvent,
    MigrationStatus,
    MigrationStatusEvent,
    Reason,
)


def make_dummy_context(tmp_path: Path) -> Context:
    settings = Settings(home=tmp_path)
    ctx = Context(settings=settings, device_id="local-dev")
    return ctx


def make_sample_device(device_id: str = "dev-test-1") -> DeviceInfo:
    return DeviceInfo(
        id=device_id,
        name="Test Host",
        os="linux",
        arch="x86_64",
        cpuCores=8,
        ramMb=16384,
        gpu=None,
        diskFreeMb=50000,
        runtimes={"python": "3.11.9"},
        libs=["numpy", "requests"],
        addrs=[],
        agentVersion="0.1.0",
    )


def make_sample_decision(decision_id: str = "dec-test-1") -> DecisionLog:
    return DecisionLog(
        id=decision_id,
        ts=time.time(),
        workloadId="w-test",
        trigger="user_command",
        decision="MIGRATE",
        reasons=[
            Reason(code="decision.migrate", severity="pass", text="Migration is feasible.")
        ],
    )


def make_sample_migration(
    migration_id: str = "mig-test-1",
    phase: str = "CONNECTING",
    bytes_done: int = 0,
) -> MigrationStatus:
    return MigrationStatus(
        id=migration_id,
        workloadId="w-test",
        sourceId="dev-source",
        targetId="dev-target",
        phase=phase,  # type: ignore
        trigger="user_command",
        link="cable",
        decision="MIGRATE",
        reasons=[Reason(code="decision.migrate", severity="pass", text="OK")],
        checkpoints=[],
        bytesTotal=10000,
        bytesDone=bytes_done,
        authority=Authority(workloadId="w-test", holder="dev-source", epoch=1, state="SOURCE"),
        startedAt=time.time(),
    )


# ---------------------------------------------------------------- Tests


class TestHistoryStoreSchema:
    def test_schema_version(self, tmp_path: Path) -> None:
        db_file = tmp_path / "schema_test.db"
        import sqlite3

        conn = sqlite3.connect(str(db_file))
        version = initialize_database(conn)
        assert version == CURRENT_SCHEMA_VERSION

        # Calling again is idempotent
        version_again = initialize_database(conn)
        assert version_again == CURRENT_SCHEMA_VERSION
        conn.close()


class TestHistoryPersistenceAndRestart:
    async def test_history_survives_restart(self, tmp_path: Path) -> None:
        db_file = tmp_path / "survive_test.db"
        ctx = make_dummy_context(tmp_path)

        # Instance 1: write data
        store1 = SqliteHistoryStore(ctx, db_path=db_file)
        await store1.startup()

        dev = make_sample_device("dev-survive-1")
        dec = make_sample_decision("dec-survive-1")
        mig = make_sample_migration("mig-survive-1", phase="COMPLETED", bytes_done=10000)

        await store1._persist_device(dev)
        await store1._persist_decision(dec)
        await store1._persist_migration(mig)
        await store1.shutdown()

        # Instance 2: reopen same database file and verify data persists
        store2 = SqliteHistoryStore(ctx, db_path=db_file)
        await store2.startup()

        devices = await store2.list_devices()
        assert len(devices) == 1
        assert devices[0].id == "dev-survive-1"

        decisions = await store2.list_decisions()
        assert len(decisions) == 1
        assert decisions[0].id == "dec-survive-1"

        migrations = await store2.list_migrations()
        assert len(migrations) == 1
        assert migrations[0].id == "mig-survive-1"
        assert migrations[0].phase == "COMPLETED"

        await store2.shutdown()


class TestHistoryEventBusSubscriptions:
    async def test_device_paired_persists(self, tmp_path: Path) -> None:
        ctx = make_dummy_context(tmp_path)
        store = SqliteHistoryStore(ctx, db_path=tmp_path / "bus_test.db")
        await store.startup()

        dev = make_sample_device("dev-event-1")
        await ctx.bus.publish(DevicePairedEvent(device=dev))

        devices = await store.list_devices()
        assert len(devices) == 1
        assert devices[0].id == "dev-event-1"

        await store.shutdown()

    async def test_decision_logged_persists(self, tmp_path: Path) -> None:
        ctx = make_dummy_context(tmp_path)
        store = SqliteHistoryStore(ctx, db_path=tmp_path / "bus_test.db")
        await store.startup()

        dec = make_sample_decision("dec-event-1")
        await ctx.bus.publish(DecisionLoggedEvent(log=dec))

        decisions = await store.list_decisions()
        assert len(decisions) == 1
        assert decisions[0].id == "dec-event-1"

        await store.shutdown()

    async def test_migration_status_upsert_by_id(self, tmp_path: Path) -> None:
        ctx = make_dummy_context(tmp_path)
        store = SqliteHistoryStore(ctx, db_path=tmp_path / "bus_test.db")
        await store.startup()

        # Step 1: Initial status (CONNECTING)
        mig_pending = make_sample_migration("mig-upsert-1", phase="CONNECTING", bytes_done=0)
        await ctx.bus.publish(MigrationStatusEvent(status=mig_pending))

        migs = await store.list_migrations()
        assert len(migs) == 1
        assert migs[0].phase == "CONNECTING"
        assert migs[0].bytesDone == 0

        # Step 2: Transition to TRANSFERRING
        mig_transfer = make_sample_migration("mig-upsert-1", phase="TRANSFERRING", bytes_done=5000)
        await ctx.bus.publish(MigrationStatusEvent(status=mig_transfer))

        migs = await store.list_migrations()
        assert len(migs) == 1  # Still 1 record (upserted!)
        assert migs[0].phase == "TRANSFERRING"
        assert migs[0].bytesDone == 5000

        # Step 3: Transition to COMPLETED
        mig_done = make_sample_migration("mig-upsert-1", phase="COMPLETED", bytes_done=10000)
        await ctx.bus.publish(MigrationStatusEvent(status=mig_done))

        migs = await store.list_migrations()
        assert len(migs) == 1
        assert migs[0].phase == "COMPLETED"
        assert migs[0].bytesDone == 10000

        await store.shutdown()

    async def test_authority_change_persists_event(self, tmp_path: Path) -> None:
        ctx = make_dummy_context(tmp_path)
        store = SqliteHistoryStore(ctx, db_path=tmp_path / "bus_test.db")
        await store.startup()

        auth = Authority(workloadId="w-auth", holder="dev-target", epoch=2, state="TARGET")
        await ctx.bus.publish(AuthorityChangeEvent(authority=auth))

        # Query events table directly
        conn = store._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT event_type, payload_json FROM events WHERE event_type = 'authority.change';")
        rows = cursor.fetchall()
        assert len(rows) == 1
        assert "w-auth" in rows[0][1]

        await store.shutdown()

    async def test_log_decision_publishes_event_and_persists(self, tmp_path: Path) -> None:
        ctx = make_dummy_context(tmp_path)
        store = SqliteHistoryStore(ctx, db_path=tmp_path / "bus_test.db")
        await store.startup()

        received_events: list[DecisionLoggedEvent] = []

        async def _capture(ev: DecisionLoggedEvent) -> None:
            received_events.append(ev)

        ctx.bus.subscribe(DecisionLoggedEvent, _capture)

        dec = make_sample_decision("dec-log-api-1")
        await store.log_decision(dec)

        # Verified stored
        decisions = await store.list_decisions()
        assert len(decisions) == 1
        assert decisions[0].id == "dec-log-api-1"

        # Verified published on event bus
        assert len(received_events) == 1
        assert received_events[0].log.id == "dec-log-api-1"

        await store.shutdown()

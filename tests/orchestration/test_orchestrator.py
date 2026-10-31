"""Comprehensive tests for Orchestrator with fake clock (P3).

Tests include:
- Each trigger fires and clears (low_battery, cpu_pressure, memory_pressure, connectivity_lost, predicted)
- Sustained windows (20s CPU, 20s Memory, 3s connectivity)
- Prediction on a falling battery and ignored while charging
- Cooldown enforcement (2-minute window)
- Recommend mode vs Auto mode
- No flapping on noisy series
- Nothing fires during an active migration
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from agent.teleport.core.bus import EventBus
from agent.teleport.core.context import Context
from agent.teleport.core.settings import Prefs, Settings
from agent.teleport.orchestration.predictor import BatteryPredictor
from agent.teleport.orchestration.service import OrchestratorService
from contract.contract import (
    Authority,
    Battery,
    CheckpointDef,
    DeviceInfo,
    LinkQuality,
    LinkUpdateEvent,
    MigrationStatus,
    Recommendation,
    RecommendationEvent,
    RuntimeReq,
    Stats,
    StatsUpdateEvent,
    Trigger,
    WorkloadManifest,
)


class FakeClock:
    def __init__(self, start: float = 1700000000.0) -> None:
        self.current = start

    def now(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


class MockWorkloads:
    def __init__(self, manifests: list[WorkloadManifest]) -> None:
        self._manifests = manifests

    def list(self) -> list[WorkloadManifest]:
        return self._manifests

    def runs(self) -> list[Any]:
        return []


class MockDevices:
    def __init__(self, local: DeviceInfo, peers: list[DeviceInfo]) -> None:
        self._local = local
        self._peers = peers
        self._stats: dict[str, Stats] = {}

    def local_info(self) -> DeviceInfo:
        return self._local

    def list_devices(self) -> list[DeviceInfo]:
        return [self._local, *self._peers]

    def latest_stats(self, device_id: str) -> Stats | None:
        return self._stats.get(device_id)

    def set_stats(self, stats: Stats) -> None:
        self._stats[stats.deviceId] = stats


class MockPeers:
    def __init__(self, peers: list[DeviceInfo], links: dict[str, LinkQuality]) -> None:
        self._peers = peers
        self._links = links

    def list_peers(self) -> list[DeviceInfo]:
        return self._peers

    def link_quality(self, device_id: str) -> LinkQuality | None:
        return self._links.get(device_id)


class MockMigration:
    def __init__(self) -> None:
        self.migrations: list[MigrationStatus] = []
        self.start_calls: list[tuple[str, str, Trigger]] = []

    def list(self) -> list[MigrationStatus]:
        return self.migrations

    async def start(self, workload_id: str, target_id: str, trigger: Trigger) -> MigrationStatus:
        self.start_calls.append((workload_id, target_id, trigger))
        status = MigrationStatus(
            id=f"mig-{len(self.start_calls)}",
            workloadId=workload_id,
            sourceId="dev-source",
            targetId=target_id,
            phase="TRANSFERRING",
            trigger=trigger,
            link="cable",
            decision="MIGRATE",
            reasons=[],
            checkpoints=[],
            bytesTotal=1000,
            bytesDone=0,
            authority=Authority(workloadId=workload_id, holder="dev-source", epoch=1, state="SOURCE"),
            startedAt=1700000000.0,
        )
        self.migrations.append(status)
        return status


def create_test_env(
    clock: FakeClock,
    mode: str = "recommend",
) -> tuple[Context, OrchestratorService, MockMigration, list[Recommendation]]:
    settings = Settings(home=Settings().home)
    ctx = Context(settings=settings, device_id="dev-source", prefs=Prefs(mode=mode))  # type: ignore

    local_dev = DeviceInfo(
        id="dev-source",
        name="Source-Host",
        os="linux",
        arch="x86_64",
        cpuCores=8,
        ramMb=16384,
        gpu=None,
        diskFreeMb=50000,
        runtimes={"python": "3.11.9"},
        libs=["requests"],
        addrs=[],
        agentVersion="0.1.0",
    )

    peer_dev = DeviceInfo(
        id="dev-peer",
        name="Peer-Host",
        os="linux",
        arch="x86_64",
        cpuCores=16,
        ramMb=32768,
        gpu=None,
        diskFreeMb=100000,
        runtimes={"python": "3.11.9"},
        libs=["requests"],
        addrs=[],
        agentVersion="0.1.0",
    )

    workload = WorkloadManifest(
        id="w-test-1",
        name="Test Service",
        command="python app.py",
        runtime=RuntimeReq(name="python", minVersion="3.11"),
        arch=["x86_64"],
        os=["linux"],
        minRamMb=1024,
        minCpuCores=2,
        minDiskMb=500,
        needsGpu=False,
        libs=["requests"],
        checkpoints=[CheckpointDef(id="c1", name="state", paths=["state.json"])],
        remoteCapable=True,
    )

    link = LinkQuality(
        peerId="dev-peer",
        link="cable",
        rttMs=2.0,
        mbps=1000.0,
        lossPct=0.0,
        ts=clock.now(),
    )

    peer_stats = Stats(
        deviceId="dev-peer",
        ts=clock.now(),
        cpuPct=10.0,
        memPct=20.0,
        memFreeMb=24000,
        diskFreeMb=90000,
        battery=None,
        online=True,
    )

    devices = MockDevices(local_dev, [peer_dev])
    devices.set_stats(peer_stats)
    peers = MockPeers([peer_dev], {"dev-peer": link})
    workloads = MockWorkloads([workload])
    migration = MockMigration()

    ctx.register("devices", devices)  # type: ignore
    ctx.register("peers", peers)  # type: ignore
    ctx.register("workloads", workloads)  # type: ignore
    ctx.register("migration", migration)  # type: ignore

    orchestrator = OrchestratorService(ctx=ctx, clock=clock.now)

    emitted_recs: list[Recommendation] = []

    async def _on_rec(event: RecommendationEvent) -> None:
        emitted_recs.append(event.rec)

    ctx.bus.subscribe(RecommendationEvent, _on_rec)

    return ctx, orchestrator, migration, emitted_recs


# ---------------------------------------------------------------- Tests


class TestLowBatteryTrigger:
    async def test_low_battery_fires_and_clears(self) -> None:
        clock = FakeClock()
        ctx, orch, _, recs = create_test_env(clock)

        # 1. Normal battery at 40%: no trigger
        st1 = Stats(
            deviceId="dev-source",
            ts=clock.now(),
            cpuPct=10.0,
            memPct=40.0,
            memFreeMb=8000,
            diskFreeMb=40000,
            battery=Battery(pct=40.0, charging=False),
            online=True,
        )
        await orch.process_stats(st1)
        assert len(recs) == 0

        # 2. Drops below 20% (18%): fires low_battery trigger
        clock.advance(5.0)
        st2 = Stats(
            deviceId="dev-source",
            ts=clock.now(),
            cpuPct=10.0,
            memPct=40.0,
            memFreeMb=8000,
            diskFreeMb=40000,
            battery=Battery(pct=18.0, charging=False),
            online=True,
        )
        await orch.process_stats(st2)
        assert len(recs) == 1
        assert recs[-1].trigger == "low_battery"

        # 3. Next reading still at 17%: does not fire again (already fired)
        clock.advance(5.0)
        st3 = Stats(
            deviceId="dev-source",
            ts=clock.now(),
            cpuPct=10.0,
            memPct=40.0,
            memFreeMb=8000,
            diskFreeMb=40000,
            battery=Battery(pct=17.0, charging=False),
            online=True,
        )
        await orch.process_stats(st3)
        assert len(recs) == 1  # No duplicate recommendation

        # 4. Charger connected: clears low_battery trigger
        clock.advance(5.0)
        st4 = Stats(
            deviceId="dev-source",
            ts=clock.now(),
            cpuPct=10.0,
            memPct=40.0,
            memFreeMb=8000,
            diskFreeMb=40000,
            battery=Battery(pct=17.0, charging=True),
            online=True,
        )
        await orch.process_stats(st4)
        assert ("dev-source", "low_battery") not in orch._active_triggers

        # 5. Cooldown expires (advance past 120s) and unplugged at 15%: fires again
        clock.advance(130.0)
        st5 = Stats(
            deviceId="dev-source",
            ts=clock.now(),
            cpuPct=10.0,
            memPct=40.0,
            memFreeMb=8000,
            diskFreeMb=40000,
            battery=Battery(pct=15.0, charging=False),
            online=True,
        )
        await orch.process_stats(st5)
        assert len(recs) == 2
        assert recs[-1].trigger == "low_battery"


class TestSustainedPressureWindows:
    async def test_cpu_pressure_sustained_20s(self) -> None:
        clock = FakeClock()
        ctx, orch, _, recs = create_test_env(clock)

        # t=0: CPU spikes to 95%
        await orch.process_stats(
            Stats(
                deviceId="dev-source",
                ts=clock.now(),
                cpuPct=95.0,
                memPct=30.0,
                memFreeMb=8000,
                diskFreeMb=40000,
                battery=None,
                online=True,
            )
        )
        assert len(recs) == 0  # Under 20s window

        # t=10: still 95% (10s sustained)
        clock.advance(10.0)
        await orch.process_stats(
            Stats(
                deviceId="dev-source",
                ts=clock.now(),
                cpuPct=95.0,
                memPct=30.0,
                memFreeMb=8000,
                diskFreeMb=40000,
                battery=None,
                online=True,
            )
        )
        assert len(recs) == 0

        # t=21: 21s sustained >= 90% -> fires cpu_pressure!
        clock.advance(11.0)
        await orch.process_stats(
            Stats(
                deviceId="dev-source",
                ts=clock.now(),
                cpuPct=95.0,
                memPct=30.0,
                memFreeMb=8000,
                diskFreeMb=40000,
                battery=None,
                online=True,
            )
        )
        assert len(recs) == 1
        assert recs[-1].trigger == "cpu_pressure"

        # CPU drops below 90%: clears trigger
        clock.advance(5.0)
        await orch.process_stats(
            Stats(
                deviceId="dev-source",
                ts=clock.now(),
                cpuPct=50.0,
                memPct=30.0,
                memFreeMb=8000,
                diskFreeMb=40000,
                battery=None,
                online=True,
            )
        )
        assert ("dev-source", "cpu_pressure") not in orch._active_triggers

    async def test_memory_pressure_sustained_20s(self) -> None:
        clock = FakeClock()
        ctx, orch, _, recs = create_test_env(clock)

        # t=0: Memory spikes to 92%
        await orch.process_stats(
            Stats(
                deviceId="dev-source",
                ts=clock.now(),
                cpuPct=20.0,
                memPct=92.0,
                memFreeMb=500,
                diskFreeMb=40000,
                battery=None,
                online=True,
            )
        )
        assert len(recs) == 0

        # t=21: 21s sustained -> fires memory_pressure!
        clock.advance(21.0)
        await orch.process_stats(
            Stats(
                deviceId="dev-source",
                ts=clock.now(),
                cpuPct=20.0,
                memPct=92.0,
                memFreeMb=500,
                diskFreeMb=40000,
                battery=None,
                online=True,
            )
        )
        assert len(recs) == 1
        assert recs[-1].trigger == "memory_pressure"

    async def test_connectivity_lost_sustained_3s(self) -> None:
        clock = FakeClock()
        ctx, orch, _, recs = create_test_env(clock)

        # Link drops to 100% loss at t=0
        await orch.process_link(
            LinkQuality(peerId="dev-peer", link="wifi", rttMs=500.0, mbps=0.0, lossPct=100.0, ts=clock.now())
        )
        assert len(recs) == 0  # Under 3s

        # At t=2s: still down
        clock.advance(2.0)
        await orch.process_link(
            LinkQuality(peerId="dev-peer", link="wifi", rttMs=500.0, mbps=0.0, lossPct=100.0, ts=clock.now())
        )
        assert len(recs) == 0

        # At t=4s: sustained 4s >= 3s -> fires connectivity_lost!
        clock.advance(2.0)
        await orch.process_link(
            LinkQuality(peerId="dev-peer", link="wifi", rttMs=500.0, mbps=0.0, lossPct=100.0, ts=clock.now())
        )
        assert len(recs) == 1
        assert recs[-1].trigger == "connectivity_lost"


class TestBatteryPrediction:
    async def test_falling_battery_triggers_predicted_before_low_battery(self) -> None:
        clock = FakeClock()
        ctx, orch, _, recs = create_test_env(clock)

        # Battery starts at 50% and drops 1% every 10 seconds (-0.1%/s)
        # t=0: 50%
        # t=30: 47%
        # t=60: 44%
        await orch.process_stats(
            Stats(deviceId="dev-source", ts=clock.now(), cpuPct=10.0, memPct=30.0, memFreeMb=8000, diskFreeMb=40000, battery=Battery(pct=50.0, charging=False), online=True)
        )
        clock.advance(30.0)
        await orch.process_stats(
            Stats(deviceId="dev-source", ts=clock.now(), cpuPct=10.0, memPct=30.0, memFreeMb=8000, diskFreeMb=40000, battery=Battery(pct=47.0, charging=False), online=True)
        )
        clock.advance(30.0)
        await orch.process_stats(
            Stats(deviceId="dev-source", ts=clock.now(), cpuPct=10.0, memPct=30.0, memFreeMb=8000, diskFreeMb=40000, battery=Battery(pct=44.0, charging=False), online=True)
        )

        # At t=60, rate is -0.1%/s, TTE = 440s (~7.3 min) < 15 min -> predicted fires!
        assert len(recs) == 1
        assert recs[0].trigger == "predicted"

        # Advance past 120s cooldown and drop below 20%
        clock.advance(250.0)  # t=310s, battery at 19%
        await orch.process_stats(
            Stats(deviceId="dev-source", ts=clock.now(), cpuPct=10.0, memPct=30.0, memFreeMb=8000, diskFreeMb=40000, battery=Battery(pct=19.0, charging=False), online=True)
        )

        assert len(recs) == 2
        assert recs[1].trigger == "low_battery"

    async def test_prediction_ignored_while_charging(self) -> None:
        clock = FakeClock()
        ctx, orch, _, recs = create_test_env(clock)

        # Same series but charging=True
        for pct in (50.0, 47.0, 44.0, 40.0):
            await orch.process_stats(
                Stats(deviceId="dev-source", ts=clock.now(), cpuPct=10.0, memPct=30.0, memFreeMb=8000, diskFreeMb=40000, battery=Battery(pct=pct, charging=True), online=True)
            )
            clock.advance(30.0)

        assert len(recs) == 0

    async def test_no_flapping_on_noisy_series(self) -> None:
        clock = FakeClock()
        ctx, orch, _, recs = create_test_env(clock)

        # Highly erratic readings: 50 -> 20 -> 55 -> 15 -> 50
        for pct in (50.0, 20.0, 55.0, 15.0, 50.0):
            await orch.process_stats(
                Stats(deviceId="dev-source", ts=clock.now(), cpuPct=10.0, memPct=30.0, memFreeMb=8000, diskFreeMb=40000, battery=Battery(pct=pct, charging=False), online=True)
            )
            clock.advance(10.0)

        # Low battery will fire on 20/15, but erratic data will NOT cause predicted flapping
        assert all(r.trigger != "predicted" for r in recs)


class TestCooldownAndActiveMigration:
    async def test_cooldown_suppresses_subsequent_trigger(self) -> None:
        clock = FakeClock()
        ctx, orch, _, recs = create_test_env(clock)

        # t=0: low battery fires
        await orch.process_stats(
            Stats(deviceId="dev-source", ts=clock.now(), cpuPct=10.0, memPct=30.0, memFreeMb=8000, diskFreeMb=40000, battery=Battery(pct=18.0, charging=False), online=True)
        )
        assert len(recs) == 1

        # t=30: CPU pressure sustained (force trigger), but in 120s cooldown
        orch._active_triggers.clear()  # reset active trigger tracking
        orch._cpu_pressure_start["dev-source"] = clock.now() - 30.0  # simulate sustained CPU
        clock.advance(30.0)  # t=30 (within 120s cooldown)

        await orch.process_stats(
            Stats(deviceId="dev-source", ts=clock.now(), cpuPct=95.0, memPct=30.0, memFreeMb=8000, diskFreeMb=40000, battery=Battery(pct=18.0, charging=False), online=True)
        )
        assert len(recs) == 1  # Still 1 because cooldown suppressed it

        # t=130: cooldown has now expired
        clock.advance(100.0)
        orch._active_triggers.clear()
        orch._cpu_pressure_start["dev-source"] = clock.now() - 30.0

        await orch.process_stats(
            Stats(deviceId="dev-source", ts=clock.now(), cpuPct=95.0, memPct=30.0, memFreeMb=8000, diskFreeMb=40000, battery=Battery(pct=18.0, charging=False), online=True)
        )
        assert len(recs) == 2  # Cooldown expired, fires!

    async def test_nothing_fires_during_active_migration(self) -> None:
        clock = FakeClock()
        ctx, orch, mig_svc, recs = create_test_env(clock)

        # Active migration running in TRANSFERRING phase for w-test-1
        mig_svc.migrations.append(
            MigrationStatus(
                id="active-mig",
                workloadId="w-test-1",
                sourceId="dev-source",
                targetId="dev-peer",
                phase="TRANSFERRING",
                trigger="low_battery",
                link="cable",
                decision="MIGRATE",
                reasons=[],
                checkpoints=[],
                bytesTotal=1000,
                bytesDone=500,
                authority=Authority(workloadId="w-test-1", holder="dev-source", epoch=1, state="SOURCE"),
                startedAt=clock.now(),
            )
        )

        # Battery drops to 10%
        await orch.process_stats(
            Stats(deviceId="dev-source", ts=clock.now(), cpuPct=10.0, memPct=30.0, memFreeMb=8000, diskFreeMb=40000, battery=Battery(pct=10.0, charging=False), online=True)
        )

        # Suppressed because migration is actively running
        assert len(recs) == 0


class TestRecommendVsAutoMode:
    async def test_recommend_mode_waits_for_user(self) -> None:
        clock = FakeClock()
        ctx, orch, mig_svc, recs = create_test_env(clock, mode="recommend")

        await orch.process_stats(
            Stats(deviceId="dev-source", ts=clock.now(), cpuPct=10.0, memPct=30.0, memFreeMb=8000, diskFreeMb=40000, battery=Battery(pct=18.0, charging=False), online=True)
        )

        assert len(recs) == 1
        assert recs[0].auto is False
        assert len(mig_svc.start_calls) == 0  # Does NOT auto-start

    async def test_auto_mode_calls_migration_start(self) -> None:
        clock = FakeClock()
        ctx, orch, mig_svc, recs = create_test_env(clock, mode="auto")

        await orch.process_stats(
            Stats(deviceId="dev-source", ts=clock.now(), cpuPct=10.0, memPct=30.0, memFreeMb=8000, diskFreeMb=40000, battery=Battery(pct=18.0, charging=False), online=True)
        )

        assert len(recs) == 1
        assert recs[0].auto is True
        assert len(mig_svc.start_calls) == 1  # Auto-started migration!
        workload_id, target_id, trigger = mig_svc.start_calls[0]
        assert workload_id == "w-test-1"
        assert target_id == "dev-peer"
        assert trigger == "low_battery"


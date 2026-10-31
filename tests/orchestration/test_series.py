"""Test suite covering 10 recorded stats series for orchestrator trigger evaluation (P3).

Series:
1. steady: normal battery, CPU, RAM -> no triggers
2. slow_drain: linear battery discharge projecting TTE < 900s -> 'predicted' trigger
3. sudden_drop: battery drops below 20% -> 'low_battery' trigger
4. cpu_spike: CPU > 90% sustained for 25s (>20s window) -> 'cpu_pressure' trigger
5. memory_climb: RAM > 90% sustained for 25s (>20s window) -> 'memory_pressure' trigger
6. wifi_loss: link drops for 4s (>3s window) -> 'connectivity_lost' trigger
7. charger_plugged_halfway: charger connected suppresses battery triggers
8. noisy_battery: erratic readings rejected by OLS noise filter
9. cpu_transient: CPU spike < 20s window -> no trigger fired
10. recommendation_generation: trigger generates candidate target recommendation
"""

from __future__ import annotations

import builtins
from typing import Any

import pytest

from contract.contract import (
    Battery,
    DeviceInfo,
    LinkQuality,
    RecommendationEvent,
    Stats,
    WorkloadManifest,
)
from teleport.core.context import Context
from teleport.core.settings import Prefs, Settings
from teleport.orchestration.predictor import BatteryPredictor
from teleport.orchestration.service import OrchestratorService


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.time = start

    def __call__(self) -> float:
        return self.time

    def advance(self, seconds: float) -> None:
        self.time += seconds


class DummyDevices:
    def __init__(self, devices: list[DeviceInfo]) -> None:
        self._devs = {d.id: d for d in devices}

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    def list_devices(self) -> list[DeviceInfo]:
        return list(self._devs.values())

    def local_info(self) -> DeviceInfo:
        return list(self._devs.values())[0]

    def latest_stats(self, device_id: str) -> Any:
        return None


class DummyPeers:
    def __init__(self, peers: list[DeviceInfo], link: LinkQuality | None = None) -> None:
        self._peers = {p.id: p for p in peers}
        self._link = link

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    def list_peers(self) -> list[DeviceInfo]:
        return list(self._peers.values())

    def link_quality(self, peer_id: str) -> LinkQuality | None:
        return self._link


class DummyWorkloads:
    def __init__(self, manifests: list[WorkloadManifest]) -> None:
        self._manifests = manifests

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    def list(self) -> builtins.list[WorkloadManifest]:
        return self._manifests

    def runs(self) -> builtins.list[Any]:
        return []


def make_dev(dev_id: str, name: str) -> DeviceInfo:
    return DeviceInfo(
        id=dev_id,
        name=name,
        os="linux",
        arch="x86_64",
        cpuCores=8,
        ramMb=16384,
        gpu=None,
        diskFreeMb=50000,
        runtimes={"python": "3.11.9"},
        libs=[],
        addrs=[],
        agentVersion="0.1.0",
    )


def make_stats(
    device_id: str,
    ts: float,
    cpu: float = 20.0,
    mem: float = 30.0,
    battery_pct: float | None = 80.0,
    charging: bool = False,
    online: bool = True,
) -> Stats:
    bat = Battery(pct=battery_pct, charging=charging) if battery_pct is not None else None
    return Stats(
        deviceId=device_id,
        ts=ts,
        cpuPct=cpu,
        memPct=mem,
        memFreeMb=12000,
        diskFreeMb=45000,
        battery=bat,
        online=online,
        simulated=False,
    )


@pytest.fixture
def test_setup(tmp_path: Any) -> tuple[Context, OrchestratorService, FakeClock, list[Any]]:
    clock = FakeClock()
    settings = Settings(home=tmp_path)
    ctx = Context(settings=settings, device_id="dev-source")
    ctx.prefs = Prefs(mode="recommend", batteryLowPct=20.0, cpuHighPct=90.0, memHighPct=90.0)

    # Register dependencies
    d_source = make_dev("dev-source", "Source Laptop")
    d_target = make_dev("dev-target", "Target Workstation")
    ctx.register("devices", DummyDevices([d_source]))
    ctx.register("peers", DummyPeers([d_target], LinkQuality(
        peerId="dev-target", link="cable", rttMs=1.5, mbps=1000.0, lossPct=0.0, ts=clock()
    )))

    manifest = WorkloadManifest(
        id="workload-1",
        name="Analysis App",
        command="python run.py",
        runtime={"name": "python", "minVersion": "3.11"},  # type: ignore
        arch=["x86_64"],
        os=["linux"],
        minRamMb=2048,
        minCpuCores=4,
        minDiskMb=2000,
        needsGpu=False,
        libs=[],
        checkpoints=[],
        remoteCapable=True,
    )
    ctx.register("workloads", DummyWorkloads([manifest]))

    fired_events: list[Any] = []

    async def _on_rec(ev: RecommendationEvent) -> None:
        fired_events.append(ev)

    ctx.bus.subscribe(RecommendationEvent, _on_rec)

    predictor = BatteryPredictor(window_sec=600.0, ctx=ctx)
    orch = OrchestratorService(ctx=ctx, clock=clock, battery_predictor=predictor)

    return ctx, orch, clock, fired_events


@pytest.mark.asyncio
class TestOrchestratorTenSeries:
    # 1. Steady Series
    async def test_series_1_steady(self, test_setup: Any) -> None:
        ctx, orch, clock, events = test_setup
        for _ in range(10):
            st = make_stats("dev-source", ts=clock(), cpu=25.0, mem=35.0, battery_pct=75.0)
            await orch.process_stats(st)
            clock.advance(5.0)
        assert len(events) == 0
        assert len(orch.recommendations()) == 0

    # 2. Slow Drain Series (Triggers 'predicted' when projected TTE < 900s)
    async def test_series_2_slow_drain(self, test_setup: Any) -> None:
        ctx, orch, clock, events = test_setup
        # Drain 0.05% per second over 30 seconds -> current 38.5% with slope -0.05% -> TTE = 770s < 900s
        for i in range(7):
            pct = 40.0 - (i * 0.25)
            st = make_stats("dev-source", ts=clock(), cpu=20.0, battery_pct=pct, charging=False)
            await orch.process_stats(st)
            clock.advance(5.0)

        assert any(ev.rec.trigger == "predicted" for ev in events)

    # 3. Sudden Drop Series (Triggers 'low_battery' below 20%)
    async def test_series_3_sudden_drop(self, test_setup: Any) -> None:
        ctx, orch, clock, events = test_setup
        st1 = make_stats("dev-source", ts=clock(), battery_pct=35.0)
        await orch.process_stats(st1)
        clock.advance(1.0)
        # Sudden drop below 20%
        st2 = make_stats("dev-source", ts=clock(), battery_pct=14.0)
        await orch.process_stats(st2)

        assert any(ev.rec.trigger == "low_battery" for ev in events)

    # 4. CPU Spike Series (Sustained > 90% for > 20s)
    async def test_series_4_cpu_spike(self, test_setup: Any) -> None:
        ctx, orch, clock, events = test_setup
        # Initial spike
        await orch.process_stats(make_stats("dev-source", ts=clock(), cpu=95.0))
        clock.advance(10.0)
        await orch.process_stats(make_stats("dev-source", ts=clock(), cpu=95.0))
        assert len(events) == 0  # not reached 20s yet

        # Advance past 20s
        clock.advance(11.0)
        await orch.process_stats(make_stats("dev-source", ts=clock(), cpu=95.0))
        assert any(ev.rec.trigger == "cpu_pressure" for ev in events)

    # 5. Memory Climb Series (Sustained > 90% for > 20s)
    async def test_series_5_memory_climb(self, test_setup: Any) -> None:
        ctx, orch, clock, events = test_setup
        await orch.process_stats(make_stats("dev-source", ts=clock(), mem=94.0))
        clock.advance(12.0)
        await orch.process_stats(make_stats("dev-source", ts=clock(), mem=95.0))
        assert len(events) == 0

        clock.advance(9.0)  # Total 21s
        await orch.process_stats(make_stats("dev-source", ts=clock(), mem=96.0))
        assert any(ev.rec.trigger == "memory_pressure" for ev in events)

    # 6. Wi-Fi Loss Series (Down for > 3s)
    async def test_series_6_wifi_loss(self, test_setup: Any) -> None:
        ctx, orch, clock, events = test_setup

        def make_down_link() -> LinkQuality:
            return LinkQuality(
                peerId="dev-target", link="wifi", rttMs=999.0, mbps=0.0, lossPct=100.0, ts=clock()
            )

        await orch.process_link(make_down_link())
        clock.advance(2.0)
        await orch.process_link(make_down_link())
        assert len(events) == 0  # only 2s

        clock.advance(1.5)  # 3.5s total > 3s window
        await orch.process_link(make_down_link())
        assert any(ev.rec.trigger == "connectivity_lost" for ev in events)

    # 7. Charger Plugged in Halfway Series (Suppresses battery triggers)
    async def test_series_7_charger_plugged_halfway(self, test_setup: Any) -> None:
        ctx, orch, clock, events = test_setup
        # Drain initially
        await orch.process_stats(make_stats("dev-source", ts=clock(), battery_pct=25.0, charging=False))
        clock.advance(5.0)
        await orch.process_stats(make_stats("dev-source", ts=clock(), battery_pct=24.0, charging=False))
        clock.advance(5.0)
        # Charger plugged in at 18% (which would be low_battery if not charging)
        await orch.process_stats(make_stats("dev-source", ts=clock(), battery_pct=18.0, charging=True))

        # Battery triggers must not fire
        assert not any(ev.rec.trigger in ("low_battery", "predicted") for ev in events)

    # 8. Noisy Battery Series (Erratic readings rejected by noise filter)
    async def test_series_8_noisy_battery(self, test_setup: Any) -> None:
        ctx, orch, clock, events = test_setup
        # Highly erratic percentage samples: 45, 65, 30, 70, 40, 60
        percentages = [45.0, 65.0, 30.0, 70.0, 40.0, 60.0]
        for pct in percentages:
            await orch.process_stats(make_stats("dev-source", ts=clock(), battery_pct=pct))
            clock.advance(5.0)

        # Noisy data should not trigger predicted
        assert not any(ev.rec.trigger == "predicted" for ev in events)

    # 9. CPU Transient Spike (Spike < 20s window drops back)
    async def test_series_9_cpu_transient(self, test_setup: Any) -> None:
        ctx, orch, clock, events = test_setup
        await orch.process_stats(make_stats("dev-source", ts=clock(), cpu=98.0))
        clock.advance(8.0)
        # Drop back to normal before 20s window expires
        await orch.process_stats(make_stats("dev-source", ts=clock(), cpu=30.0))
        clock.advance(15.0)
        await orch.process_stats(make_stats("dev-source", ts=clock(), cpu=30.0))

        assert not any(ev.rec.trigger == "cpu_pressure" for ev in events)

    # 10. Recommendation Candidate Selection
    async def test_series_10_recommendation_target(self, test_setup: Any) -> None:
        ctx, orch, clock, events = test_setup
        st = make_stats("dev-source", ts=clock(), battery_pct=15.0, charging=False)
        await orch.process_stats(st)

        assert len(events) == 1
        rec = events[0].rec
        assert rec.trigger == "low_battery"
        assert rec.workloadId == "workload-1"
        assert rec.targetId == "dev-target"
        assert rec.decision == "MIGRATE"

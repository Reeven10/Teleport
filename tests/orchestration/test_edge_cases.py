"""Performance benchmarks and edge case tests for Orchestrator (P3).

Requirements:
- Orchestrator under 1 percent CPU at one stats update per second per device.
- Edge case: two workloads triggered at once.
- Edge case: clock changes (time jumping backwards or forwards).
"""

from __future__ import annotations

import builtins
import time
from pathlib import Path
from typing import Any

import pytest

from contract.contract import (
    Battery,
    DeviceInfo,
    LinkQuality,
    Recommendation,
    RecommendationEvent,
    RuntimeReq,
    Stats,
    WorkloadManifest,
)
from teleport.core.context import Context
from teleport.core.settings import Prefs, Settings
from teleport.orchestration.predictor import BatteryPredictor
from teleport.orchestration.service import OrchestratorService


class MockClock:
    def __init__(self, start: float = 1_000_000.0) -> None:
        self.current = start

    def __call__(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds

    def jump(self, target_time: float) -> None:
        self.current = target_time


class MockDevicesService:
    def __init__(self, local: DeviceInfo, peers: list[DeviceInfo]) -> None:
        self._local = local
        self._peers = {p.id: p for p in peers}

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    def local_info(self) -> DeviceInfo:
        return self._local

    def list_devices(self) -> builtins.list[DeviceInfo]:
        return [self._local, *self._peers.values()]

    def latest_stats(self, device_id: str) -> Any:
        return None


class MockPeersService:
    def __init__(self, peers: list[DeviceInfo], link: LinkQuality) -> None:
        self._peers = {p.id: p for p in peers}
        self._link = link

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    def list_peers(self) -> builtins.list[DeviceInfo]:
        return list(self._peers.values())

    def link_quality(self, peer_id: str) -> LinkQuality | None:
        return self._link


class MockWorkloadsService:
    def __init__(self, workloads: list[WorkloadManifest]) -> None:
        self._workloads = workloads

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    def list(self) -> builtins.list[WorkloadManifest]:
        return self._workloads

    def runs(self) -> builtins.list[Any]:
        return []


def _make_device(device_id: str, name: str) -> DeviceInfo:
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
        libs=[],
        addrs=[],
        agentVersion="0.1.0",
    )


def _make_workload(workload_id: str, name: str) -> WorkloadManifest:
    return WorkloadManifest(
        id=workload_id,
        name=name,
        command="python app.py",
        runtime=RuntimeReq(name="python", minVersion="3.11"),
        arch=["x86_64"],
        os=["linux"],
        minRamMb=1024,
        minCpuCores=2,
        minDiskMb=1000,
        needsGpu=False,
        libs=[],
        checkpoints=[],
        remoteCapable=True,
    )


def _make_stats(
    device_id: str,
    ts: float,
    cpu: float = 20.0,
    mem: float = 30.0,
    mem_free_mb: int = 12000,
    battery_pct: float = 80.0,
    charging: bool = False,
) -> Stats:
    return Stats(
        deviceId=device_id,
        ts=ts,
        cpuPct=cpu,
        memPct=mem,
        memFreeMb=mem_free_mb,
        diskFreeMb=40000,
        battery=Battery(pct=battery_pct, charging=charging),
        online=True,
        simulated=False,
    )


class TestOrchestratorPerformance:
    @pytest.mark.asyncio
    async def test_orchestrator_under_1_percent_cpu_at_1_update_per_sec(
        self, tmp_path: Path
    ) -> None:
        """Requirement: Orchestrator under 1% CPU at one stats update per second per device.

        1% of 1 second is 10 ms (0.010 s) of CPU processing time per update.
        We process 100 sequential stats updates and verify average processing time < 10 ms.
        """
        clock = MockClock()
        settings = Settings(home=tmp_path)
        ctx = Context(settings=settings, device_id="local-dev")
        ctx.prefs = Prefs(mode="recommend", batteryLowPct=20.0, cpuHighPct=90.0, memHighPct=90.0)

        local_dev = _make_device("local-dev", "Local Host")
        peer_dev = _make_device("target-dev", "Target Host")
        link = LinkQuality(
            peerId="target-dev",
            link="wifi",
            ts=clock(),
            mbps=100.0,
            rttMs=15.0,
            lossPct=0.01,
            simulated=False,
        )

        ctx.register("devices", MockDevicesService(local_dev, [peer_dev]))
        ctx.register("peers", MockPeersService([peer_dev], link))
        ctx.register("workloads", MockWorkloadsService([_make_workload("w-1", "App 1")]))

        orch = OrchestratorService(
            ctx=ctx, clock=clock, battery_predictor=BatteryPredictor(ctx=ctx)
        )

        # Warm up
        await orch.process_stats(_make_stats("local-dev", ts=clock()))

        # Benchmark 100 updates
        num_updates = 100
        start_cpu = time.process_time()

        for _ in range(num_updates):
            clock.advance(1.0)
            st = _make_stats("local-dev", ts=clock(), cpu=25.0, mem=30.0, battery_pct=75.0)
            await orch.process_stats(st)

        cpu_time = time.process_time() - start_cpu
        avg_cpu_ms = (cpu_time / num_updates) * 1000.0

        # Budget is 10 ms (1% of 1 second); in practice Python processing should be < 1 ms
        assert avg_cpu_ms < 10.0, f"Average CPU time was {avg_cpu_ms:.3f} ms per update (budget: 10 ms)"
        assert cpu_time < 0.500, f"Total CPU time for 100 updates was {cpu_time:.3f} s"


class TestOrchestratorEdgeCases:
    @pytest.mark.asyncio
    async def test_two_workloads_triggered_at_once(self, tmp_path: Path) -> None:
        """Edge Case: Two workloads running locally when a trigger fires.

        Both workloads must be evaluated independently, emit recommendations,
        and track separate cooldown timers.
        """
        clock = MockClock()
        settings = Settings(home=tmp_path)
        ctx = Context(settings=settings, device_id="local-dev")
        ctx.prefs = Prefs(mode="recommend", batteryLowPct=20.0, cpuHighPct=90.0, memHighPct=90.0)

        local_dev = _make_device("local-dev", "Local Host")
        peer_dev = _make_device("target-dev", "Target Host")
        link = LinkQuality(
            peerId="target-dev",
            link="wifi",
            ts=clock(),
            mbps=100.0,
            rttMs=15.0,
            lossPct=0.01,
            simulated=False,
        )

        w1 = _make_workload("w-1", "Database")
        w2 = _make_workload("w-2", "Web Server")

        ctx.register("devices", MockDevicesService(local_dev, [peer_dev]))
        ctx.register("peers", MockPeersService([peer_dev], link))
        ctx.register("workloads", MockWorkloadsService([w1, w2]))

        received_recs: list[Recommendation] = []

        async def _capture_rec(ev: RecommendationEvent) -> None:
            received_recs.append(ev.rec)

        ctx.bus.subscribe(RecommendationEvent, _capture_rec)

        orch = OrchestratorService(
            ctx=ctx, clock=clock, battery_predictor=BatteryPredictor(ctx=ctx)
        )

        # Trigger low battery
        clock.advance(1.0)
        st = _make_stats("local-dev", ts=clock(), battery_pct=15.0, charging=False)
        await orch.process_stats(st)

        # Both workloads should receive recommendations
        assert len(received_recs) == 2
        workload_ids = {r.workloadId for r in received_recs}
        assert workload_ids == {"w-1", "w-2"}

        # Immediate follow-up update within cooldown window (120s) must NOT fire duplicates
        received_recs.clear()
        clock.advance(10.0)
        st2 = _make_stats("local-dev", ts=clock(), battery_pct=14.0, charging=False)
        await orch.process_stats(st2)
        assert len(received_recs) == 0, "Recommendations fired while in cooldown window"

    @pytest.mark.asyncio
    async def test_clock_changes_jumping_backwards_and_forwards(self, tmp_path: Path) -> None:
        """Edge Case: System clock jumps backwards (NTP skew/daylight saving) or forwards.

        Hysteresis and predictor state should handle clock discontinuities gracefully without crashing.
        """
        clock = MockClock(start=10_000.0)
        settings = Settings(home=tmp_path)
        ctx = Context(settings=settings, device_id="local-dev")
        ctx.prefs = Prefs(mode="recommend", batteryLowPct=20.0, cpuHighPct=90.0, memHighPct=90.0)

        local_dev = _make_device("local-dev", "Local Host")
        peer_dev = _make_device("target-dev", "Target Host")
        link = LinkQuality(
            peerId="target-dev",
            link="wifi",
            ts=clock(),
            mbps=100.0,
            rttMs=15.0,
            lossPct=0.01,
            simulated=False,
        )

        ctx.register("devices", MockDevicesService(local_dev, [peer_dev]))
        ctx.register("peers", MockPeersService([peer_dev], link))
        ctx.register("workloads", MockWorkloadsService([_make_workload("w-1", "App")]))

        orch = OrchestratorService(
            ctx=ctx, clock=clock, battery_predictor=BatteryPredictor(ctx=ctx)
        )

        # Initial steady state at t = 10,000
        await orch.process_stats(_make_stats("local-dev", ts=clock(), cpu=20.0))

        # Clock jumps backwards by 3600 seconds (1 hour)
        clock.jump(6_400.0)
        await orch.process_stats(_make_stats("local-dev", ts=clock(), cpu=25.0))

        # Clock jumps forward by 24 hours
        clock.jump(92_800.0)
        await orch.process_stats(_make_stats("local-dev", ts=clock(), cpu=30.0))

        # Sustained CPU pressure trigger at new time
        await orch.process_stats(_make_stats("local-dev", ts=clock(), cpu=95.0))
        clock.advance(25.0)  # > 20s sustained window
        await orch.process_stats(_make_stats("local-dev", ts=clock(), cpu=95.0))

        # Should operate normally and detect the sustained condition
        assert ("local-dev", "cpu_pressure") in orch._active_triggers
        assert orch._cpu_pressure_start.get("local-dev") is not None

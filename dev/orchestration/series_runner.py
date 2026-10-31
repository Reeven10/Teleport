"""Orchestrator telemetry series runner and report generator (P3).

Executes 10 recorded stats series (steady, slow drain, sudden drop, CPU spike,
memory climb, wifi loss, charger plugged in halfway, noisy battery, transient CPU spike,
and candidate recommendation), checks triggers, and generates dev/orchestration/report.md.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

from contract.contract import (
    Battery,
    DeviceInfo,
    LinkQuality,
    Recommendation,
    RecommendationEvent,
    Stats,
    WorkloadManifest,
)
from teleport.core.context import Context
from teleport.core.settings import Prefs, Settings
from teleport.orchestration.predictor import BatteryPredictor
from teleport.orchestration.service import OrchestratorService

REPORT_PATH = Path(__file__).resolve().parent / "report.md"


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

    def list_peers(self) -> list[DeviceInfo]:
        return list(self._peers.values())

    def link_quality(self, peer_id: str) -> LinkQuality | None:
        return self._link


class DummyWorkloads:
    def __init__(self, manifests: list[WorkloadManifest]) -> None:
        self._manifests = manifests

    def list(self) -> list[WorkloadManifest]:
        return self._manifests

    def runs(self) -> list[Any]:
        return []


def _build_context(clock: FakeClock, tmp_path: Path) -> tuple[Context, list[Recommendation]]:
    settings = Settings(home=tmp_path)
    ctx = Context(settings=settings, device_id="dev-source")
    ctx.prefs = Prefs(mode="recommend", batteryLowPct=20.0, cpuHighPct=90.0, memHighPct=90.0)

    d_source = DeviceInfo(
        id="dev-source",
        name="Source Laptop",
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
    d_target = DeviceInfo(
        id="dev-target",
        name="Target Server",
        os="linux",
        arch="x86_64",
        cpuCores=16,
        ramMb=32768,
        gpu=None,
        diskFreeMb=80000,
        runtimes={"python": "3.11.9"},
        libs=[],
        addrs=[],
        agentVersion="0.1.0",
    )

    ctx.register("devices", DummyDevices([d_source]))
    ctx.register("peers", DummyPeers([d_target], LinkQuality(
        peerId="dev-target", link="cable", rttMs=1.5, mbps=1000.0, lossPct=0.0, ts=clock()
    )))

    manifest = WorkloadManifest(
        id="w-live",
        name="Live Service",
        command="python app.py",
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

    fired_recs: list[Recommendation] = []

    async def _on_rec(ev: RecommendationEvent) -> None:
        fired_recs.append(ev.rec)

    ctx.bus.subscribe(RecommendationEvent, _on_rec)
    return ctx, fired_recs


def _make_stats(
    device_id: str,
    ts: float,
    cpu: float = 20.0,
    mem: float = 30.0,
    battery_pct: float | None = 80.0,
    charging: bool = False,
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
        online=True,
        simulated=False,
    )


async def run_all_series() -> tuple[int, int, str]:
    tmp_path = Path("/tmp/orchestrator_series_test")
    results = []

    # 1. Steady
    clock1 = FakeClock()
    ctx1, recs1 = _build_context(clock1, tmp_path)
    orch1 = OrchestratorService(ctx=ctx1, clock=clock1, battery_predictor=BatteryPredictor(ctx=ctx1))
    for _ in range(10):
        st = _make_stats("dev-source", ts=clock1(), cpu=25.0, mem=35.0, battery_pct=75.0)
        await orch1.process_stats(st)
        clock1.advance(5.0)
    p1 = len(recs1) == 0
    results.append(("1. Steady Workload", "Normal battery (75%), CPU 25%, RAM 35%", "None",
                    "None" if not recs1 else recs1[0].trigger, "PASS" if p1 else "FAIL"))

    # 2. Slow Drain
    clock2 = FakeClock()
    ctx2, recs2 = _build_context(clock2, tmp_path)
    orch2 = OrchestratorService(ctx=ctx2, clock=clock2, battery_predictor=BatteryPredictor(ctx=ctx2))
    for i in range(7):
        pct = 40.0 - (i * 0.25)
        await orch2.process_stats(
            _make_stats("dev-source", ts=clock2(), cpu=20.0, battery_pct=pct, charging=False)
        )
        clock2.advance(5.0)
    p2 = any(r.trigger == "predicted" for r in recs2)
    results.append(("2. Slow Battery Drain", "Linear discharge projecting TTE < 900s", "predicted",
                    "predicted" if p2 else "None", "PASS" if p2 else "FAIL"))

    # 3. Sudden Drop
    clock3 = FakeClock()
    ctx3, recs3 = _build_context(clock3, tmp_path)
    orch3 = OrchestratorService(ctx=ctx3, clock=clock3, battery_predictor=BatteryPredictor(ctx=ctx3))
    await orch3.process_stats(_make_stats("dev-source", ts=clock3(), battery_pct=35.0))
    clock3.advance(1.0)
    await orch3.process_stats(_make_stats("dev-source", ts=clock3(), battery_pct=14.0))
    p3 = any(r.trigger == "low_battery" for r in recs3)
    results.append(("3. Sudden Battery Drop", "Battery drops to 14% (<20% threshold)", "low_battery",
                    "low_battery" if p3 else "None", "PASS" if p3 else "FAIL"))

    # 4. CPU Spike
    clock4 = FakeClock()
    ctx4, recs4 = _build_context(clock4, tmp_path)
    orch4 = OrchestratorService(ctx=ctx4, clock=clock4, battery_predictor=BatteryPredictor(ctx=ctx4))
    await orch4.process_stats(_make_stats("dev-source", ts=clock4(), cpu=95.0))
    clock4.advance(21.0)
    await orch4.process_stats(_make_stats("dev-source", ts=clock4(), cpu=95.0))
    p4 = any(r.trigger == "cpu_pressure" for r in recs4)
    results.append(("4. CPU Pressure Spike", "CPU > 90% sustained for 21 seconds (>20s)", "cpu_pressure",
                    "cpu_pressure" if p4 else "None", "PASS" if p4 else "FAIL"))

    # 5. Memory Climb
    clock5 = FakeClock()
    ctx5, recs5 = _build_context(clock5, tmp_path)
    orch5 = OrchestratorService(ctx=ctx5, clock=clock5, battery_predictor=BatteryPredictor(ctx=ctx5))
    await orch5.process_stats(_make_stats("dev-source", ts=clock5(), mem=94.0))
    clock5.advance(21.0)
    await orch5.process_stats(_make_stats("dev-source", ts=clock5(), mem=96.0))
    p5 = any(r.trigger == "memory_pressure" for r in recs5)
    results.append(
        (
            "5. Memory Pressure Climb",
            "RAM > 90% sustained for 21 seconds (>20s)",
            "memory_pressure",
            "memory_pressure" if p5 else "None",
            "PASS" if p5 else "FAIL",
        )
    )

    # 6. Wi-Fi Loss
    clock6 = FakeClock()
    ctx6, recs6 = _build_context(clock6, tmp_path)
    orch6 = OrchestratorService(ctx=ctx6, clock=clock6, battery_predictor=BatteryPredictor(ctx=ctx6))
    await orch6.process_link(LinkQuality(
        peerId="dev-target", link="wifi", rttMs=999.0, mbps=0.0, lossPct=100.0, ts=clock6()
    ))
    clock6.advance(3.5)
    await orch6.process_link(LinkQuality(
        peerId="dev-target", link="wifi", rttMs=999.0, mbps=0.0, lossPct=100.0, ts=clock6()
    ))
    p6 = any(r.trigger == "connectivity_lost" for r in recs6)
    results.append(
        (
            "6. Connectivity Lost",
            "Link down (100% loss) for 3.5s (>3s window)",
            "connectivity_lost",
            "connectivity_lost" if p6 else "None",
            "PASS" if p6 else "FAIL",
        )
    )

    # 7. Charger Plugged In Halfway
    clock7 = FakeClock()
    ctx7, recs7 = _build_context(clock7, tmp_path)
    orch7 = OrchestratorService(ctx=ctx7, clock=clock7, battery_predictor=BatteryPredictor(ctx=ctx7))
    await orch7.process_stats(_make_stats("dev-source", ts=clock7(), battery_pct=25.0, charging=False))
    clock7.advance(5.0)
    await orch7.process_stats(_make_stats("dev-source", ts=clock7(), battery_pct=18.0, charging=True))
    p7 = not any(r.trigger in ("low_battery", "predicted") for r in recs7)
    results.append(("7. Charger Connected", "Charger connected at 18% suppresses low_battery", "Suppressed",
                    "Suppressed" if p7 else "Fired", "PASS" if p7 else "FAIL"))

    # 8. Noisy Battery
    clock8 = FakeClock()
    ctx8, recs8 = _build_context(clock8, tmp_path)
    orch8 = OrchestratorService(ctx=ctx8, clock=clock8, battery_predictor=BatteryPredictor(ctx=ctx8))
    for pct in [45.0, 65.0, 30.0, 70.0, 40.0, 60.0]:
        await orch8.process_stats(_make_stats("dev-source", ts=clock8(), battery_pct=pct))
        clock8.advance(5.0)
    p8 = not any(r.trigger == "predicted" for r in recs8)
    results.append(("8. Noisy Battery Readings", "Erratic readings rejected by OLS noise filter", "Rejected",
                    "Rejected" if p8 else "Fired", "PASS" if p8 else "FAIL"))

    # 9. Transient CPU Spike
    clock9 = FakeClock()
    ctx9, recs9 = _build_context(clock9, tmp_path)
    orch9 = OrchestratorService(ctx=ctx9, clock=clock9, battery_predictor=BatteryPredictor(ctx=ctx9))
    await orch9.process_stats(_make_stats("dev-source", ts=clock9(), cpu=98.0))
    clock9.advance(8.0)
    await orch9.process_stats(_make_stats("dev-source", ts=clock9(), cpu=30.0))
    clock9.advance(15.0)
    await orch9.process_stats(_make_stats("dev-source", ts=clock9(), cpu=30.0))
    p9 = not any(r.trigger == "cpu_pressure" for r in recs9)
    results.append(("9. Transient CPU Spike", "CPU spike lasting 8s (<20s window) drops back", "None",
                    "None" if p9 else "cpu_pressure", "PASS" if p9 else "FAIL"))

    # 10. Candidate Recommendation
    clock10 = FakeClock()
    ctx10, recs10 = _build_context(clock10, tmp_path)
    orch10 = OrchestratorService(ctx=ctx10, clock=clock10, battery_predictor=BatteryPredictor(ctx=ctx10))
    await orch10.process_stats(_make_stats("dev-source", ts=clock10(), battery_pct=15.0, charging=False))
    p10 = len(recs10) == 1 and recs10[0].targetId == "dev-target" and recs10[0].decision == "MIGRATE"
    act_str = f"{recs10[0].targetId} ({recs10[0].decision})" if recs10 else "None"
    results.append(
        (
            "10. Candidate Selection",
            "Low battery trigger produces target recommendation",
            "dev-target (MIGRATE)",
            act_str,
            "PASS" if p10 else "FAIL",
        )
    )

    passed = sum(1 for _, _, _, _, st in results if st == "PASS")
    failed = len(results) - passed

    # Build Markdown table
    lines = [
        "# Orchestrator Telemetry Series Evaluation Report",
        "",
        f"**Total Series Evaluated**: {len(results)}  ",
        f"**Passed**: {passed} | **Failed**: {failed}  ",
        f"**Pass Rate**: {(passed / len(results) * 100):.1f}%  ",
        "",
        "## Evaluated Series Matrix",
        "",
        "| Series | Description | Expected Trigger | Actual Trigger | Status |",
        "| :--- | :--- | :--- | :--- | :--- |",
    ]
    for name, desc, exp, act, st in results:
        lines.append(f"| **{name}** | {desc} | `{exp}` | `{act}` | **{st}** |")

    lines.extend([
        "",
        "## Tuning and Hysteresis Highlights",
        "- **Sliding Windows**: Continuous 20s window on CPU/RAM avoid spurious load spikes.",
        "- **Connectivity Loss**: Detects complete packet loss or zero throughput sustained for 3.0 seconds.",
        "- **OLS Battery Filter**: Rejects erratic telemetry (R^2 < 0.6) and suppresses alerts on charger.",
        "- **Action Cooldown**: Enforces 2-minute quiet period per workload to avoid recommendation storms.",
        "",
    ])

    report_text = "\n".join(lines)
    return passed, failed, report_text


def main() -> int:
    print("=" * 80)
    print("Teleport Orchestrator Telemetry Series Runner (P3)")
    print("=" * 80)

    passed, failed, report = asyncio.run(run_all_series())

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(report)

    print(report)
    print(f"\n[DONE] Report written to: {REPORT_PATH}")
    print(f"Summary: {passed} passed, {failed} failed.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

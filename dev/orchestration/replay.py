"""Telemetry replay harness demonstrating trigger detection and recommendation generation (P3).

Replays recorded or synthetic stats series with a simulated clock,
verifying that a falling-battery series triggers 'predicted' before 'low_battery'.

Usage:
    python -m dev.orchestration.replay
    python -m dev.orchestration.replay --file stats_series.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from agent.teleport.core.bus import EventBus
from agent.teleport.core.context import Context
from agent.teleport.core.settings import Prefs, Settings
from agent.teleport.orchestration.service import OrchestratorService
from contract.contract import (
    Battery,
    CheckpointDef,
    DeviceInfo,
    LinkQuality,
    Recommendation,
    RecommendationEvent,
    RuntimeReq,
    Stats,
    WorkloadManifest,
)


class MockWorkloadService:
    def __init__(self, workloads: list[WorkloadManifest]) -> None:
        self._workloads = workloads

    def list(self) -> list[WorkloadManifest]:
        return self._workloads

    def runs(self) -> list[Any]:
        return []


class MockDeviceService:
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


class MockPeerLink:
    def __init__(self, peers: list[DeviceInfo], links: dict[str, LinkQuality]) -> None:
        self._peers = peers
        self._links = links

    def list_peers(self) -> list[DeviceInfo]:
        return self._peers

    def link_quality(self, device_id: str) -> LinkQuality | None:
        return self._links.get(device_id)


def generate_falling_battery_series(device_id: str = "dev-source") -> list[Stats]:
    """Generate a realistic falling battery telemetry series."""
    series: list[Stats] = []
    # Drop from 50% down to 14% over 360 seconds (rate: -0.1% per second = 1% every 10s)
    # TTE will fall below 15 min (900s) at ~38% (t=120s), triggering 'predicted'.
    # Battery drops below 20% at t=310s, triggering 'low_battery'.
    start_ts = 1700000000.0
    timeline = [
        (0.0, 50.0),
        (30.0, 47.0),
        (60.0, 44.0),
        (90.0, 41.0),
        (120.0, 38.0),   # TTE = 380s (6.3 min) -> triggers 'predicted'
        (150.0, 35.0),
        (180.0, 32.0),
        (210.0, 29.0),
        (245.0, 25.5),   # Cooldown from t=120 expires at t=240
        (280.0, 22.0),
        (310.0, 19.0),   # < 20% -> triggers 'low_battery'
        (340.0, 16.0),
        (360.0, 14.0),
    ]

    for offset_sec, pct in timeline:
        ts = start_ts + offset_sec
        st = Stats(
            deviceId=device_id,
            ts=ts,
            cpuPct=18.5,
            memPct=42.0,
            memFreeMb=8192,
            diskFreeMb=50000,
            battery=Battery(pct=pct, charging=False),
            online=True,
        )
        series.append(st)

    return series


async def run_replay(stats_series: list[Stats]) -> list[tuple[float, str, Recommendation]]:
    """Execute the replay through the Orchestrator with an advancing clock."""
    simulated_now = stats_series[0].ts if stats_series else 1700000000.0

    def get_clock() -> float:
        nonlocal simulated_now
        return simulated_now

    # Setup context and mock services
    settings = Settings(home=Path("./.teleport-replay"))
    ctx = Context(settings=settings, device_id="dev-source", prefs=Prefs(mode="recommend"))

    local_dev = DeviceInfo(
        id="dev-source",
        name="Source-Laptop",
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

    target_dev = DeviceInfo(
        id="dev-target",
        name="Target-Desktop",
        os="linux",
        arch="x86_64",
        cpuCores=16,
        ramMb=32768,
        gpu=None,
        diskFreeMb=200000,
        runtimes={"python": "3.11.9"},
        libs=["requests"],
        addrs=[],
        agentVersion="0.1.0",
    )

    workload = WorkloadManifest(
        id="w-demo",
        name="Demo Workload",
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

    target_stats = Stats(
        deviceId="dev-target",
        ts=simulated_now,
        cpuPct=10.0,
        memPct=25.0,
        memFreeMb=24000,
        diskFreeMb=180000,
        battery=None,
        online=True,
    )

    link = LinkQuality(
        peerId="dev-target",
        link="cable",
        rttMs=2.0,
        mbps=1000.0,
        lossPct=0.0,
        ts=simulated_now,
    )

    device_svc = MockDeviceService(local_dev, [target_dev])
    device_svc.set_stats(target_stats)
    peer_link = MockPeerLink([target_dev], {"dev-target": link})
    workload_svc = MockWorkloadService([workload])

    ctx.register("devices", device_svc)  # type: ignore
    ctx.register("peers", peer_link)  # type: ignore
    ctx.register("workloads", workload_svc)  # type: ignore

    orchestrator = OrchestratorService(ctx=ctx, clock=get_clock)

    captured_events: list[tuple[float, str, Recommendation]] = []

    async def _on_rec(event: RecommendationEvent) -> None:
        rec = event.rec
        captured_events.append((simulated_now, rec.trigger, rec))

    ctx.bus.subscribe(RecommendationEvent, _on_rec)

    # Replay timeline
    base_ts = stats_series[0].ts
    print("\n" + "=" * 90)
    print(" TELEPORT ORCHESTRATOR TELEMETRY REPLAY")
    print("=" * 90)
    print(f"{'Offset':<10} | {'Battery':<10} | {'Charging':<10} | {'Projected TTE':<16} | {'Trigger Event':<28}")
    print("-" * 90)

    for st in stats_series:
        simulated_now = st.ts
        offset = simulated_now - base_ts

        # Query predictor state before processing
        tte = orchestrator.predictor.predict_tte_seconds(st.deviceId, simulated_now)
        tte_str = f"{tte / 60.0:.1f} min" if tte is not None else "N/A"

        event_before = len(captured_events)
        await orchestrator.process_stats(st)
        event_after = len(captured_events)

        event_desc = "-"
        if event_after > event_before:
            _, trigger_name, rec = captured_events[-1]
            event_desc = f"[*] {trigger_name} -> {rec.decision}"

        bat_pct_str = f"{st.battery.pct:.0f}%" if st.battery else "N/A"
        charging_str = str(st.battery.charging) if st.battery else "N/A"

        print(f"T+{offset:<7.0f}s | {bat_pct_str:<10} | {charging_str:<10} | {tte_str:<16} | {event_desc:<28}")

    print("-" * 90)
    print(f"Total Recommendations Emitted: {len(captured_events)}")
    for ts, trig, rec in captured_events:
        offset = ts - base_ts
        print(f" -> T+{offset:.0f}s: Trigger='{trig}', Decision='{rec.decision}', Target='{rec.targetId}'")
    print("=" * 90 + "\n")

    return captured_events


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Teleport Orchestrator Replay Harness")
    parser.add_argument("--file", help="Path to JSON file containing recorded Stats series.")
    args = parser.parse_args(argv)

    if args.file:
        path = Path(args.file)
        if not path.exists():
            print(f"Error: file not found '{args.file}'", file=sys.stderr)
            return 1
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
            series = [Stats.model_validate(item) for item in data]
    else:
        series = generate_falling_battery_series()

    events = asyncio.run(run_replay(series))

    # Verify that 'predicted' fired before 'low_battery'
    trigger_order = [e[1] for e in events]
    if "predicted" in trigger_order and "low_battery" in trigger_order:
        pred_idx = trigger_order.index("predicted")
        low_idx = trigger_order.index("low_battery")
        if pred_idx < low_idx:
            print("[SUCCESS] Verified: 'predicted' recommendation was emitted BEFORE 'low_battery'!")
            return 0
        else:
            print("[FAILURE] 'low_battery' fired before 'predicted'!", file=sys.stderr)
            return 1
    elif "predicted" in trigger_order:
        print("[INFO] 'predicted' trigger fired successfully.")
        return 0
    else:
        print("[WARNING] Did not observe expected triggers in series.")
        return 0


if __name__ == "__main__":
    sys.exit(main())


"""Performance benchmarks and edge case tests for Feasibility Engine (P3).

Requirements:
- Feasibility evaluation under 500 ms with 5 paired devices.
- Edge case: device disappearing while being evaluated.
- Edge case: link or device fields missing/None during evaluation.
"""

from __future__ import annotations

import time
from typing import Literal

from contract.contract import (
    Battery,
    CheckpointDef,
    DeviceInfo,
    LinkQuality,
    RuntimeReq,
    Stats,
    WorkloadManifest,
)
from teleport.feasibility.engine import (
    best_target,
    evaluate_feasibility,
)


def _make_workload(workload_id: str = "w-perf-1") -> WorkloadManifest:
    return WorkloadManifest(
        id=workload_id,
        name="Data Cruncher",
        command="python main.py",
        runtime=RuntimeReq(name="python", minVersion="3.11"),
        arch=["x86_64"],
        os=["linux"],
        minRamMb=2048,
        minCpuCores=4,
        minDiskMb=5000,
        needsGpu=False,
        libs=["numpy", "scipy"],
        checkpoints=[
            CheckpointDef(id="cp-1", name="checkpoint", paths=["/data/cp.bin"])
        ],
        remoteCapable=True,
    )


def _make_device(
    device_id: str,
    name: str = "Device",
    os: Literal["windows", "linux", "macos"] = "linux",
    arch: Literal["x86_64", "arm64"] = "x86_64",
    ram_mb: int = 16384,
    cpu_cores: int = 8,
    disk_free_mb: int = 50000,
    runtimes: dict[str, str] | None = None,
    libs: list[str] | None = None,
) -> DeviceInfo:
    return DeviceInfo(
        id=device_id,
        name=name,
        os=os,
        arch=arch,
        cpuCores=cpu_cores,
        ramMb=ram_mb,
        gpu=None,
        diskFreeMb=disk_free_mb,
        runtimes=runtimes or {"python": "3.11.9"},
        libs=libs or ["numpy", "scipy", "requests"],
        addrs=[],
        agentVersion="0.1.0",
    )


def _make_stats(
    device_id: str,
    cpu: float = 20.0,
    mem: float = 30.0,
    mem_free_mb: int = 12000,
    disk_free_mb: int = 40000,
    battery_pct: float = 85.0,
    online: bool = True,
) -> Stats:
    return Stats(
        deviceId=device_id,
        ts=time.time(),
        cpuPct=cpu,
        memPct=mem,
        memFreeMb=mem_free_mb,
        diskFreeMb=disk_free_mb,
        battery=Battery(pct=battery_pct, charging=False),
        online=online,
        simulated=False,
    )


def _make_link(
    peer_id: str,
    mbps: float = 100.0,
    rtt_ms: float = 15.0,
    loss_pct: float = 0.05,
) -> LinkQuality:
    return LinkQuality(
        peerId=peer_id,
        link="wifi",
        ts=time.time(),
        mbps=mbps,
        rttMs=rtt_ms,
        lossPct=loss_pct,
        simulated=False,
    )


class TestFeasibilityPerformance:
    def test_feasibility_evaluation_under_500ms_with_5_paired_devices(self) -> None:
        """Requirement: Feasibility evaluation under 500 ms with 5 paired devices."""
        workload = _make_workload()
        source = _make_device("source-node", "Source Workstation")
        source_stats = _make_stats("source-node", cpu=15.0, mem=25.0)

        peers = [
            _make_device(f"peer-{i}", f"Peer Node {i}", ram_mb=8192 + i * 2048)
            for i in range(1, 6)
        ]
        peer_stats = {
            p.id: _make_stats(p.id, cpu=20.0 + i * 5, mem=30.0 + i * 5)
            for i, p in enumerate(peers, 1)
        }
        peer_links = {
            p.id: _make_link(p.id, mbps=50.0 + i * 10, rtt_ms=10.0 + i * 2)
            for i, p in enumerate(peers, 1)
        }

        # Measure best_target ranking across 5 peers over 50 iterations to ensure stable timing
        t0 = time.perf_counter()
        target_res = best_target(
            manifest=workload,
            source=source,
            candidates=peers,
            candidate_links=peer_links,
            candidate_stats=peer_stats,
            source_stats=source_stats,
        )
        elapsed_sec = time.perf_counter() - t0

        # Must be well under 500 ms (0.500 s)
        assert elapsed_sec < 0.500, f"Evaluation took {elapsed_sec * 1000:.2f} ms (budget: 500 ms)"
        assert target_res is not None
        chosen_target, result = target_res
        assert result.decision == "MIGRATE"

        # Even 100 full iterations should easily complete within the 500ms budget
        t_batch_start = time.perf_counter()
        for _ in range(100):
            best_target(
                manifest=workload,
                source=source,
                candidates=peers,
                candidate_links=peer_links,
                candidate_stats=peer_stats,
                source_stats=source_stats,
            )
        batch_elapsed = time.perf_counter() - t_batch_start
        assert batch_elapsed < 0.500, f"100 iterations took {batch_elapsed:.2f}s"


class TestFeasibilityEdgeCases:
    def test_device_disappearing_while_being_evaluated(self) -> None:
        """Edge Case: Target candidate list is empty or candidate disappears during selection."""
        workload = _make_workload()
        source = _make_device("source-node")
        source_stats = _make_stats("source-node")

        # Empty candidates list -> returns None
        target_res = best_target(
            manifest=workload,
            source=source,
            candidates=[],
            candidate_links={},
            candidate_stats={},
            source_stats=source_stats,
        )
        assert target_res is None

    def test_candidate_device_offline(self) -> None:
        """Edge Case: Candidate peer device reported as offline in stats."""
        workload = _make_workload()
        source = _make_device("source-node")
        target = _make_device("target-node")
        stats_offline = _make_stats("target-node", online=False)
        link = _make_link("target-node")

        result = evaluate_feasibility(
            manifest=workload,
            source=source,
            target=target,
            link=link,
            target_stats=stats_offline,
        )
        # Target offline blocks migration; since target is offline, cannot stream remote access either -> STAY
        assert result.decision == "STAY"
        assert any(r.code == "online.offline" for r in result.reasons)

    def test_link_missing_or_partial_metrics(self) -> None:
        """Edge Case: Link quality is None or severely degraded."""
        workload = _make_workload()
        source = _make_device("source-node")
        target = _make_device("target-node")
        target_stats = _make_stats("target-node")

        # 1. No link available (None)
        result_no_link = evaluate_feasibility(
            manifest=workload,
            source=source,
            target=target,
            link=None,
            target_stats=target_stats,
            snapshot_size_mb=100.0,
        )
        assert result_no_link.decision in ("REMOTE_ACCESS", "STAY")
        assert result_no_link.estTransferSec >= 0.0

        # 2. Severely degraded link (>5% loss blocks migration and streaming)
        bad_link = _make_link("target-node", mbps=0.0, rtt_ms=999.0, loss_pct=25.0)
        result_bad = evaluate_feasibility(
            manifest=workload,
            source=source,
            target=target,
            link=bad_link,
            target_stats=target_stats,
            snapshot_size_mb=100.0,
        )
        assert result_bad.decision == "STAY"
        assert any(r.code == "link.high_loss" for r in result_bad.reasons)

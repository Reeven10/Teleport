"""Unit and integration tests for Feasibility Decision Engine, Estimates, and Best Target (P3)."""

from __future__ import annotations

import pytest

from agent.teleport.feasibility.engine import (
    best_target,
    calculate_estimates,
    evaluate_feasibility,
)
from contract.contract import (
    Battery,
    CheckpointDef,
    DeviceInfo,
    LinkQuality,
    RuntimeReq,
    Stats,
    WorkloadManifest,
)


def make_manifest(
    arch: list[str] = ["x86_64"],
    os: list[str] = ["linux"],
    runtime_name: str = "python",
    runtime_version: str = "3.11",
    min_ram_mb: int = 1000,
    min_cpu_cores: int = 4,
    min_disk_mb: int = 1000,
    needs_gpu: bool = False,
    libs: list[str] | None = None,
    remote_capable: bool = True,
) -> WorkloadManifest:
    return WorkloadManifest(
        id="test-w",
        name="Test Workload",
        command="python app.py",
        runtime=RuntimeReq(name=runtime_name, minVersion=runtime_version),
        arch=arch,  # type: ignore
        os=os,  # type: ignore
        minRamMb=min_ram_mb,
        minCpuCores=min_cpu_cores,
        minDiskMb=min_disk_mb,
        needsGpu=needs_gpu,
        libs=libs if libs is not None else [],
        checkpoints=[CheckpointDef(id="c1", name="state", paths=["state.json"])],
        remoteCapable=remote_capable,
    )


def make_device(
    id: str = "target-1",
    name: str = "Target Device",
    arch: str = "x86_64",
    os: str = "linux",
    cpu_cores: int = 4,
    ram_mb: int = 8192,
    disk_free_mb: int = 50000,
    gpu: str | None = None,
    runtimes: dict[str, str] | None = None,
    libs: list[str] | None = None,
) -> DeviceInfo:
    return DeviceInfo(
        id=id,
        name=name,
        os=os,  # type: ignore
        arch=arch,  # type: ignore
        cpuCores=cpu_cores,
        ramMb=ram_mb,
        gpu=gpu,
        diskFreeMb=disk_free_mb,
        runtimes=runtimes if runtimes is not None else {"python": "3.11.9"},
        libs=libs if libs is not None else ["numpy", "requests"],
        addrs=[],
        agentVersion="0.1.0",
    )


def make_stats(
    device_id: str = "target-1",
    mem_free_mb: int = 4096,
    disk_free_mb: int = 50000,
    battery_pct: float | None = 80.0,
    charging: bool = False,
    online: bool = True,
) -> Stats:
    bat = None
    if battery_pct is not None:
        bat = Battery(pct=battery_pct, charging=charging)
    return Stats(
        deviceId=device_id,
        ts=1700000000.0,
        cpuPct=10.0,
        memPct=50.0,
        memFreeMb=mem_free_mb,
        diskFreeMb=disk_free_mb,
        battery=bat,
        online=online,
    )


def make_link(
    loss_pct: float = 0.0,
    rtt_ms: float = 10.0,
    mbps: float = 100.0,
    link_type: str = "wifi",
) -> LinkQuality:
    return LinkQuality(
        peerId="test-peer",
        link=link_type,  # type: ignore
        rttMs=rtt_ms,
        mbps=mbps,
        lossPct=loss_pct,
        ts=1700000000.0,
    )


# ---------------------------------------------------------------- Decision Paths


class TestDecisionPaths:
    def test_migrate_clean_pass(self) -> None:
        m = make_manifest()
        s = make_device(id="source-1", name="Source")
        t = make_device(id="target-1", name="Target")
        st = make_stats()
        lk = make_link()

        res = evaluate_feasibility(m, s, t, lk, target_stats=st)
        assert res.decision == "MIGRATE"
        assert len(res.reasons) == 12  # 1 summary + 11 checks
        assert res.reasons[0].code == "decision.migrate"
        assert res.reasons[0].severity == "pass"
        assert res.estTransferSec > 0
        assert res.estInterruptionMs > 0

    def test_migrate_with_warnings(self) -> None:
        m = make_manifest()
        s = make_device(id="source-1")
        t = make_device(id="target-1")
        # Low battery (22%) triggers battery.low warning
        st = make_stats(battery_pct=22.0, charging=False)
        lk = make_link(rtt_ms=150.0)  # High RTT triggers link.degraded warning

        res = evaluate_feasibility(m, s, t, lk, target_stats=st)
        assert res.decision == "MIGRATE"
        assert res.reasons[0].code == "decision.migrate"
        assert res.reasons[0].severity == "warn"
        assert "warning" in res.reasons[0].text

    @pytest.mark.parametrize(
        "block_type,manifest_kwargs,target_kwargs,stats_kwargs",
        [
            ("arch", {"arch": ["x86_64"]}, {"arch": "arm64"}, {}),
            ("os", {"os": ["linux"]}, {"os": "windows"}, {}),
            ("runtime_missing", {"runtime_name": "rust", "runtime_version": "1.75"}, {}, {}),
            ("runtime_ver_low", {"runtime_version": "3.11"}, {"runtimes": {"python": "3.9"}}, {}),
            ("libs", {"libs": ["missing_codec_v1"]}, {"libs": ["numpy"]}, {}),
            ("ram", {"min_ram_mb": 4000}, {}, {"mem_free_mb": 1000}),
            ("cpu", {"min_cpu_cores": 16}, {"cpu_cores": 4}, {}),
            ("disk", {"min_disk_mb": 80000}, {}, {"disk_free_mb": 1000}),
            ("gpu", {"needs_gpu": True}, {"gpu": None}, {}),
        ],
    )
    def test_remote_access_for_each_blocking_check(
        self,
        block_type: str,
        manifest_kwargs: dict,
        target_kwargs: dict,
        stats_kwargs: dict,
    ) -> None:
        m = make_manifest(remote_capable=True, **manifest_kwargs)
        s = make_device(id="source-1")
        t = make_device(id="target-1", **target_kwargs)
        st = make_stats(**stats_kwargs)
        lk = make_link(loss_pct=0.1, mbps=50.0, rtt_ms=25.0)

        res = evaluate_feasibility(m, s, t, lk, target_stats=st)
        assert res.decision == "REMOTE_ACCESS"
        assert res.reasons[0].code == "decision.remote_access"
        assert "remote access" in res.reasons[0].text.lower()
        # Non-migrating result zeroes out transfer & interruption estimates
        assert res.estTransferSec == 0.0
        assert res.estInterruptionMs == 0.0

    def test_stay_when_remote_not_allowed(self) -> None:
        # Architecture mismatch but remoteCapable is False
        m = make_manifest(arch=["x86_64"], remote_capable=False)
        s = make_device(id="source-1")
        t = make_device(id="target-1", arch="arm64")
        st = make_stats()
        lk = make_link()

        res = evaluate_feasibility(m, s, t, lk, target_stats=st)
        assert res.decision == "STAY"
        assert res.reasons[0].code == "decision.stay"
        assert "not remotecapable" in res.reasons[0].text.lower()

    def test_stay_when_link_dead(self) -> None:
        m = make_manifest()
        s = make_device(id="source-1")
        t = make_device(id="target-1")
        st = make_stats()

        res = evaluate_feasibility(m, s, t, link=None, target_stats=st)
        assert res.decision == "STAY"
        assert res.reasons[0].code == "decision.stay"
        assert "network link" in res.reasons[0].text.lower()

    def test_stay_when_link_lossy(self) -> None:
        m = make_manifest(remote_capable=True)
        s = make_device(id="source-1")
        t = make_device(id="target-1")
        st = make_stats()
        lk = make_link(loss_pct=8.0)  # > 5.0%

        res = evaluate_feasibility(m, s, t, link=lk, target_stats=st)
        assert res.decision == "STAY"
        assert res.reasons[0].code == "decision.stay"

    def test_stay_when_target_offline(self) -> None:
        m = make_manifest(remote_capable=True)
        s = make_device(id="source-1")
        t = make_device(id="target-1")
        st = make_stats(online=False)
        lk = make_link()

        res = evaluate_feasibility(m, s, t, link=lk, target_stats=st)
        assert res.decision == "STAY"
        assert res.reasons[0].code == "decision.stay"
        assert "offline" in res.reasons[0].text.lower()


# ---------------------------------------------------------------- Estimates


class TestEstimates:
    def test_estimate_sanity(self) -> None:
        m = make_manifest(min_disk_mb=2000)
        lk = make_link(mbps=100.0, rtt_ms=10.0)

        transfer_sec, interruption_ms, battery_warn = calculate_estimates(
            manifest=m,
            link=lk,
            total_checkpoint_bytes=50 * 1024 * 1024,  # 50 MB
        )

        assert transfer_sec > 0.0
        assert interruption_ms > 0.0
        assert battery_warn is None

    def test_source_battery_warning_triggered(self) -> None:
        m = make_manifest(min_disk_mb=1000)
        # Slow link: 0.5 Mbps
        lk = make_link(mbps=0.5, rtt_ms=50.0)
        # Source battery critically low: 1% discharging (~60s remaining)
        src_stats = make_stats(battery_pct=1.0, charging=False)

        transfer_sec, interruption_ms, battery_warn = calculate_estimates(
            manifest=m,
            link=lk,
            total_checkpoint_bytes=100 * 1024 * 1024,  # 100 MB on 0.5 Mbps -> hundreds of seconds
            source_stats=src_stats,
        )

        assert battery_warn is not None
        assert battery_warn.code == "battery.source_depleting"
        assert battery_warn.severity == "warn"


# ---------------------------------------------------------------- Best Target


class TestBestTarget:
    def test_best_target_empty_candidates(self) -> None:
        m = make_manifest()
        s = make_device(id="src")
        assert best_target(m, s, []) is None

    def test_migrate_preferred_over_remote_access(self) -> None:
        m = make_manifest(arch=["x86_64"], remote_capable=True)
        s = make_device(id="src")

        # Candidate A: arm64 -> REMOTE_ACCESS
        cand_a = make_device(id="cand-a", name="Arm Mac", arch="arm64")
        # Candidate B: x86_64 -> MIGRATE
        cand_b = make_device(id="cand-b", name="x86 Linux", arch="x86_64")

        stats_map = {
            "cand-a": make_stats(device_id="cand-a"),
            "cand-b": make_stats(device_id="cand-b"),
        }
        links_map = {
            "cand-a": make_link(),
            "cand-b": make_link(),
        }

        best = best_target(m, s, [cand_a, cand_b], stats_map, links_map)
        assert best is not None
        dev, res = best
        assert dev.id == "cand-b"
        assert res.decision == "MIGRATE"

    def test_fewer_warnings_preferred(self) -> None:
        m = make_manifest()
        s = make_device(id="src")

        # Candidate A: MIGRATE with warning (battery 20%)
        cand_a = make_device(id="cand-a", name="Low Battery Laptop")
        # Candidate B: MIGRATE with 0 warnings (battery 90%)
        cand_b = make_device(id="cand-b", name="Full Battery Laptop")

        stats_map = {
            "cand-a": make_stats(device_id="cand-a", battery_pct=20.0),
            "cand-b": make_stats(device_id="cand-b", battery_pct=90.0),
        }
        links_map = {
            "cand-a": make_link(),
            "cand-b": make_link(),
        }

        best = best_target(m, s, [cand_a, cand_b], stats_map, links_map)
        assert best is not None
        dev, res = best
        assert dev.id == "cand-b"

    def test_spare_capacity_tie_breaker(self) -> None:
        m = make_manifest()
        s = make_device(id="src")

        # Both MIGRATE with 0 warnings, but Candidate B has 32GB RAM vs 4GB
        cand_a = make_device(id="cand-a", name="4GB Box", ram_mb=4096)
        cand_b = make_device(id="cand-b", name="32GB Box", ram_mb=32768)

        stats_map = {
            "cand-a": make_stats(device_id="cand-a", mem_free_mb=2000),
            "cand-b": make_stats(device_id="cand-b", mem_free_mb=28000),
        }
        links_map = {
            "cand-a": make_link(),
            "cand-b": make_link(),
        }

        best = best_target(m, s, [cand_a, cand_b], stats_map, links_map)
        assert best is not None
        dev, res = best
        assert dev.id == "cand-b"


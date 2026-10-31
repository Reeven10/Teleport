"""Unit tests for pure feasibility check functions and edge cases (P3)."""

from __future__ import annotations

import pytest

from contract.contract import (
    Battery,
    CheckpointDef,
    DeviceInfo,
    LinkQuality,
    RuntimeReq,
    Stats,
    WorkloadManifest,
)
from teleport.feasibility.checks import (
    check_architecture,
    check_cpu_cores,
    check_disk,
    check_gpu,
    check_libraries,
    check_link_quality,
    check_os,
    check_ram,
    check_runtime,
    check_target_battery,
    check_target_online,
    compare_versions,
    run_all_checks,
)
from tests.feasibility.fixtures import (
    ALL_DEVICE_FILES,
    ALL_MANIFEST_FILES,
    load_device,
    load_link,
    load_manifest,
    load_stats,
)


# Helper builders
def make_manifest(
    arch: list[str] | None = None,
    os: list[str] | None = None,
    runtime_name: str = "python",
    runtime_version: str = "3.11",
    min_ram_mb: int = 1000,
    min_cpu_cores: int = 4,
    min_disk_mb: int = 1000,
    needs_gpu: bool = False,
    libs: list[str] | None = None,
    remote_capable: bool = True,
) -> WorkloadManifest:
    if arch is None:
        arch = ["x86_64"]
    if os is None:
        os = ["linux"]
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
        id="test-dev",
        name="Test Device",
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
        deviceId="test-dev",
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


# ---------------------------------------------------------------- Tests: Version Comparison


class TestVersionComparison:
    def test_version_greater(self) -> None:
        assert compare_versions("3.11.4", "3.11") is True
        assert compare_versions("3.12", "3.11") is True
        assert compare_versions("3.11.1", "3.11.0") is True

    def test_version_equal(self) -> None:
        assert compare_versions("3.11", "3.11") is True
        assert compare_versions("3.11.0", "3.11") is True
        assert compare_versions("v3.11.4", "3.11.4") is True

    def test_version_lower(self) -> None:
        assert compare_versions("3.9", "3.11") is False
        assert compare_versions("3.9.18", "3.11") is False
        assert compare_versions("3.10.12", "3.11") is False
        assert compare_versions("3.11.3", "3.11.4") is False


# ---------------------------------------------------------------- Tests: Architecture


class TestArchitectureCheck:
    def test_match(self) -> None:
        m = make_manifest(arch=["x86_64", "arm64"])
        d = make_device(arch="x86_64")
        res = check_architecture(m, d)
        assert res.severity == "pass"
        assert res.code == "arch.match"
        assert "x86_64" in res.text

    def test_mismatch(self) -> None:
        m = make_manifest(arch=["x86_64"])
        d = make_device(arch="arm64")
        res = check_architecture(m, d)
        assert res.severity == "block"
        assert res.code == "arch.mismatch"
        assert "arm64" in res.text

    def test_missing_data(self) -> None:
        m = make_manifest()
        d = make_device()
        d.arch = None  # type: ignore
        res = check_architecture(m, d)
        assert res.severity == "warn"
        assert res.code == "arch.unknown"


# ---------------------------------------------------------------- Tests: OS


class TestOsCheck:
    def test_match(self) -> None:
        m = make_manifest(os=["linux", "windows"])
        d = make_device(os="windows")
        res = check_os(m, d)
        assert res.severity == "pass"
        assert res.code == "os.match"

    def test_mismatch(self) -> None:
        m = make_manifest(os=["linux"])
        d = make_device(os="macos")
        res = check_os(m, d)
        assert res.severity == "block"
        assert res.code == "os.mismatch"

    def test_missing_data(self) -> None:
        m = make_manifest()
        d = make_device()
        d.os = None  # type: ignore
        res = check_os(m, d)
        assert res.severity == "warn"
        assert res.code == "os.unknown"


# ---------------------------------------------------------------- Tests: Runtime


class TestRuntimeCheck:
    def test_runtime_boundary_exact_match(self) -> None:
        m = make_manifest(runtime_version="3.11")
        d = make_device(runtimes={"python": "3.11"})
        res = check_runtime(m, d)
        assert res.severity == "pass"
        assert res.code == "runtime.ok"

    def test_runtime_boundary_just_above(self) -> None:
        m = make_manifest(runtime_version="3.11")
        d = make_device(runtimes={"python": "3.11.4"})
        res = check_runtime(m, d)
        assert res.severity == "pass"
        assert res.code == "runtime.ok"

    def test_runtime_boundary_just_below(self) -> None:
        m = make_manifest(runtime_version="3.11")
        d = make_device(runtimes={"python": "3.9.18"})
        res = check_runtime(m, d)
        assert res.severity == "block"
        assert res.code == "runtime.version_low"

    def test_runtime_missing(self) -> None:
        m = make_manifest(runtime_name="rust", runtime_version="1.75")
        d = make_device(runtimes={"python": "3.11.9"})
        res = check_runtime(m, d)
        assert res.severity == "block"
        assert res.code == "runtime.missing"

    def test_missing_data(self) -> None:
        m = make_manifest()
        d = make_device()
        d.runtimes = None  # type: ignore
        res = check_runtime(m, d)
        assert res.severity == "warn"
        assert res.code == "runtime.unknown"


# ---------------------------------------------------------------- Tests: Libraries


class TestLibrariesCheck:
    def test_all_libraries_present(self) -> None:
        m = make_manifest(libs=["numpy", "requests"])
        d = make_device(libs=["numpy", "requests", "pandas", "scipy"])
        res = check_libraries(m, d)
        assert res.severity == "pass"
        assert res.code == "libs.ok"

    def test_no_libraries_required(self) -> None:
        m = make_manifest(libs=[])
        d = make_device(libs=[])
        res = check_libraries(m, d)
        assert res.severity == "pass"
        assert res.code == "libs.ok"

    def test_missing_library(self) -> None:
        m = make_manifest(libs=["numpy", "obscure_lib_x"])
        d = make_device(libs=["numpy", "requests"])
        res = check_libraries(m, d)
        assert res.severity == "block"
        assert res.code == "libs.missing"
        assert "obscure_lib_x" in res.text

    def test_missing_data(self) -> None:
        m = make_manifest()
        d = make_device()
        d.libs = None  # type: ignore
        res = check_libraries(m, d)
        assert res.severity == "warn"
        assert res.code == "libs.unknown"


# ---------------------------------------------------------------- Tests: RAM Boundaries


class TestRamCheck:
    # Rule: free RAM >= required x 1.2
    # If minRamMb = 1000, margin requirement is 1200 MB.

    def test_ram_exactly_at_limit(self) -> None:
        m = make_manifest(min_ram_mb=1000)
        d = make_device()
        s = make_stats(mem_free_mb=1200)
        res = check_ram(m, d, s)
        assert res.severity == "pass"
        assert res.code == "ram.sufficient"

    def test_ram_just_above_limit(self) -> None:
        m = make_manifest(min_ram_mb=1000)
        d = make_device()
        s = make_stats(mem_free_mb=1201)
        res = check_ram(m, d, s)
        assert res.severity == "pass"
        assert res.code == "ram.sufficient"

    def test_ram_just_below_limit(self) -> None:
        m = make_manifest(min_ram_mb=1000)
        d = make_device()
        s = make_stats(mem_free_mb=1199)
        res = check_ram(m, d, s)
        assert res.severity == "block"
        assert res.code == "ram.insufficient"

    def test_ram_missing_telemetry(self) -> None:
        m = make_manifest(min_ram_mb=1000)
        d = make_device()
        res = check_ram(m, d, stats=None)
        assert res.severity == "warn"
        assert res.code == "ram.unknown"


# ---------------------------------------------------------------- Tests: CPU Cores Boundaries


class TestCpuCoresCheck:
    # Rule: cpuCores >= minCpuCores

    def test_cores_exactly_at_limit(self) -> None:
        m = make_manifest(min_cpu_cores=4)
        d = make_device(cpu_cores=4)
        res = check_cpu_cores(m, d)
        assert res.severity == "pass"
        assert res.code == "cpu.sufficient"

    def test_cores_just_above_limit(self) -> None:
        m = make_manifest(min_cpu_cores=4)
        d = make_device(cpu_cores=5)
        res = check_cpu_cores(m, d)
        assert res.severity == "pass"
        assert res.code == "cpu.sufficient"

    def test_cores_just_below_limit(self) -> None:
        m = make_manifest(min_cpu_cores=4)
        d = make_device(cpu_cores=3)
        res = check_cpu_cores(m, d)
        assert res.severity == "block"
        assert res.code == "cpu.insufficient"

    def test_cores_missing_data(self) -> None:
        m = make_manifest()
        d = make_device()
        d.cpuCores = None  # type: ignore
        res = check_cpu_cores(m, d)
        assert res.severity == "warn"
        assert res.code == "cpu.unknown"


# ---------------------------------------------------------------- Tests: Disk Boundaries


class TestDiskCheck:
    # Rule: free disk >= snapshot size x 2 + minDiskMb
    # If snapshot_size = 100 MB, minDiskMb = 1000 MB -> limit = 1200 MB.

    def test_disk_exactly_at_limit(self) -> None:
        m = make_manifest(min_disk_mb=1000)
        d = make_device()
        s = make_stats(disk_free_mb=1200)
        res = check_disk(m, d, stats=s, snapshot_size_mb=100.0)
        assert res.severity == "pass"
        assert res.code == "disk.sufficient"

    def test_disk_just_above_limit(self) -> None:
        m = make_manifest(min_disk_mb=1000)
        d = make_device()
        s = make_stats(disk_free_mb=1201)
        res = check_disk(m, d, stats=s, snapshot_size_mb=100.0)
        assert res.severity == "pass"
        assert res.code == "disk.sufficient"

    def test_disk_just_below_limit(self) -> None:
        m = make_manifest(min_disk_mb=1000)
        d = make_device()
        s = make_stats(disk_free_mb=1199)
        res = check_disk(m, d, stats=s, snapshot_size_mb=100.0)
        assert res.severity == "block"
        assert res.code == "disk.insufficient"

    def test_disk_missing_telemetry(self) -> None:
        m = make_manifest(min_disk_mb=1000)
        d = make_device()
        d.diskFreeMb = None  # type: ignore
        res = check_disk(m, d, stats=None)
        assert res.severity == "warn"
        assert res.code == "disk.unknown"


# ---------------------------------------------------------------- Tests: GPU


class TestGpuCheck:
    def test_gpu_not_needed(self) -> None:
        m = make_manifest(needs_gpu=False)
        d = make_device(gpu=None)
        res = check_gpu(m, d)
        assert res.severity == "pass"
        assert res.code == "gpu.ok"

    def test_gpu_needed_and_present(self) -> None:
        m = make_manifest(needs_gpu=True)
        d = make_device(gpu="NVIDIA GeForce RTX 4090")
        res = check_gpu(m, d)
        assert res.severity == "pass"
        assert res.code == "gpu.ok"

    def test_gpu_needed_and_missing(self) -> None:
        m = make_manifest(needs_gpu=True)
        d = make_device(gpu=None)
        res = check_gpu(m, d)
        assert res.severity == "block"
        assert res.code == "gpu.missing"

    def test_gpu_missing_data(self) -> None:
        m = make_manifest()
        m.needsGpu = None  # type: ignore
        d = make_device()
        res = check_gpu(m, d)
        assert res.severity == "warn"
        assert res.code == "gpu.unknown"


# ---------------------------------------------------------------- Tests: Target Battery Boundaries


class TestTargetBatteryCheck:
    # Rule: warn under 30% and not charging, block under 15% not charging

    def test_no_battery_desktop(self) -> None:
        d = make_device()
        s = make_stats(battery_pct=None)
        res = check_target_battery(d, s)
        assert res.severity == "pass"
        assert res.code == "battery.mains"

    def test_battery_charging_at_low_pct(self) -> None:
        d = make_device()
        s = make_stats(battery_pct=10.0, charging=True)
        res = check_target_battery(d, s)
        assert res.severity == "pass"
        assert res.code == "battery.charging"

    def test_boundary_30_percent_exactly(self) -> None:
        d = make_device()
        s = make_stats(battery_pct=30.0, charging=False)
        res = check_target_battery(d, s)
        assert res.severity == "pass"
        assert res.code == "battery.ok"

    def test_boundary_30_percent_just_above(self) -> None:
        d = make_device()
        s = make_stats(battery_pct=30.1, charging=False)
        res = check_target_battery(d, s)
        assert res.severity == "pass"
        assert res.code == "battery.ok"

    def test_boundary_30_percent_just_below(self) -> None:
        d = make_device()
        s = make_stats(battery_pct=29.9, charging=False)
        res = check_target_battery(d, s)
        assert res.severity == "warn"
        assert res.code == "battery.low"

    def test_boundary_15_percent_exactly(self) -> None:
        d = make_device()
        s = make_stats(battery_pct=15.0, charging=False)
        res = check_target_battery(d, s)
        assert res.severity == "warn"
        assert res.code == "battery.low"

    def test_boundary_15_percent_just_above(self) -> None:
        d = make_device()
        s = make_stats(battery_pct=15.1, charging=False)
        res = check_target_battery(d, s)
        assert res.severity == "warn"
        assert res.code == "battery.low"

    def test_boundary_15_percent_just_below(self) -> None:
        d = make_device()
        s = make_stats(battery_pct=14.9, charging=False)
        res = check_target_battery(d, s)
        assert res.severity == "block"
        assert res.code == "battery.critical"

    def test_battery_missing_telemetry(self) -> None:
        d = make_device()
        res = check_target_battery(d, stats=None)
        assert res.severity == "warn"
        assert res.code == "battery.unknown"


# ---------------------------------------------------------------- Tests: Target Online


class TestTargetOnlineCheck:
    def test_online_true(self) -> None:
        d = make_device()
        s = make_stats(online=True)
        res = check_target_online(d, s)
        assert res.severity == "pass"
        assert res.code == "online.ok"

    def test_online_false(self) -> None:
        d = make_device()
        s = make_stats(online=False)
        res = check_target_online(d, s)
        assert res.severity == "block"
        assert res.code == "online.offline"

    def test_online_missing(self) -> None:
        d = make_device()
        res = check_target_online(d, stats=None)
        assert res.severity == "warn"
        assert res.code == "online.unknown"


# ---------------------------------------------------------------- Tests: Link Quality Boundaries


class TestLinkQualityCheck:
    # Rule: warn on high RTT (> 100 ms) or low Mbps (< 10 Mbps), block on high loss (> 5.0%) or no link

    def test_no_link(self) -> None:
        res = check_link_quality(None)
        assert res.severity == "block"
        assert res.code == "link.no_link"

    def test_good_cable_link(self) -> None:
        link = make_link(loss_pct=0.0, rtt_ms=1.0, mbps=1000.0, link_type="cable")
        res = check_link_quality(link)
        assert res.severity == "pass"
        assert res.code == "link.ok"

    def test_loss_boundary_exactly_5_percent(self) -> None:
        link = make_link(loss_pct=5.0, rtt_ms=20.0, mbps=50.0)
        res = check_link_quality(link)
        assert res.severity == "pass"

    def test_loss_boundary_just_above(self) -> None:
        link = make_link(loss_pct=5.1, rtt_ms=20.0, mbps=50.0)
        res = check_link_quality(link)
        assert res.severity == "block"
        assert res.code == "link.high_loss"

    def test_rtt_boundary_exactly_100_ms(self) -> None:
        link = make_link(loss_pct=0.0, rtt_ms=100.0, mbps=50.0)
        res = check_link_quality(link)
        assert res.severity == "pass"

    def test_rtt_boundary_just_above_100_ms(self) -> None:
        link = make_link(loss_pct=0.0, rtt_ms=100.1, mbps=50.0)
        res = check_link_quality(link)
        assert res.severity == "warn"
        assert res.code == "link.degraded"

    def test_bandwidth_boundary_exactly_10_mbps(self) -> None:
        link = make_link(loss_pct=0.0, rtt_ms=20.0, mbps=10.0)
        res = check_link_quality(link)
        assert res.severity == "pass"

    def test_bandwidth_boundary_just_below_10_mbps(self) -> None:
        link = make_link(loss_pct=0.0, rtt_ms=20.0, mbps=9.9)
        res = check_link_quality(link)
        assert res.severity == "warn"
        assert res.code == "link.degraded"

    def test_missing_link_telemetry(self) -> None:
        link = make_link()
        link.lossPct = None  # type: ignore
        res = check_link_quality(link)
        assert res.severity == "warn"
        assert res.code == "link.unknown"


# ---------------------------------------------------------------- Tests: Fixture Combinations Matrix


class TestFixtureCombinationsMatrix:
    @pytest.mark.parametrize("manifest_file", ALL_MANIFEST_FILES)
    @pytest.mark.parametrize("device_file", ALL_DEVICE_FILES)
    def test_all_manifest_and_device_pairs(self, manifest_file: str, device_file: str) -> None:
        manifest = load_manifest(manifest_file)
        device = load_device(device_file)
        # Corresponding stats file
        stats_file = device_file.replace("device_", "stats_")
        stats = load_stats(stats_file)
        link = load_link("link_good_wifi.json")

        reasons = run_all_checks(
            manifest=manifest,
            target=device,
            stats=stats,
            link=link,
            snapshot_size_mb=10.0,
        )

        assert len(reasons) == 11
        for r in reasons:
            assert r.severity in ("pass", "warn", "block")
            assert len(r.code) > 0
            assert len(r.text) > 0

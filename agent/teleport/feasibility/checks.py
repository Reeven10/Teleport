"""Pure feasibility check functions (P3).

Each check function is pure and returns a Reason with a stable code,
a severity ('pass' | 'warn' | 'block'), and a human-readable explanation naming actual values.
Missing data always produces a 'warn' with an 'unknown' code, never raising an exception.
"""

from __future__ import annotations

from contract.contract import (
    DeviceInfo,
    LinkQuality,
    Reason,
    Stats,
    WorkloadManifest,
)


def format_mb(mb: float) -> str:
    """Format megabytes into human-friendly representation (GB or MB)."""
    if mb >= 1000:
        return f"{mb / 1024:.1f} GB"
    return f"{mb:.0f} MB"


def parse_version_tuple(v: str) -> tuple[int, ...]:
    """Parse a semantic or dotted version string into a numeric tuple."""
    clean = str(v).strip().lstrip("v").lstrip("V")
    parts: list[int] = []
    for segment in clean.split("."):
        digits = ""
        for ch in segment:
            if ch.isdigit():
                digits += ch
            else:
                break
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def compare_versions(target_ver: str, min_ver: str) -> bool:
    """Return True if target_ver >= min_ver according to semantic/numeric versioning."""
    try:
        from packaging.version import Version

        return Version(str(target_ver).lstrip("v").lstrip("V")) >= Version(
            str(min_ver).lstrip("v").lstrip("V")
        )
    except Exception:
        pass
    t_tup = parse_version_tuple(target_ver)
    m_tup = parse_version_tuple(min_ver)
    max_len = max(len(t_tup), len(m_tup))
    t_norm = t_tup + (0,) * (max_len - len(t_tup))
    m_norm = m_tup + (0,) * (max_len - len(m_tup))
    return t_norm >= m_norm


# ---------------------------------------------------------------- individual checks


def check_architecture(manifest: WorkloadManifest, target: DeviceInfo) -> Reason:
    """Check whether target architecture is in the workload's supported architecture list."""
    if (
        not hasattr(manifest, "arch")
        or manifest.arch is None
        or not hasattr(target, "arch")
        or target.arch is None
    ):
        return Reason(
            code="arch.unknown",
            severity="warn",
            text="Workload architecture requirement or target architecture is unknown.",
        )

    if target.arch in manifest.arch:
        return Reason(
            code="arch.match",
            severity="pass",
            text=f"Target architecture '{target.arch}' matches supported workload architectures ({', '.join(manifest.arch)}).",
        )
    return Reason(
        code="arch.mismatch",
        severity="block",
        text=f"Target architecture '{target.arch}' does not match supported workload architectures ({', '.join(manifest.arch)}).",
    )


def check_os(manifest: WorkloadManifest, target: DeviceInfo) -> Reason:
    """Check whether target OS is in the workload's supported OS list."""
    if (
        not hasattr(manifest, "os")
        or manifest.os is None
        or not hasattr(target, "os")
        or target.os is None
    ):
        return Reason(
            code="os.unknown",
            severity="warn",
            text="Workload OS requirement or target OS is unknown.",
        )

    if target.os in manifest.os:
        return Reason(
            code="os.match",
            severity="pass",
            text=f"Target OS '{target.os}' matches supported workload operating systems ({', '.join(manifest.os)}).",
        )
    return Reason(
        code="os.mismatch",
        severity="block",
        text=f"Target OS '{target.os}' does not match supported workload operating systems ({', '.join(manifest.os)}).",
    )


def check_runtime(manifest: WorkloadManifest, target: DeviceInfo) -> Reason:
    """Check whether target has required runtime and runtime version >= minVersion."""
    if (
        not hasattr(manifest, "runtime")
        or manifest.runtime is None
        or not getattr(manifest.runtime, "name", None)
        or getattr(manifest.runtime, "minVersion", None) is None
        or not hasattr(target, "runtimes")
        or target.runtimes is None
    ):
        return Reason(
            code="runtime.unknown",
            severity="warn",
            text="Workload runtime specification or target runtimes catalog is unknown.",
        )

    req_name = manifest.runtime.name
    min_ver = str(manifest.runtime.minVersion)

    if req_name not in target.runtimes:
        return Reason(
            code="runtime.missing",
            severity="block",
            text=f"Target is missing required runtime '{req_name}' (workload requires >= {min_ver}).",
        )

    target_ver = str(target.runtimes[req_name])
    if compare_versions(target_ver, min_ver):
        return Reason(
            code="runtime.ok",
            severity="pass",
            text=f"Target runtime '{req_name}' version {target_ver} satisfies requirement (>= {min_ver}).",
        )
    return Reason(
        code="runtime.version_low",
        severity="block",
        text=f"Target runtime '{req_name}' version {target_ver} is lower than required (>= {min_ver}).",
    )


def check_libraries(manifest: WorkloadManifest, target: DeviceInfo) -> Reason:
    """Check whether all required libraries are installed on the target."""
    if (
        not hasattr(manifest, "libs")
        or manifest.libs is None
        or not hasattr(target, "libs")
        or target.libs is None
    ):
        return Reason(
            code="libs.unknown",
            severity="warn",
            text="Workload library requirements or target installed libraries are unknown.",
        )

    if not manifest.libs:
        return Reason(
            code="libs.ok",
            severity="pass",
            text="Workload requires no extra libraries; target library check passed.",
        )

    target_libs_set = set(target.libs)
    missing = [lib for lib in manifest.libs if lib not in target_libs_set]
    if missing:
        return Reason(
            code="libs.missing",
            severity="block",
            text=f"Target is missing required libraries: {', '.join(missing)}.",
        )
    return Reason(
        code="libs.ok",
        severity="pass",
        text=f"All {len(manifest.libs)} required libraries are present on target.",
    )


def check_ram(
    manifest: WorkloadManifest, target: DeviceInfo, stats: Stats | None = None
) -> Reason:
    """Check whether free RAM meets minRamMb with a 1.2x safety margin."""
    if not hasattr(manifest, "minRamMb") or manifest.minRamMb is None:
        return Reason(
            code="ram.unknown",
            severity="warn",
            text="Workload minimum RAM requirement is unknown.",
        )

    needed_mb = manifest.minRamMb
    margin_needed_mb = needed_mb * 1.2

    free_mb: float | None = None
    if stats is not None and hasattr(stats, "memFreeMb") and stats.memFreeMb is not None:
        free_mb = float(stats.memFreeMb)

    if free_mb is None:
        return Reason(
            code="ram.unknown",
            severity="warn",
            text=f"Target free RAM is unknown (telemetry missing); workload needs {format_mb(needed_mb)} (x1.2 safety margin = {format_mb(margin_needed_mb)}).",
        )

    if free_mb >= margin_needed_mb:
        return Reason(
            code="ram.sufficient",
            severity="pass",
            text=f"Target has {format_mb(free_mb)} free RAM, the workload needs {format_mb(needed_mb)} (x1.2 safety margin = {format_mb(margin_needed_mb)}).",
        )
    return Reason(
        code="ram.insufficient",
        severity="block",
        text=f"Target has {format_mb(free_mb)} free RAM, which is below the workload's required {format_mb(needed_mb)} (x1.2 safety margin = {format_mb(margin_needed_mb)}).",
    )


def check_cpu_cores(manifest: WorkloadManifest, target: DeviceInfo) -> Reason:
    """Check whether target CPU cores >= minCpuCores."""
    if (
        not hasattr(manifest, "minCpuCores")
        or manifest.minCpuCores is None
        or not hasattr(target, "cpuCores")
        or target.cpuCores is None
    ):
        return Reason(
            code="cpu.unknown",
            severity="warn",
            text="Workload required CPU cores or target core count is unknown.",
        )

    if target.cpuCores >= manifest.minCpuCores:
        return Reason(
            code="cpu.sufficient",
            severity="pass",
            text=f"Target has {target.cpuCores} CPU cores, workload requires {manifest.minCpuCores} cores.",
        )
    return Reason(
        code="cpu.insufficient",
        severity="block",
        text=f"Target has {target.cpuCores} CPU cores, which is fewer than required {manifest.minCpuCores} cores.",
    )


def check_disk(
    manifest: WorkloadManifest,
    target: DeviceInfo,
    stats: Stats | None = None,
    snapshot_size_mb: float = 0.0,
) -> Reason:
    """Check whether free disk >= snapshot size x 2 + minDiskMb."""
    if not hasattr(manifest, "minDiskMb") or manifest.minDiskMb is None:
        return Reason(
            code="disk.unknown",
            severity="warn",
            text="Workload minimum disk requirement is unknown.",
        )

    needed_base_mb = manifest.minDiskMb
    required_mb = snapshot_size_mb * 2.0 + needed_base_mb

    free_mb: float | None = None
    if stats is not None and hasattr(stats, "diskFreeMb") and stats.diskFreeMb is not None:
        free_mb = float(stats.diskFreeMb)
    elif hasattr(target, "diskFreeMb") and target.diskFreeMb is not None:
        free_mb = float(target.diskFreeMb)

    if free_mb is None:
        return Reason(
            code="disk.unknown",
            severity="warn",
            text=f"Target free disk is unknown (telemetry missing); workload requires {format_mb(required_mb)} (snapshot {format_mb(snapshot_size_mb)} x 2 + {format_mb(needed_base_mb)} required).",
        )

    if free_mb >= required_mb:
        return Reason(
            code="disk.sufficient",
            severity="pass",
            text=f"Target has {format_mb(free_mb)} free disk, workload requires {format_mb(required_mb)} (snapshot {format_mb(snapshot_size_mb)} x 2 + {format_mb(needed_base_mb)} required).",
        )
    return Reason(
        code="disk.insufficient",
        severity="block",
        text=f"Target has {format_mb(free_mb)} free disk, which is below required {format_mb(required_mb)} (snapshot {format_mb(snapshot_size_mb)} x 2 + {format_mb(needed_base_mb)} required).",
    )


def check_gpu(manifest: WorkloadManifest, target: DeviceInfo) -> Reason:
    """Check whether target has a GPU if workload needs one."""
    if not hasattr(manifest, "needsGpu") or manifest.needsGpu is None:
        return Reason(
            code="gpu.unknown",
            severity="warn",
            text="Workload GPU requirement is unknown.",
        )

    if not manifest.needsGpu:
        return Reason(
            code="gpu.ok",
            severity="pass",
            text="Workload does not require GPU acceleration.",
        )

    if hasattr(target, "gpu") and target.gpu:
        return Reason(
            code="gpu.ok",
            severity="pass",
            text=f"Target provides required GPU acceleration ({target.gpu}).",
        )
    return Reason(
        code="gpu.missing",
        severity="block",
        text="Workload requires GPU acceleration, but target has no GPU available.",
    )


def check_target_battery(target: DeviceInfo, stats: Stats | None = None) -> Reason:
    """Check target battery state: warn under 30% and not charging, block under 15% not charging."""
    if stats is None:
        return Reason(
            code="battery.unknown",
            severity="warn",
            text="Target battery state is unknown (telemetry missing).",
        )

    if not hasattr(stats, "battery") or stats.battery is None:
        return Reason(
            code="battery.mains",
            severity="pass",
            text="Target has no battery (connected to AC mains power).",
        )

    battery = stats.battery
    pct = getattr(battery, "pct", None)
    charging = getattr(battery, "charging", False)

    if pct is None:
        return Reason(
            code="battery.unknown",
            severity="warn",
            text="Target battery percentage is unknown.",
        )

    if charging:
        return Reason(
            code="battery.charging",
            severity="pass",
            text=f"Target battery is at {pct:.0f}% and charging.",
        )

    if pct < 15.0:
        return Reason(
            code="battery.critical",
            severity="block",
            text=f"Target battery is critically low at {pct:.0f}% and not charging (minimum 15% required).",
        )
    if pct < 30.0:
        return Reason(
            code="battery.low",
            severity="warn",
            text=f"Target battery is low at {pct:.0f}% and not charging (recommended >= 30%).",
        )
    return Reason(
        code="battery.ok",
        severity="pass",
        text=f"Target battery is healthy at {pct:.0f}%.",
    )


def check_target_online(target: DeviceInfo, stats: Stats | None = None) -> Reason:
    """Check whether target device is currently marked online."""
    if stats is None or not hasattr(stats, "online") or stats.online is None:
        return Reason(
            code="online.unknown",
            severity="warn",
            text="Target online status is unknown (missing stats telemetry).",
        )

    if stats.online:
        return Reason(
            code="online.ok",
            severity="pass",
            text="Target device is online and responsive.",
        )
    return Reason(
        code="online.offline",
        severity="block",
        text="Target device is offline or unresponsive.",
    )


def check_link_quality(link: LinkQuality | None) -> Reason:
    """Check link quality: warn on high RTT or low Mbps, block on high loss or no link."""
    if link is None:
        return Reason(
            code="link.no_link",
            severity="block",
            text="No network link available to target device.",
        )

    loss = getattr(link, "lossPct", None)
    rtt = getattr(link, "rttMs", None)
    mbps = getattr(link, "mbps", None)
    link_type = getattr(link, "link", "unknown")

    if loss is None or rtt is None or mbps is None:
        return Reason(
            code="link.unknown",
            severity="warn",
            text="Link quality telemetry is incomplete or unknown.",
        )

    if loss > 5.0:
        return Reason(
            code="link.high_loss",
            severity="block",
            text=f"Link packet loss is critically high at {loss:.1f}% on {link_type} (threshold 5.0%).",
        )

    if rtt > 100.0 or mbps < 10.0:
        reasons_list = []
        if rtt > 100.0:
            reasons_list.append(f"high RTT ({rtt:.1f} ms > 100 ms)")
        if mbps < 10.0:
            reasons_list.append(f"low throughput ({mbps:.1f} Mbps < 10 Mbps)")
        details = ", ".join(reasons_list)
        return Reason(
            code="link.degraded",
            severity="warn",
            text=f"Link quality is degraded on {link_type}: {details} ({mbps:.1f} Mbps, {rtt:.1f} ms RTT, {loss:.1f}% loss).",
        )

    return Reason(
        code="link.ok",
        severity="pass",
        text=f"Link quality is good on {link_type}: {mbps:.1f} Mbps, {rtt:.1f} ms RTT, {loss:.1f}% loss.",
    )


# ---------------------------------------------------------------- all checks runner


def run_all_checks(
    manifest: WorkloadManifest,
    target: DeviceInfo,
    stats: Stats | None = None,
    link: LinkQuality | None = None,
    snapshot_size_mb: float = 0.0,
) -> list[Reason]:
    """Execute all 11 feasibility checks in standard order and return their reasons."""
    return [
        check_architecture(manifest, target),
        check_os(manifest, target),
        check_runtime(manifest, target),
        check_libraries(manifest, target),
        check_ram(manifest, target, stats=stats),
        check_cpu_cores(manifest, target),
        check_disk(manifest, target, stats=stats, snapshot_size_mb=snapshot_size_mb),
        check_gpu(manifest, target),
        check_target_battery(target, stats=stats),
        check_target_online(target, stats=stats),
        check_link_quality(link),
    ]


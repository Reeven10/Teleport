"""Feasibility evaluation engine and target selection (P3).

Implements decision rules, transfer/interruption estimates, and target ranking
strictly adhering to the Teleport Project Brief.
"""

from __future__ import annotations

import time
from typing import Any

from contract.contract import (
    Decision,
    DeviceInfo,
    FeasibilityResult,
    LinkQuality,
    Reason,
    Stats,
    WorkloadManifest,
)

from .checks import run_all_checks


def calculate_estimates(
    manifest: WorkloadManifest,
    link: LinkQuality | None,
    total_checkpoint_bytes: int | None = None,
    source_stats: Stats | None = None,
) -> tuple[float, float, Reason | None]:
    """Calculate estimated transfer time (seconds) and interruption time (milliseconds).

    Also checks if the estimated transfer time exceeds remaining battery runtime on the source.
    """
    if link is None or getattr(link, "mbps", 0.0) <= 0.0:
        return 0.0, 0.0, None

    # Determine total bytes to transfer
    if total_checkpoint_bytes is not None and total_checkpoint_bytes > 0:
        total_bytes = total_checkpoint_bytes
    else:
        # Default baseline checkpoint footprint: 10 MB or minDiskMb fraction
        min_disk = getattr(manifest, "minDiskMb", 100)
        total_bytes = max(10 * 1024 * 1024, (min_disk * 1024 * 1024) // 4)

    mbps = max(0.1, float(link.mbps))
    rtt_ms = max(0.1, float(link.rttMs))

    # Protocol throughput efficiency: 15% overhead for chunk framing, encryption, and hash tags
    effective_bytes_sec = (mbps * 125_000.0) / 1.15

    # Full transfer time: raw network transmission + TLS/handshake round-trips
    raw_transfer_sec = total_bytes / effective_bytes_sec
    est_transfer_sec = round(raw_transfer_sec + 2.0 * (rtt_ms / 1000.0), 2)

    # Interruption time (fence to target active):
    # Final dirty delta memory pages (~5% of checkpoint set, bounded between 256KB and 4MB)
    final_delta_bytes = max(256 * 1024, min(int(total_bytes * 0.05), 4 * 1024 * 1024))
    delta_transfer_ms = (final_delta_bytes / effective_bytes_sec) * 1000.0

    # Handover round trips (mig.fence -> mig.fenced -> mig.start -> mig.started) + restore overhead
    handover_ms = 3.0 * rtt_ms
    freeze_restore_overhead_ms = 50.0
    est_interruption_ms = round(delta_transfer_ms + handover_ms + freeze_restore_overhead_ms, 1)

    # Source battery depletion check
    battery_warn: Reason | None = None
    if (
        source_stats is not None
        and hasattr(source_stats, "battery")
        and source_stats.battery is not None
        and not getattr(source_stats.battery, "charging", True)
    ):
        pct = float(getattr(source_stats.battery, "pct", 100.0))
        # Estimate ~60 seconds per 1% battery under active workload
        remaining_battery_sec = pct * 60.0
        if est_transfer_sec > remaining_battery_sec:
            battery_warn = Reason(
                code="battery.source_depleting",
                severity="warn",
                text=(
                    f"Estimated transfer time ({est_transfer_sec:.1f}s) may exceed source remaining "
                    f"battery runtime (~{remaining_battery_sec:.0f}s at {pct:.0f}% discharging)."
                ),
            )

    return est_transfer_sec, est_interruption_ms, battery_warn


def evaluate_feasibility(
    manifest: WorkloadManifest,
    source: DeviceInfo,
    target: DeviceInfo,
    link: LinkQuality | None,
    target_stats: Stats | None = None,
    source_stats: Stats | None = None,
    snapshot_size_mb: float = 0.0,
    total_checkpoint_bytes: int | None = None,
) -> FeasibilityResult:
    """Evaluate feasibility of migrating a workload to target according to Project Brief rules.

    Precedence rules:
    1. A block on target online or on the link: STAY.
    2. Any block on arch, os, runtime, libs, ram, cpu, disk or gpu:
       REMOTE_ACCESS if workload is remoteCapable and link can stream (loss <= 5%, >= 2 Mbps, <= 300 ms RTT),
       else STAY.
    3. Only pass and warn: MIGRATE.
    Every check is included in reasons, with one top-level summary Reason stating the decision.
    """
    check_reasons = run_all_checks(
        manifest=manifest,
        target=target,
        stats=target_stats,
        link=link,
        snapshot_size_mb=snapshot_size_mb,
    )

    # Map individual check results by category code prefix
    reason_by_prefix: dict[str, Reason] = {}
    for r in check_reasons:
        prefix = r.code.split(".")[0]
        reason_by_prefix[prefix] = r

    # 1. Target availability and link blocks strictly require STAY
    online_block = reason_by_prefix.get("online", Reason(code="", severity="pass", text="")).severity == "block"
    link_block = reason_by_prefix.get("link", Reason(code="", severity="pass", text="")).severity == "block"

    decision: Decision
    summary_text: str
    summary_code: str
    summary_sev: str

    if online_block or link_block:
        decision = "STAY"
        summary_code = "decision.stay"
        summary_sev = "block"
        if online_block:
            summary_text = (
                f"Workload '{manifest.name}' must stay on source '{source.name}'; "
                f"target device '{target.name}' is offline."
            )
        else:
            summary_text = (
                f"Workload '{manifest.name}' must stay on source '{source.name}'; "
                f"network link to '{target.name}' is unavailable or experiencing severe packet loss."
            )

    else:
        # 2. Check hardware / software compatibility
        compat_prefixes = ["arch", "os", "runtime", "libs", "ram", "cpu", "disk", "gpu", "battery"]
        compat_blocks = [
            r for r in check_reasons
            if r.severity == "block" and any(r.code.startswith(p) for p in compat_prefixes)
        ]

        if compat_blocks:
            # Check remote streaming capability (>= 10 FPS at 720p on LAN)
            remote_capable = bool(getattr(manifest, "remoteCapable", False))
            link_can_stream = (
                link is not None
                and float(getattr(link, "lossPct", 100.0)) <= 5.0
                and float(getattr(link, "mbps", 0.0)) >= 2.0
                and float(getattr(link, "rttMs", 999.0)) <= 300.0
            )

            if remote_capable and link_can_stream:
                decision = "REMOTE_ACCESS"
                summary_code = "decision.remote_access"
                summary_sev = "warn"
                blocked_names = ", ".join(r.code.split(".")[0] for r in compat_blocks)
                summary_text = (
                    f"Direct migration blocked by incompatible resources ({blocked_names}); "
                    f"remote access display streaming is viable for '{manifest.name}' on '{target.name}'."
                )
            else:
                decision = "STAY"
                summary_code = "decision.stay"
                summary_sev = "block"
                if not remote_capable:
                    summary_text = (
                        f"Workload '{manifest.name}' must stay on source '{source.name}'; "
                        f"migration is blocked and workload is not remoteCapable."
                    )
                else:
                    summary_text = (
                        f"Workload '{manifest.name}' must stay on source '{source.name}'; "
                        f"migration is blocked and link to '{target.name}' cannot support remote streaming."
                    )

        else:
            # 3. Only pass and warn -> MIGRATE
            decision = "MIGRATE"
            summary_code = "decision.migrate"
            warnings = [r for r in check_reasons if r.severity == "warn"]
            if warnings:
                summary_sev = "warn"
                summary_text = (
                    f"Workload '{manifest.name}' can be migrated to '{target.name}' "
                    f"with {len(warnings)} warning(s)."
                )
            else:
                summary_sev = "pass"
                summary_text = (
                    f"Workload '{manifest.name}' can be safely migrated to '{target.name}'; "
                    f"all compatibility and resource checks passed."
                )

    # Compute transfer and interruption estimates
    est_transfer_sec, est_interruption_ms, battery_warn = calculate_estimates(
        manifest=manifest,
        link=link,
        total_checkpoint_bytes=total_checkpoint_bytes,
        source_stats=source_stats,
    )

    if decision != "MIGRATE":
        est_transfer_sec = 0.0
        est_interruption_ms = 0.0

    # Build final reasons list with summary reason at index 0
    summary_reason = Reason(code=summary_code, severity=summary_sev, text=summary_text)  # type: ignore
    final_reasons: list[Reason] = [summary_reason] + check_reasons

    if battery_warn is not None:
        final_reasons.append(battery_warn)

    return FeasibilityResult(
        workloadId=manifest.id,
        sourceId=source.id,
        targetId=target.id,
        decision=decision,
        reasons=final_reasons,
        estTransferSec=est_transfer_sec,
        estInterruptionMs=est_interruption_ms,
        ts=time.time(),
    )


def best_target(
    manifest: WorkloadManifest,
    source: DeviceInfo,
    candidates: list[DeviceInfo] | list[tuple[DeviceInfo, Stats | None, LinkQuality | None]],
    candidate_stats: dict[str, Stats] | None = None,
    candidate_links: dict[str, LinkQuality] | None = None,
    source_stats: Stats | None = None,
) -> tuple[DeviceInfo, FeasibilityResult] | None:
    """Rank paired candidate devices and return the best target and its evaluation.

    Ranking precedence:
    1. Decision: MIGRATE > REMOTE_ACCESS > STAY
    2. Fewer warnings: lowest warning count preferred
    3. Spare capacity: available RAM + free disk + CPU cores
    4. Link quality: higher throughput, lower RTT, lowest packet loss
    """
    if not candidates:
        return None

    candidate_tuples: list[tuple[DeviceInfo, Stats | None, LinkQuality | None]] = []
    stats_map = candidate_stats or {}
    links_map = candidate_links or {}

    for item in candidates:
        if isinstance(item, tuple):
            dev, st, lk = item
            candidate_tuples.append((dev, st, lk))
        else:
            dev = item
            st = stats_map.get(dev.id)
            lk = links_map.get(dev.id)
            candidate_tuples.append((dev, st, lk))

    scored_evaluations: list[tuple[tuple[Any, ...], DeviceInfo, FeasibilityResult]] = []

    decision_priority = {
        "MIGRATE": 3,
        "REMOTE_ACCESS": 2,
        "STAY": 1,
    }

    for dev, st, lk in candidate_tuples:
        result = evaluate_feasibility(
            manifest=manifest,
            source=source,
            target=dev,
            link=lk,
            target_stats=st,
            source_stats=source_stats,
        )

        dec_score = decision_priority.get(result.decision, 0)
        warn_count = sum(1 for r in result.reasons if r.severity == "warn")

        # Spare capacity score
        free_ram = st.memFreeMb if (st and st.memFreeMb is not None) else (dev.ramMb or 0)
        free_disk = st.diskFreeMb if (st and st.diskFreeMb is not None) else (dev.diskFreeMb or 0)
        cores = dev.cpuCores or 1
        capacity_score = float(free_ram) + (float(free_disk) / 1024.0) + (cores * 100.0)

        # Link quality score
        if lk is not None:
            link_score = float(lk.mbps) - (float(lk.rttMs) * 0.1) - (float(lk.lossPct) * 10.0)
        else:
            link_score = -1000.0

        # Sort key: higher is better
        # (dec_score: max, -warn_count: max, capacity_score: max, link_score: max)
        sort_key = (dec_score, -warn_count, capacity_score, link_score)
        scored_evaluations.append((sort_key, dev, result))

    scored_evaluations.sort(key=lambda x: x[0], reverse=True)
    best = scored_evaluations[0]
    return best[1], best[2]


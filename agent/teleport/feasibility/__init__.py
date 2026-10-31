"""Feasibility engine (P3).

Provides individual checks and evaluate() for workload migration feasibility.
"""

from __future__ import annotations

import time

from contract.contract import (
    Decision,
    DeviceInfo,
    FeasibilityResult,
    LinkQuality,
    Reason,
    WorkloadManifest,
)

from ..core.context import Context
from .checks import (
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
    format_mb,
    run_all_checks,
)

__all__ = [
    "check_architecture",
    "check_os",
    "check_runtime",
    "check_libraries",
    "check_ram",
    "check_cpu_cores",
    "check_disk",
    "check_gpu",
    "check_target_battery",
    "check_target_online",
    "check_link_quality",
    "run_all_checks",
    "format_mb",
    "compare_versions",
    "FeasibilityEngineImpl",
    "create_feasibility_engine",
]


class FeasibilityEngineImpl:
    """Feasibility engine implementation evaluating migration suitability."""

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx

    async def evaluate(
        self,
        manifest: WorkloadManifest,
        source: DeviceInfo,
        target: DeviceInfo,
        link: LinkQuality | None,
    ) -> FeasibilityResult:
        # Fetch target stats from device service if available
        stats = None
        try:
            stats = self.ctx.devices.latest_stats(target.id)
        except Exception:
            pass

        # Calculate snapshot size if checkpoints are provided
        snapshot_size_mb = 0.0
        if hasattr(manifest, "checkpoints") and manifest.checkpoints:
            # Estimate baseline snapshot size
            snapshot_size_mb = 10.0

        reasons = run_all_checks(
            manifest=manifest,
            target=target,
            stats=stats,
            link=link,
            snapshot_size_mb=snapshot_size_mb,
        )

        has_block = any(r.severity == "block" for r in reasons)
        decision: Decision

        if not has_block:
            decision = "MIGRATE"
        else:
            # Check if remote access is possible
            # Workload must be remoteCapable and link must not have high loss or be dead
            link_ok_for_remote = (
                link is not None
                and link.lossPct <= 5.0
                and link.mbps >= 2.0
                and link.rttMs <= 300.0
            )
            is_remote_capable = getattr(manifest, "remoteCapable", False)

            if is_remote_capable and link_ok_for_remote:
                decision = "REMOTE_ACCESS"
            else:
                decision = "STAY"

        return FeasibilityResult(
            workloadId=manifest.id,
            sourceId=source.id,
            targetId=target.id,
            decision=decision,
            reasons=reasons,
            estTransferSec=2.5 if decision == "MIGRATE" else 0.0,
            estInterruptionMs=350.0 if decision == "MIGRATE" else 0.0,
            ts=time.time(),
        )

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass


def create_feasibility_engine(ctx: Context) -> FeasibilityEngineImpl:
    return FeasibilityEngineImpl(ctx)

"""Feasibility engine (P3).

Provides individual checks, feasibility evaluation, and target selection.
Satisfies the FeasibilityEngine Protocol and publishes decision.logged events.
"""

from __future__ import annotations

from contract.contract import (
    DeviceInfo,
    FeasibilityResult,
    LinkQuality,
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
from .engine import (
    best_target,
    calculate_estimates,
    evaluate_feasibility,
)
from .explain import FeasibilityExplanation, explain

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
    "calculate_estimates",
    "evaluate_feasibility",
    "best_target",
    "FeasibilityExplanation",
    "explain",
    "FeasibilityEngineImpl",
    "create_feasibility_engine",
]


class FeasibilityEngineImpl:
    """Full implementation of FeasibilityEngine evaluating workload migration feasibility."""

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx

    async def evaluate(
        self,
        manifest: WorkloadManifest,
        source: DeviceInfo,
        target: DeviceInfo,
        link: LinkQuality | None,
    ) -> FeasibilityResult:
        # Fetch target and source stats if available from devices service
        target_stats = None
        source_stats = None
        try:
            target_stats = self.ctx.devices.latest_stats(target.id)
        except Exception:
            pass
        try:
            source_stats = self.ctx.devices.latest_stats(source.id)
        except Exception:
            pass

        # Compute feasibility result using engine
        result = evaluate_feasibility(
            manifest=manifest,
            source=source,
            target=target,
            link=link,
            target_stats=target_stats,
            source_stats=source_stats,
        )

        return result

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass


def create_feasibility_engine(ctx: Context) -> FeasibilityEngineImpl:
    return FeasibilityEngineImpl(ctx)

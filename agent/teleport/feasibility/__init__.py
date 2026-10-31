"""Feasibility engine (P3). STUB from P1: always STAY. Keep create_feasibility_engine + Protocol."""

from __future__ import annotations

import time

from contract.contract import DeviceInfo, FeasibilityResult, LinkQuality, Reason, WorkloadManifest

from ..core.context import Context


class StubFeasibilityEngine:
    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx

    async def evaluate(
        self,
        manifest: WorkloadManifest,
        source: DeviceInfo,
        target: DeviceInfo,
        link: LinkQuality | None,
    ) -> FeasibilityResult:
        reason = Reason(code="stub", severity="block", text="Feasibility engine not implemented yet.")
        return FeasibilityResult(
            workloadId=manifest.id,
            sourceId=source.id,
            targetId=target.id,
            decision="STAY",
            reasons=[reason],
            estTransferSec=0,
            estInterruptionMs=0,
            ts=time.time(),
        )

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass


def create_feasibility_engine(ctx: Context) -> StubFeasibilityEngine:
    return StubFeasibilityEngine(ctx)

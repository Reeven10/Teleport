"""Orchestrator (P3). STUB from P1: never recommends. Keep create_orchestrator + Protocol."""

from __future__ import annotations

from contract.contract import Recommendation

from ..core.context import Context


class StubOrchestrator:
    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx

    def recommendations(self) -> list[Recommendation]:
        return []

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass


def create_orchestrator(ctx: Context) -> StubOrchestrator:
    return StubOrchestrator(ctx)

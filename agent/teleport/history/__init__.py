"""History store (P3). STUB from P1: in memory, decisions only. Keep create_history_store + Protocol."""

from __future__ import annotations

from contract.contract import DecisionLog, DecisionLoggedEvent, DeviceInfo, MigrationStatus

from ..core.context import Context


class StubHistoryStore:
    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self._decisions: list[DecisionLog] = []

    async def log_decision(self, log: DecisionLog) -> None:
        self._decisions.append(log)
        await self.ctx.bus.publish(DecisionLoggedEvent(log=log))

    async def list_devices(self) -> list[DeviceInfo]:
        return []

    async def list_migrations(self) -> list[MigrationStatus]:
        return []

    async def list_decisions(self) -> list[DecisionLog]:
        return list(self._decisions)

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass


def create_history_store(ctx: Context) -> StubHistoryStore:
    return StubHistoryStore(ctx)

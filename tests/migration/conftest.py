from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Coroutine
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import pytest

from contract.contract import (
    CheckpointDef,
    MigrationStatus,
    MigrationStatusEvent,
    RuntimeReq,
    WorkloadManifest,
)
from teleport.core import Context, Settings, build_context
from teleport.migration import MigrationManager, Timeouts
from tests.migration.mocks import (
    FakeWorkloadHost,
    MockFeasibility,
    MockPeerLink,
    MockRemote,
    World,
    link_pair,
)

FAST = Timeouts(ready=2, ack=0.3, validate=3, checkpoint=2, start=3, retries=2, window=4)


def make_manifest(n_checkpoints: int = 6, wid: str = "demo") -> WorkloadManifest:
    ids = ["counter", *[f"c{i}" for i in range(1, n_checkpoints)]]
    return WorkloadManifest(
        id=wid,
        name="Demo",
        command="python job.py",
        runtime=RuntimeReq(name="python", minVersion="3.11"),
        arch=["x86_64", "arm64"],
        os=["linux", "windows", "macos"],
        minRamMb=10,
        minCpuCores=1,
        minDiskMb=1,
        needsGpu=False,
        libs=[],
        checkpoints=[CheckpointDef(id=i, name=i, paths=[]) for i in ids],
        remoteCapable=True,
    )


@dataclass
class Side:
    ctx: Context
    link: MockPeerLink
    host: FakeWorkloadHost
    feasibility: MockFeasibility
    remote: MockRemote
    home: Path
    phases: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return self.ctx.device_id

    @property
    def manager(self) -> MigrationManager:
        return cast(MigrationManager, self.ctx.migration)


@dataclass
class Pair:
    a: Side
    b: Side
    world: World
    manifest: WorkloadManifest
    started: list[Context]

    @property
    def wid(self) -> str:
        return self.manifest.id

    async def migrate(self) -> MigrationStatus:
        st = await self.a.manager.start(self.wid, self.b.id, "user_command")
        return await self.a.manager.wait(st.id, timeout=20)

    def other(self, side: Side) -> Side:
        return self.b if side is self.a else self.a

    def crash(self, side: Side) -> None:
        """The agent process dies: no cleanup, its link drops, its workload processes are orphaned."""
        manager = side.manager
        for unsub in manager._unsubscribe:
            unsub()
        for task in manager._tasks:
            task.cancel()
        for run in manager._sources.values():
            if run.task and not run.task.done():
                run.task.cancel()
        side.host.dead = True
        side.link.cut()
        if side.link._pump:
            side.link._pump.cancel()

    async def restart(self, side: Side) -> Side:
        """Start a new agent on the crashed side's TELEPORT_HOME and reconnect it to the other side."""
        fresh = _side(side.home, self.world)
        fresh.link = self.other(side).link.reconnect(fresh.ctx)
        fresh.ctx.register("peers", fresh.link)
        await _boot(fresh)
        self.started.append(fresh.ctx)
        if side is self.a:
            self.a = fresh
        else:
            self.b = fresh
        return fresh


def _side(home: Path, world: World) -> Side:
    ctx = build_context(Settings(home=home, port=1, uiDist=home / "no-ui"))
    host, feas, remote = FakeWorkloadHost(ctx, world), MockFeasibility(), MockRemote(ctx)
    ctx.register("workloads", host)
    ctx.register("feasibility", feas)
    ctx.register("remote", remote)
    cast(MigrationManager, ctx.migration).timeouts = FAST
    ctx.prefs = ctx.prefs.model_copy(update={"leaseSyncS": 0.1})
    return Side(ctx=ctx, link=cast(MockPeerLink, None), host=host, feasibility=feas, remote=remote, home=home)


async def _boot(side: Side) -> None:
    async def record(e: MigrationStatusEvent, phases: list[str] = side.phases) -> None:
        if not phases or phases[-1] != e.status.phase:
            phases.append(e.status.phase)

    side.ctx.bus.subscribe(MigrationStatusEvent, record)
    for _, service in side.ctx.services():
        await service.startup()


PairFactory = Callable[..., Coroutine[Any, Any, Pair]]


@pytest.fixture
async def make_pair(tmp_path: Path) -> AsyncIterator[PairFactory]:
    started: list[Context] = []

    async def factory(n_checkpoints: int = 6, run_source: bool = True) -> Pair:
        world = World()
        a, b = _side(tmp_path / "a", world), _side(tmp_path / "b", world)
        a.link, b.link = link_pair(a.ctx, b.ctx)
        a.ctx.register("peers", a.link)
        b.ctx.register("peers", b.link)
        manifest = make_manifest(n_checkpoints)
        src = tmp_path / "src"
        src.mkdir(exist_ok=True)
        (src / "job.py").write_text("print('hello')\n")
        for side in (a, b):
            await _boot(side)
            started.append(side.ctx)
        if run_source:
            a.host.register(manifest, src)
            await a.ctx.authority.claim(manifest.id, a.id)
            await a.host.start(manifest.id, restore=False)
            a.host.tick(manifest.id, 41)
        return Pair(a=a, b=b, world=world, manifest=manifest, started=started)

    yield factory
    for ctx in started:
        for _, service in reversed(ctx.services()):
            try:
                await service.shutdown()
            except Exception:  # a crashed agent's services may already be half gone
                pass

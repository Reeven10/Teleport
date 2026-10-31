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

    @property
    def wid(self) -> str:
        return self.manifest.id

    async def migrate(self) -> MigrationStatus:
        st = await self.a.manager.start(self.wid, self.b.id, "user_command")
        return await self.a.manager.wait(st.id, timeout=20)


def _side(home: Path, world: World) -> Side:
    ctx = build_context(Settings(home=home, port=1, uiDist=home / "no-ui"))
    host, feas, remote = FakeWorkloadHost(ctx, world), MockFeasibility(), MockRemote(ctx)
    ctx.register("workloads", host)
    ctx.register("feasibility", feas)
    ctx.register("remote", remote)
    cast(MigrationManager, ctx.migration).timeouts = FAST
    return Side(ctx=ctx, link=cast(MockPeerLink, None), host=host, feasibility=feas, remote=remote)


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
            for _, service in side.ctx.services():
                await service.startup()
            started.append(side.ctx)

            async def record(e: MigrationStatusEvent, phases: list[str] = side.phases) -> None:
                if not phases or phases[-1] != e.status.phase:
                    phases.append(e.status.phase)

            side.ctx.bus.subscribe(MigrationStatusEvent, record)
        if run_source:
            a.host.register(manifest, src)
            await a.ctx.authority.claim(manifest.id, a.id)
            await a.host.start(manifest.id, restore=False)
            a.host.tick(manifest.id, 41)
        return Pair(a=a, b=b, world=world, manifest=manifest)

    yield factory
    for ctx in started:
        for _, service in reversed(ctx.services()):
            await service.shutdown()

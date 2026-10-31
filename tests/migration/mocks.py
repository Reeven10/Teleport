"""Test doubles for migration: in-memory PeerLink pair with fault injection, feasibility, remote
service, and a fake workload host that tracks how many copies of a workload run at once."""

from __future__ import annotations

import asyncio
import base64
import builtins
import contextlib
import json
import random
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from starlette.websockets import WebSocket
from teleport_sdk.unit import decode_state, pack_unit, unpack_unit

from contract.contract import (
    CheckpointRecord,
    Decision,
    DeviceInfo,
    DeviceLostEvent,
    FeasibilityResult,
    LinkQuality,
    MigChunk,
    PeerMessage,
    PeerMessageAdapter,
    PeerMessageHandler,
    Reason,
    RemoteSession,
    RunState,
    WorkloadManifest,
    WorkloadRun,
)
from teleport.core import Context
from teleport.migration.store import CheckpointStore

# ---------------------------------------------------------------- peer link


@dataclass
class Faults:
    """Applied on send. Predicates get the decoded message as the receiver would see it."""

    drop: Callable[[PeerMessage], bool] | None = None
    corrupt: Callable[[MigChunk], bool] | None = None
    delay: float = 0.0
    on_send: Callable[[PeerMessage], None] | None = None


class MockPeerLink:
    """One end of an in-memory link. Messages round-trip through JSON like the real wire."""

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self.other: MockPeerLink | None = None
        self.faults = Faults()
        self.sent: list[PeerMessage] = []
        self.is_cut = False
        self._handlers: list[PeerMessageHandler] = []
        self._inbox: asyncio.Queue[tuple[str, PeerMessage]] = asyncio.Queue()
        self._pump: asyncio.Task[None] | None = None

    @property
    def peer(self) -> MockPeerLink:
        assert self.other is not None
        return self.other

    async def pair(self, addr: str, pin: str) -> DeviceInfo:
        return self.peer.ctx.devices.local_info()

    async def connect(self, device_id: str) -> None:
        if self.is_cut or device_id != self.peer.ctx.device_id:
            raise ConnectionError(f"cannot reach {device_id}")

    async def send(self, device_id: str, msg: PeerMessage) -> None:
        if self.is_cut:
            raise ConnectionError("link cut")
        if device_id != self.peer.ctx.device_id:
            raise ConnectionError(f"unknown peer {device_id}")
        decoded = PeerMessageAdapter.validate_json(msg.model_dump_json())
        self.sent.append(decoded)
        if self.faults.on_send:
            self.faults.on_send(decoded)
            if self.is_cut:
                raise ConnectionError("link cut")
        if self.faults.drop and self.faults.drop(decoded):
            return
        if isinstance(decoded, MigChunk) and self.faults.corrupt and self.faults.corrupt(decoded):
            data = bytearray(base64.b64decode(decoded.dataB64))
            data[len(data) // 2] ^= 0xFF
            decoded = decoded.model_copy(update={"dataB64": base64.b64encode(bytes(data)).decode()})
        self.peer._inbox.put_nowait((self.ctx.device_id, decoded))

    def on_message(self, handler: PeerMessageHandler) -> None:
        self._handlers.append(handler)

    def link_quality(self, device_id: str) -> LinkQuality | None:
        if self.is_cut:
            return None
        return LinkQuality(peerId=device_id, link="cable", rttMs=1, mbps=1000, lossPct=0, ts=time.time())

    def list_peers(self) -> list[DeviceInfo]:
        return [self.peer.ctx.devices.local_info()]

    def cut(self) -> None:
        """Cut both directions now; both sides get device.lost."""
        for end in (self, self.peer):
            end.is_cut = True
            lost = DeviceLostEvent(deviceId=end.peer.ctx.device_id)
            asyncio.get_running_loop().create_task(end.ctx.bus.publish(lost))

    def reconnect(self, ctx: Context) -> MockPeerLink:
        """The agent behind the other end restarted with `ctx`: a fresh end, attached to this one."""
        fresh = MockPeerLink(ctx)
        fresh.other, self.other = self, fresh
        self.is_cut = False
        return fresh

    def cut_after(self, n: int, kind: type = MigChunk) -> None:
        """Cut the link when the n-th message of `kind` is sent."""
        count = 0

        def hook(msg: PeerMessage) -> None:
            nonlocal count
            if isinstance(msg, kind):
                count += 1
                if count == n:
                    self.cut()

        self.faults.on_send = hook

    async def _run_pump(self) -> None:
        while True:
            src, msg = await self._inbox.get()
            if self.peer.faults.delay:
                await asyncio.sleep(self.peer.faults.delay)
            if self.is_cut:
                continue
            for h in list(self._handlers):
                await h(src, msg)

    async def startup(self) -> None:
        self._pump = asyncio.create_task(self._run_pump())

    async def shutdown(self) -> None:
        if self._pump:
            self._pump.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._pump


def link_pair(a: Context, b: Context) -> tuple[MockPeerLink, MockPeerLink]:
    la, lb = MockPeerLink(a), MockPeerLink(b)
    la.other, lb.other = lb, la
    return la, lb


# ---------------------------------------------------------------- feasibility and remote


class MockFeasibility:
    def __init__(self, decision: Decision = "MIGRATE") -> None:
        self.decision: Decision = decision
        self.calls = 0

    async def evaluate(
        self, manifest: WorkloadManifest, source: DeviceInfo, target: DeviceInfo, link: LinkQuality | None
    ) -> FeasibilityResult:
        self.calls += 1
        severity: Literal["pass", "block"] = "pass" if self.decision == "MIGRATE" else "block"
        reasons = [Reason(code="mock", severity=severity, text=f"Mock decided {self.decision}.")]
        return FeasibilityResult(
            workloadId=manifest.id,
            sourceId=source.id,
            targetId=target.id,
            decision=self.decision,
            reasons=reasons,
            estTransferSec=0.1,
            estInterruptionMs=50,
            ts=time.time(),
        )

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass


class MockRemote:
    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self._sessions: list[RemoteSession] = []

    async def start_session(self, workload_id: str, viewer_id: str) -> RemoteSession:
        s = RemoteSession(
            id=f"rs-{uuid.uuid4().hex[:8]}",
            workloadId=workload_id,
            hostId=self.ctx.device_id,
            viewerId=viewer_id,
            consent=True,
            fps=0,
            ts=time.time(),
        )
        self._sessions.append(s)
        return s

    async def handle_viewer(self, websocket: WebSocket, session_id: str) -> None:
        await websocket.close()

    def sessions(self) -> list[RemoteSession]:
        return list(self._sessions)

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass


# ---------------------------------------------------------------- workload host


@dataclass
class World:
    """Shared by every FakeWorkloadHost in a test: who is running what, and the worst case seen."""

    running: dict[str, set[str]] = field(default_factory=dict)
    max_running: dict[str, int] = field(default_factory=dict)
    started_on: list[tuple[str, str]] = field(default_factory=list)

    def set(self, workload_id: str, device_id: str, running: bool) -> None:
        devices = self.running.setdefault(workload_id, set())
        (devices.add if running else devices.discard)(device_id)
        self.max_running[workload_id] = max(self.max_running.get(workload_id, 0), len(devices))


class FakeWorkloadHost:
    """Stands in for WorkloadRunner. State: `counter` advances on tick(); other checkpoints are static.

    Like the real runner it persists its registry and which workloads run (fake_host.json), so a
    host built on the same TELEPORT_HOME after a "crash" knows them and kills the orphans.
    """

    def __init__(self, ctx: Context, world: World) -> None:
        self.ctx = ctx
        self.world = world
        self.store = CheckpointStore(ctx.settings.home)
        self.manifests: dict[str, WorkloadManifest] = {}
        self.sources: dict[str, Path] = {}
        self.states: dict[str, RunState] = {}
        self.counts: dict[str, int] = {}
        self.restored_count: dict[str, int] = {}
        self.fail_start = False
        self.start_delay = 0.0
        self.blobs: dict[str, int] = {}  # checkpoint id -> size of a deterministic binary state
        self.dead = False
        self._file = ctx.settings.home / "fake_host.json"
        self._interrupted: set[str] = set()
        if self._file.exists():
            saved = json.loads(self._file.read_text())
            for wid, m in saved["manifests"].items():
                self.manifests[wid] = WorkloadManifest.model_validate(m)
                self.sources[wid] = Path(saved["sources"][wid])
                self.states[wid] = "idle"
            self._interrupted = set(saved["running"])

    def _save(self) -> None:
        self._file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "manifests": {w: m.model_dump() for w, m in self.manifests.items()},
            "sources": {w: str(p) for w, p in self.sources.items()},
            "running": sorted(w for w, s in self.states.items() if s in ("running", "paused")),
        }
        self._file.write_text(json.dumps(data))

    def _set(self, wid: str, state: RunState) -> None:
        assert not self.dead, "a crashed agent's host must not act"
        self.states[wid] = state
        self.world.set(wid, self.ctx.device_id, state == "running")
        self._save()

    def interrupted(self) -> set[str]:
        return set(self._interrupted)

    def tick(self, wid: str, n: int = 1) -> None:
        assert self.states.get(wid) == "running", "a paused or stopped copy must not make progress"
        self.counts[wid] = self.counts.get(wid, 0) + n

    def manifest(self, workload_id: str) -> WorkloadManifest:
        return self.manifests[workload_id]

    def source_dir(self, workload_id: str) -> Path:
        return self.sources[workload_id]

    def register(self, manifest: WorkloadManifest, source_dir: Path) -> None:
        self.manifests[manifest.id] = manifest
        self.sources[manifest.id] = source_dir
        self.states.setdefault(manifest.id, "idle")
        self._save()

    def status(self, workload_id: str) -> WorkloadRun:
        if workload_id not in self.manifests:
            raise KeyError(workload_id)
        return WorkloadRun(
            workloadId=workload_id,
            state=self.states[workload_id],
            pid=None,
            exitCode=None,
            startedAt=None,
            restored=[],
            logTail=[],
        )

    async def start(self, workload_id: str, restore: bool = True) -> WorkloadRun:
        if self.start_delay:
            await asyncio.sleep(self.start_delay)
        if self.fail_start:
            raise RuntimeError("simulated start failure")
        count = 0
        if restore and (data := self.store.read(workload_id, "counter")) is not None:
            state = decode_state(*unpack_unit(data))
            assert isinstance(state, dict)
            count = int(state["count"])
            self.restored_count[workload_id] = count
        self.counts[workload_id] = count
        self._set(workload_id, "running")
        self.world.started_on.append((self.ctx.device_id, workload_id))
        return self.status(workload_id)

    def pause(self, workload_id: str) -> WorkloadRun:
        assert self.states[workload_id] == "running"
        self._set(workload_id, "paused")
        return self.status(workload_id)

    def resume(self, workload_id: str) -> WorkloadRun:
        assert self.states[workload_id] == "paused"
        self._set(workload_id, "running")
        return self.status(workload_id)

    async def request_checkpoint(
        self, workload_id: str, timeout: float = 10.0
    ) -> builtins.list[CheckpointRecord]:
        if self.states.get(workload_id) == "running":  # the SDK only answers while running
            for ck in self.manifests[workload_id].checkpoints:
                state: dict[str, object] | bytes = {"id": ck.id, "static": True}
                if ck.id == "counter":
                    state = {"count": self.counts.get(workload_id, 0)}
                elif ck.id in self.blobs:
                    state = random.Random(ck.id).randbytes(self.blobs[ck.id])
                self.store.put(workload_id, ck.id, pack_unit(state))
        return self.store.records(workload_id)

    async def kill(self, workload_id: str) -> WorkloadRun:
        self._set(workload_id, "stopped")
        return self.status(workload_id)

    async def launch(self, manifest_path: str) -> WorkloadManifest:
        raise NotImplementedError

    def list(self) -> builtins.list[WorkloadManifest]:
        return builtins.list(self.manifests.values())

    async def startup(self) -> None:
        for wid in self._interrupted:  # the previous agent's processes do not survive the restart
            self.world.set(wid, self.ctx.device_id, False)

    async def shutdown(self) -> None:
        pass

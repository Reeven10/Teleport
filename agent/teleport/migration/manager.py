"""Migration manager (P1): source and target sides of checkpointed migration, with rollback,
restart recovery, a split-brain guard, delta transfer, pre-copy and metrics.

Source: CONNECTING -> EVALUATING -> (MIGRATE) TRANSFERRING -> VALIDATING -> FENCING ->
STARTING_TARGET -> COMPLETED, or REMOTE_ACCESS, or FAILED (STAY / nothing sent yet), or
ROLLING_BACK -> ROLLED_BACK on any failure, timeout, abort or lost link before mig.started ok.
Authority only moves after every checkpoint is validated and the target confirmed it started.

Continuity: every status change is journaled (journal.py). After a restart, an unfinished
migration is resolved without ever running two copies: before mig.start the source rolls back and
resumes; once authority moved the old source stays stopped; if mig.start was out but its answer
never came back, the side that restarted waits for the peer's lease (auth.leases) to decide.

The workload folder travels as the system unit `teleport.code`. Units the target already holds
with the same SHA-256 (from an earlier run, migration or pre-copy) are not sent again.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import builtins
import contextlib
import errno
import json
import logging
import os
import shutil
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

from teleport_sdk.unit import collect_files, pack_unit, unpack_unit

from contract.contract import (
    AuthLeases,
    Authority,
    AuthorityConflict,
    AuthorityConflictEvent,
    CheckpointMetric,
    CheckpointRecord,
    CutoverTiming,
    DecisionLog,
    DeviceInfo,
    DeviceLostEvent,
    LinkUpdateEvent,
    MigAbort,
    MigChunk,
    MigChunkAck,
    MigFence,
    MigFenced,
    MigPrepare,
    MigrationMetrics,
    MigrationStatus,
    MigrationStatusEvent,
    MigReady,
    MigStart,
    MigStarted,
    MigValidated,
    PeerMessage,
    Phase,
    Reason,
    Trigger,
    WorkloadManifest,
    WorkloadRun,
)

from ..authority import resolve
from ..core.context import Context
from .journal import JournalEntry, MigrationJournal
from .store import CHUNK_SIZE, CheckpointStore, ChunkError, Reassembler, iter_chunks, sha256_hex

log = logging.getLogger("teleport.migration")

CODE_UNIT = "teleport.code"
CODE_EXCLUDE = (".teleport-local", "__pycache__", "*.pyc", ".git", "node_modules", ".venv")
TERMINAL: set[Phase] = {"COMPLETED", "ROLLED_BACK", "REMOTE_ACCESS", "FAILED"}
Stage = Literal["initial", "catchup", "delta", "precopy"]


class MigrationError(RuntimeError):
    """A failure with a short message for the dashboard; `detail` keeps the technical part."""

    def __init__(self, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.detail = detail


class MigrationAborted(MigrationError):
    pass


@runtime_checkable
class WorkloadHost(Protocol):
    """What migration needs from the workload runner (ctx.workloads); faked in tests."""

    store: CheckpointStore

    def manifest(self, workload_id: str) -> WorkloadManifest: ...
    def source_dir(self, workload_id: str) -> Path: ...
    def register(self, manifest: WorkloadManifest, source_dir: Path) -> None: ...
    def status(self, workload_id: str) -> WorkloadRun: ...
    def interrupted(self) -> set[str]:
        """Workloads that were running when the previous agent process stopped."""
        ...

    async def start(self, workload_id: str, restore: bool = True) -> WorkloadRun: ...
    def pause(self, workload_id: str) -> WorkloadRun: ...
    def resume(self, workload_id: str) -> WorkloadRun: ...
    async def request_checkpoint(
        self, workload_id: str, timeout: float = 10.0
    ) -> builtins.list[CheckpointRecord]: ...
    async def kill(self, workload_id: str) -> WorkloadRun: ...
    async def launch(self, manifest_path: str) -> WorkloadManifest: ...
    def list(self) -> builtins.list[WorkloadManifest]: ...


@runtime_checkable
class ManifestSigner(Protocol):
    """Signs mig.prepare with the device identity key. The peer link should implement it (P2)."""

    def sign_manifest(self, payload: bytes) -> str: ...
    def verify_manifest(self, device_id: str, payload: bytes, signature: str) -> bool: ...


class DigestSigner:
    """Fallback until the peer link signs: SHA-256 digest, i.e. integrity only, NOT authenticity."""

    def sign_manifest(self, payload: bytes) -> str:
        return "sha256:" + sha256_hex(payload)

    def verify_manifest(self, device_id: str, payload: bytes, signature: str) -> bool:
        return signature == self.sign_manifest(payload)


@dataclass
class Timeouts:
    ready: float = 10.0
    ack: float = 20.0  # a chunk can queue behind a full window on slow wifi; resending early only adds load
    validate: float = 30.0
    checkpoint: float = 10.0
    start: float = 30.0
    retries: int = 3
    window: int = 4  # chunks in flight: ~2 MB on the wire, enough for wifi without flooding a hotspot
    chunk_delay: float = 0.0  # dev/demo slow motion, TELEPORT_DEV_SLOW_TRANSFER_MS
    catchup_rounds: int = 3  # live delta rounds before freezing, to keep the freeze window small
    catchup_bytes: int = 64 * 1024  # freeze once a round has less than this left to send
    relink: float = 5.0  # after device.lost, how long to try reconnecting before giving up

    @classmethod
    def from_env(cls) -> Timeouts:
        return cls(chunk_delay=float(os.environ.get("TELEPORT_DEV_SLOW_TRANSFER_MS") or 0) / 1000)


def prepare_payload(
    migration_id: str, manifest: WorkloadManifest, records: list[CheckpointRecord], epoch: int
) -> bytes:
    body = {
        "migrationId": migration_id,
        "manifest": manifest.model_dump(),
        "checkpoints": [r.model_dump() for r in records],
        "epoch": epoch,
    }
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode()


Key = tuple[str, ...]


class _Mailbox:
    """Replies for one source migration, matched by key; fail() wakes every waiter with an error."""

    def __init__(self) -> None:
        self._early: dict[Key, PeerMessage] = {}
        self._waiters: dict[Key, asyncio.Future[PeerMessage]] = {}
        self._error: BaseException | None = None

    def deliver(self, key: Key, msg: PeerMessage) -> None:
        fut = self._waiters.pop(key, None)
        if fut is not None and not fut.done():
            fut.set_result(msg)
        else:
            self._early[key] = msg

    def discard(self, key: Key) -> None:
        self._early.pop(key, None)

    async def expect(self, key: Key, timeout: float) -> PeerMessage:
        if self._error is not None:
            raise self._error
        if key in self._early:
            return self._early.pop(key)
        fut: asyncio.Future[PeerMessage] = asyncio.get_running_loop().create_future()
        self._waiters[key] = fut
        try:
            return await asyncio.wait_for(fut, timeout)
        finally:
            self._waiters.pop(key, None)

    def fail(self, exc: BaseException) -> None:
        self._error = exc
        for fut in self._waiters.values():
            if not fut.done():
                fut.set_exception(exc)
        self._waiters.clear()


@dataclass
class _SourceRun:
    status: MigrationStatus
    outgoing: Path
    chunk_size: int = CHUNK_SIZE
    precopy: bool = False  # internal pre-copy run: not listed, not journaled
    mailbox: _Mailbox = field(default_factory=_Mailbox)
    task: asyncio.Task[None] | None = None
    abort_reason: str | None = None
    prepared: bool = False
    start_sent: bool = False
    late_abort: str | None = None
    committed: bool = False
    fence_epoch: int | None = None
    awaiting: bool = False  # mig.start went out, answer unknown: waiting for the target's lease
    target_refused: bool = False  # the target answered mig.started ok=false
    sent: dict[str, CheckpointRecord] = field(default_factory=dict)
    metrics: list[CheckpointMetric] = field(default_factory=list)
    bytes_skipped: int = 0
    last_publish: float = 0.0
    catchup_rounds: int = 0
    fence_ms: float | None = None
    delta_bytes: int = 0
    delta_ms: float | None = None
    start_ms: float | None = None


@dataclass
class _TargetRun:
    status: MigrationStatus
    manifest: WorkloadManifest
    source_id: str
    prepare_epoch: int
    epoch: int
    staging: Path
    records: dict[str, CheckpointRecord]
    parts: dict[str, Reassembler]
    chunk_size: int = CHUNK_SIZE
    precopy: bool = False
    validated: set[str] = field(default_factory=set)
    failed: set[str] = field(default_factory=set)
    owes_validation: bool = True
    started: bool = False
    awaiting: bool = False  # restarted after taking authority: waiting for the source's lease


class MigrationManager:
    def __init__(self, ctx: Context, timeouts: Timeouts | None = None) -> None:
        self.ctx = ctx
        self.timeouts = timeouts or Timeouts.from_env()
        self.journal = MigrationJournal(ctx.settings.home)
        self._sources: dict[str, _SourceRun] = {}
        self._targets: dict[str, _TargetRun] = {}
        self._archived: dict[str, MigrationStatus] = {}  # finished before this agent started
        self._hold: set[str] = set()  # workloads that must not be relaunched until resolved
        self._resume: set[str] = set()  # rolled back during recovery: start again
        self._linked: set[str] = set()
        self._reported: set[tuple[str, str, int]] = set()  # (workload, stopped device, epoch)
        self._recent_conflicts: list[AuthorityConflict] = []
        self._target_lock = asyncio.Lock()
        self._lease_lock = asyncio.Lock()
        self._unsubscribe: list[Callable[[], None]] = []
        self._tasks: list[asyncio.Task[None]] = []

    # ------------------------------------------------------------------ wiring

    @property
    def host(self) -> WorkloadHost:
        return self.ctx.workloads

    @property
    def store(self) -> CheckpointStore:
        return self.host.store

    @property
    def signer(self) -> ManifestSigner:
        peers = self.ctx.peers
        return peers if isinstance(peers, ManifestSigner) else _DIGEST

    def cache_dir(self, workload_id: str) -> Path:
        """Units received by pre-copy, and code units seen before: reused instead of re-sent."""
        return self.store.workload_dir(workload_id) / "cache"

    async def startup(self) -> None:
        self.ctx.peers.on_message(self._on_peer_message)
        self._unsubscribe = [
            self.ctx.bus.subscribe(DeviceLostEvent, self._on_device_lost),
            self.ctx.bus.subscribe(LinkUpdateEvent, self._on_link_update),
        ]
        await self._recover()
        await self._relaunch(self.host.interrupted() | self._resume)
        self._tasks = [asyncio.create_task(self._lease_loop()), asyncio.create_task(self._precopy_loop())]

    async def shutdown(self) -> None:
        for unsub in self._unsubscribe:
            unsub()
        for task in self._tasks:
            task.cancel()
        for run in self._sources.values():
            if run.task and not run.task.done():
                self._abort_source(run, "This agent is shutting down.")
        tasks = [r.task for r in self._sources.values() if r.task and not r.task.done()]
        if tasks:
            await asyncio.wait(tasks, timeout=10)

    # ------------------------------------------------------------------ MigrationManager Protocol

    def workloads(self) -> builtins.list[WorkloadManifest]:
        return self.host.list()

    async def launch_workload(self, manifest_path: str) -> WorkloadManifest:
        return await self.host.launch(manifest_path)

    def _active(self, workload_id: str) -> _SourceRun | None:
        for r in self._sources.values():
            if r.status.workloadId == workload_id and r.status.phase not in TERMINAL:
                return r
        return None

    def _new_status(self, mid: str, workload_id: str, target_id: str, trigger: Trigger) -> MigrationStatus:
        return MigrationStatus(
            id=mid,
            workloadId=workload_id,
            sourceId=self.ctx.device_id,
            targetId=target_id,
            phase="IDLE",
            trigger=trigger,
            link="wifi",
            reasons=[],
            checkpoints=[],
            bytesTotal=0,
            bytesDone=0,
            authority=self.ctx.authority.get(workload_id),
            startedAt=time.time(),
        )

    async def start(self, workload_id: str, target_id: str, trigger: Trigger) -> MigrationStatus:
        if target_id == self.ctx.device_id:
            raise MigrationError("target is this device")
        self.host.manifest(workload_id)  # KeyError if unknown
        if active := self._active(workload_id):
            kind = "pre-copying" if active.precopy else "migrating"
            raise MigrationError(f"{workload_id} is already {kind} ({active.status.id})")
        mid = f"mig-{uuid.uuid4().hex[:12]}"
        status = self._new_status(mid, workload_id, target_id, trigger)
        run = _SourceRun(
            status=status,
            outgoing=self.store.workload_dir(workload_id) / "outgoing" / mid,
            chunk_size=self.ctx.prefs.chunkSizeKb * 1024,
        )
        self._sources[mid] = run
        run.task = asyncio.create_task(self._run_source(run), name=mid)
        return status.model_copy(deep=True)

    async def abort(self, migration_id: str) -> MigrationStatus:
        if src := self._sources.get(migration_id):
            if src.awaiting:
                # Operator override for a migration interrupted by a restart: resume here. If the
                # target did start, the split-brain guard stops it (its epoch is now older).
                src.awaiting = False
                await self._rollback(src, "Aborted by user while waiting for the target; resuming here.")
                await self._relaunch({src.status.workloadId})
            elif src.status.phase not in TERMINAL and not src.committed:
                self._abort_source(src, "Aborted by user.")
                if src.task:
                    await asyncio.wait([src.task], timeout=15)
            return src.status.model_copy(deep=True)
        if tgt := self._targets.get(migration_id):
            async with self._target_lock:
                await self._discard_target(tgt, "aborted by user on target", notify=True)
            return tgt.status.model_copy(deep=True)
        raise KeyError(f"unknown migration {migration_id}")

    def status(self, migration_id: str) -> MigrationStatus | None:
        if st := self._archived.get(migration_id):
            return st.model_copy(deep=True)
        run = self._sources.get(migration_id) or self._targets.get(migration_id)
        if run is None or run.precopy:
            return None
        if isinstance(run, _SourceRun):
            run.status.metrics = self._metrics_of(run)
        return run.status.model_copy(deep=True)

    def metrics(self, migration_id: str) -> MigrationMetrics | None:
        st = self.status(migration_id)
        if st is None:
            return None
        return st.metrics or self._basic_metrics(st)

    async def wait(self, migration_id: str, timeout: float | None = None) -> MigrationStatus:
        """Wait for a source migration to finish (tests, scripts)."""
        run = self._sources[migration_id]
        if run.task:
            await asyncio.wait_for(asyncio.shield(run.task), timeout)
        return run.status.model_copy(deep=True)

    def list(self) -> builtins.list[MigrationStatus]:
        live = [r.status for r in self._sources.values() if not r.precopy]
        live += [r.status for r in self._targets.values() if not r.precopy]
        runs = [*self._archived.values(), *live]
        return [s.model_copy(deep=True) for s in sorted(runs, key=lambda s: s.startedAt)]

    # ------------------------------------------------------------------ shared helpers

    async def _publish(self, status: MigrationStatus) -> None:
        """Journal and publish. Internal pre-copy runs are neither."""
        src, tgt = self._sources.get(status.id), self._targets.get(status.id)
        if (src and src.precopy) or (tgt and tgt.precopy):
            return
        if src is not None:
            status.metrics = self._metrics_of(src)
            entry = JournalEntry(
                role="source",
                status=status,
                peerId=status.targetId,
                chunkSize=src.chunk_size,
                fenceEpoch=src.fence_epoch,
                startSent=src.start_sent,
                committed=src.committed,
                sent=src.sent,
            )
        elif tgt is not None:
            entry = JournalEntry(
                role="target",
                status=status,
                peerId=tgt.source_id,
                chunkSize=tgt.chunk_size,
                epoch=tgt.epoch,
                manifest=tgt.manifest,
            )
        else:
            entry = None
        if entry is not None:
            try:
                self.journal.save(entry)
            except OSError:
                log.exception("could not journal %s", status.id)
        await self.ctx.bus.publish(MigrationStatusEvent(status=status.model_copy(deep=True)))

    async def _send(self, device_id: str, msg: PeerMessage) -> None:
        await self.ctx.peers.send(device_id, msg)

    def _find_device(self, device_id: str) -> DeviceInfo:
        for d in [*self.ctx.devices.list_devices(), *self.ctx.peers.list_peers()]:
            if d.id == device_id:
                return d
        raise MigrationError(f"unknown target device {device_id}")

    def _local_state(self, workload_id: str) -> str:
        try:
            return self.host.status(workload_id).state
        except KeyError:
            return "unknown"

    async def _kill_local(self, workload_id: str) -> None:
        if self._local_state(workload_id) in ("running", "paused"):
            await self.host.kill(workload_id)

    async def _relaunch(self, workload_ids: set[str]) -> None:
        """Restart workloads this device holds that are not running (continuity after restart)."""
        for wid in sorted(workload_ids):
            if wid in self._hold or not self.ctx.authority.may_run(wid):
                continue
            if self._local_state(wid) in ("idle", "stopped", "exited"):
                try:
                    await self.host.start(wid, restore=True)
                    log.info("relaunched %s from its checkpoints", wid)
                except Exception:
                    log.exception("could not relaunch %s", wid)

    # ------------------------------------------------------------------ metrics

    def _metrics_of(self, run: _SourceRun) -> MigrationMetrics:
        st = run.status
        end = st.endedAt or time.time()
        transfer_ms = sum(m.transferMs for m in run.metrics if not m.skipped)
        mbps = st.bytesDone * 8 / 1e6 / (transfer_ms / 1000) if transfer_ms > 0 else 0.0
        return MigrationMetrics(
            migrationId=st.id,
            link=st.link,
            chunkSize=run.chunk_size,
            durationMs=round((end - st.startedAt) * 1000, 1),
            interruptionMs=st.interruptionMs,
            bytesTotal=st.bytesTotal,
            bytesDone=st.bytesDone,
            bytesSkipped=run.bytes_skipped,
            throughputMbps=round(mbps, 2),
            checkpoints=builtins.list(run.metrics),
            ts=time.time(),
            cutover=(
                CutoverTiming(
                    catchupRounds=run.catchup_rounds,
                    fenceMs=round(run.fence_ms, 1),
                    deltaBytes=run.delta_bytes,
                    deltaMs=round(run.delta_ms or 0.0, 1),
                    startMs=round(run.start_ms or 0.0, 1),
                )
                if run.fence_ms is not None
                else None
            ),
        )

    def _basic_metrics(self, st: MigrationStatus) -> MigrationMetrics:
        end = st.endedAt or time.time()
        tgt = self._targets.get(st.id)
        return MigrationMetrics(
            migrationId=st.id,
            link=st.link,
            chunkSize=tgt.chunk_size if tgt else CHUNK_SIZE,
            durationMs=round((end - st.startedAt) * 1000, 1),
            interruptionMs=st.interruptionMs,
            bytesTotal=st.bytesTotal,
            bytesDone=st.bytesDone,
            bytesSkipped=0,
            throughputMbps=0.0,
            checkpoints=[],
            ts=time.time(),
        )

    # ------------------------------------------------------------------ source side

    def _abort_source(self, run: _SourceRun, reason: str, hard: bool = False) -> None:
        """Abort and roll back. Once mig.start is out, a soft abort waits for the target's answer
        instead: rolling back while the target may be starting could leave two running copies."""
        if run.start_sent and not hard:
            run.late_abort = run.late_abort or reason
            return
        if run.abort_reason is None:
            run.abort_reason = reason
        run.mailbox.fail(MigrationAborted(reason))

    def _check(self, run: _SourceRun) -> None:
        if run.abort_reason is not None:
            raise MigrationAborted(run.abort_reason)

    async def _phase(self, run: _SourceRun, phase: Phase) -> None:
        self._check(run)
        run.status.phase = phase
        await self._publish(run.status)

    async def _progress(self, run: _SourceRun, force: bool = False) -> None:
        now = time.monotonic()
        if force or now - run.last_publish > 0.1:
            run.last_publish = now
            await self._publish(run.status)

    def _mark(self, run: _SourceRun, record: CheckpointRecord, **update: bool) -> None:
        cps = run.status.checkpoints
        for i, r in enumerate(cps):
            if r.id == record.id:
                cps[i] = record.model_copy(update={"sent": r.sent, "validated": r.validated, **update})
                return
        cps.append(record.model_copy(update={"sent": False, "validated": False, **update}))

    async def _finish(self, run: _SourceRun, phase: Phase, error: str | None = None) -> None:
        st = run.status
        st.phase, st.endedAt = phase, time.time()
        if error:
            st.error = error
        st.authority = self.ctx.authority.get(st.workloadId)
        shutil.rmtree(run.outgoing, ignore_errors=True)
        await self._publish(st)

    async def _run_source(self, run: _SourceRun) -> None:
        st = run.status
        try:
            await self._phase(run, "CONNECTING")
            await self.ctx.peers.connect(st.targetId)
            link = self.ctx.peers.link_quality(st.targetId)
            if link is not None:
                st.link = link.link

            await self._phase(run, "EVALUATING")
            manifest = self.host.manifest(st.workloadId)
            target = self._find_device(st.targetId)
            result = await self.ctx.feasibility.evaluate(
                manifest, self.ctx.devices.local_info(), target, link
            )
            st.decision, st.reasons = result.decision, list(result.reasons)
            await self._log_decision(st)
            if result.decision == "REMOTE_ACCESS":
                self._check(run)
                await self.ctx.remote.start_session(st.workloadId, st.targetId)
                await self._finish(run, "REMOTE_ACCESS")
            elif result.decision == "STAY":
                blocks = "; ".join(r.text for r in result.reasons if r.severity == "block")
                await self._finish(
                    run,
                    "FAILED",
                    _short(f"Teleport decided to keep it here: {blocks or 'no device can take it.'}"),
                )
            else:
                await self._migrate(run, manifest)
        except Exception as e:
            reason, detail = _explain(e, run.abort_reason, st.phase)
            if detail:
                log.info("%s: %s (%s)", st.id, reason, detail)
                _note(st, "error.detail", "warn", _short(detail, 300))
            if run.committed:
                log.exception("%s: error after the target took over", st.id)
                await self._finish(run, "COMPLETED", f"Handed over, but cleanup here failed: {reason}")
            elif not run.prepared:  # nothing was offered yet: the source simply keeps running
                _note(st, "rollback", "block", f"Rolled back: {reason}")
                await self._finish(run, "ROLLED_BACK", reason)
            elif run.start_sent and not run.target_refused:
                await self._await_lease(run, reason)
            else:
                await self._rollback(run, reason)

    async def _await_lease(self, run: _SourceRun, why: str) -> None:
        """mig.start is out but its answer is not: the target may be running. Resuming here could
        mean two copies, so stay fenced until the target's lease says who holds the workload."""
        run.awaiting = True
        text = f"{why}; the target may have started. Waiting for its lease before resuming or handing over."
        _note(run.status, "recovery.wait", "warn", text)
        await self._publish(run.status)

    async def _log_decision(self, st: MigrationStatus) -> None:
        assert st.decision is not None
        entry = DecisionLog(
            id=f"dec-{uuid.uuid4().hex[:12]}",
            ts=time.time(),
            workloadId=st.workloadId,
            trigger=st.trigger,
            decision=st.decision,
            reasons=st.reasons,
            migrationId=st.id,
        )
        try:
            await self.ctx.history.log_decision(entry)
        except Exception:
            log.exception("could not log decision")

    async def _snapshot(
        self, run: _SourceRun, ids: builtins.list[str], skip_missing: bool = False
    ) -> builtins.list[CheckpointRecord]:
        """Freeze the current units into outgoing/ (off the event loop: reads and hashes files)."""
        return await asyncio.to_thread(self._snapshot_sync, run, ids, skip_missing)

    def _snapshot_sync(
        self, run: _SourceRun, ids: builtins.list[str], skip_missing: bool
    ) -> builtins.list[CheckpointRecord]:
        """Copy the current units into outgoing/ so later writes cannot change what is sent."""
        wid = run.status.workloadId
        run.outgoing.mkdir(parents=True, exist_ok=True)
        out: builtins.list[CheckpointRecord] = []
        for cid in ids:
            data, rec = self.store.read(wid, cid), self.store.record(wid, cid)
            if data is None or rec is None:
                if skip_missing:
                    continue
                raise MigrationError(f"Checkpoint {cid} was never saved by the workload.")
            (run.outgoing / f"{cid}.tar.gz").write_bytes(data)
            out.append(
                CheckpointRecord(
                    id=cid, seq=rec.seq, sizeBytes=len(data), sha256=sha256_hex(data), createdAt=rec.createdAt
                )
            )
        return out

    async def _pack_code(self, run: _SourceRun) -> CheckpointRecord:
        source_dir, level = self.host.source_dir(run.status.workloadId), self.ctx.prefs.compressLevel
        return await asyncio.to_thread(self._pack_code_sync, run, source_dir, level)

    def _pack_code_sync(self, run: _SourceRun, source_dir: Path, level: int) -> CheckpointRecord:
        files = collect_files(["."], source_dir, exclude=CODE_EXCLUDE)
        data = pack_unit(None, files, level)
        run.outgoing.mkdir(parents=True, exist_ok=True)
        (run.outgoing / f"{CODE_UNIT}.tar.gz").write_bytes(data)
        return CheckpointRecord(
            id=CODE_UNIT, seq=0, sizeBytes=len(data), sha256=sha256_hex(data), createdAt=0
        )

    async def _offer(
        self,
        run: _SourceRun,
        manifest: WorkloadManifest,
        records: builtins.list[CheckpointRecord],
        epoch: int,
    ) -> set[str]:
        """mig.prepare + mig.ready. Returns the ids the target already holds (not sent again)."""
        st = run.status
        payload = prepare_payload(st.id, manifest, records, epoch)
        self._check(run)
        run.prepared = True
        await self._send(
            st.targetId,
            MigPrepare(
                migrationId=st.id,
                manifest=manifest,
                checkpoints=records,
                epoch=epoch,
                signature=self.signer.sign_manifest(payload),
                chunkSize=run.chunk_size,
                precopy=run.precopy or None,
            ),
        )
        ready = await run.mailbox.expect(("ready",), self.timeouts.ready)
        assert isinstance(ready, MigReady)
        if not ready.ok:
            st.reasons = [*st.reasons, *ready.reasons]
            raise MigrationError("The target refused: " + " ".join(r.text for r in ready.reasons))
        have = set(ready.have or []) & {r.id for r in records}
        for r in records:
            if r.id in have:
                run.bytes_skipped += r.sizeBytes
                run.metrics.append(_metric(r, "precopy" if run.precopy else "initial", skipped=True))
                self._mark(run, r, sent=True, validated=True)
        return have

    def _ensure_running(self, run: _SourceRun) -> None:
        """A workload that exited on its own has no live state left to hand over."""
        wid = run.status.workloadId
        if self._local_state(wid) in ("running", "paused"):
            return
        code = self.host.status(wid).exitCode
        how = f"exit code {code}" if code is not None else "it is not running"
        raise MigrationError(f"The workload stopped during the transfer ({how}); nothing to hand over.")

    async def _changed_since_sent(self, run: _SourceRun, ids: builtins.list[str]) -> builtins.list[str]:
        records = await asyncio.to_thread(self.store.records, run.status.workloadId)
        current = {r.id: r.sha256 for r in records}
        return [cid for cid in ids if current.get(cid) != run.sent[cid].sha256]

    def _pending_bytes(self, run: _SourceRun, ids: builtins.list[str]) -> int:
        records = (self.store.record(run.status.workloadId, cid) for cid in ids)
        return sum(r.sizeBytes for r in records if r is not None)

    async def _send_changes(
        self, run: _SourceRun, changed_ids: builtins.list[str], epoch: int, stage: Stage
    ) -> int:
        """Snapshot and send the units whose SHA-256 changed since they were last sent (mig.fenced
        tells the target which units are replaced), then wait for the target to validate them."""
        st = run.status
        if not changed_ids:  # nothing changed: no mig.fenced, no extra validation round trip
            return 0
        changed = await self._snapshot(run, changed_ids)
        for r in changed:
            run.sent[r.id] = r
            self._mark(run, r, sent=False, validated=False)
        size = sum(r.sizeBytes for r in changed)
        st.bytesTotal += size
        await self._publish(st)
        await self._send(st.targetId, MigFenced(migrationId=st.id, changed=changed))
        try:  # all changed units at once: one round of acks instead of one per unit
            async with asyncio.TaskGroup() as tg:
                for r in changed:
                    tg.create_task(self._transfer(run, r, epoch, stage))
        except BaseExceptionGroup as eg:
            raise eg.exceptions[0] from None
        await self._await_validated(run)
        return size

    async def _migrate(self, run: _SourceRun, manifest: WorkloadManifest) -> None:
        st, t, auth = run.status, self.timeouts, self.ctx.authority
        wid, target = st.workloadId, st.targetId
        lease = auth.get(wid)
        if not auth.may_run(wid):
            raise MigrationError(
                f"This device does not hold {manifest.name} right now ({lease.state.lower()})."
            )
        if lease.state == "TARGET":  # it arrived here by migration; now it leaves as SOURCE
            lease = await auth.claim(wid, self.ctx.device_id)
        user_ids = [c.id for c in manifest.checkpoints]

        # 1. Live snapshot and full transfer: the workload keeps running and keeps authority.
        await self.host.request_checkpoint(wid, t.checkpoint)
        records = [await self._pack_code(run), *await self._snapshot(run, user_ids)]
        for r in records:
            run.sent[r.id] = r
            self._mark(run, r)
        have = await self._offer(run, manifest, records, lease.epoch)
        st.bytesTotal = sum(r.sizeBytes for r in records if r.id not in have)

        await self._phase(run, "TRANSFERRING")
        for r in records:
            if r.id not in have:
                await self._transfer(run, r, lease.epoch, "initial")
                self._ensure_running(run)
        await self._phase(run, "VALIDATING")
        await self._await_validated(run)

        # 2. Catch-up rounds, still live: resend what changed meanwhile until little is left, so the
        #    freeze window below only carries the last small delta.
        for _ in range(t.catchup_rounds):
            await self.host.request_checkpoint(wid, t.checkpoint)
            self._ensure_running(run)
            changed_ids = await self._changed_since_sent(run, user_ids)
            if not changed_ids or self._pending_bytes(run, changed_ids) <= t.catchup_bytes:
                break
            run.catchup_rounds += 1
            await self._send_changes(run, changed_ids, lease.epoch, "catchup")
        self._ensure_running(run)
        self._check(run)

        # 3. Freeze window (the interruption): pause, fence, send only what changed, start the target.
        fence_start = time.perf_counter()
        await self._phase(run, "FENCING")
        self.host.pause(wid)
        fenced = await auth.fence(wid)
        run.fence_epoch = fenced.epoch
        st.authority = fenced
        await self._send(target, MigFence(migrationId=st.id, epoch=fenced.epoch))
        if any(c.paths for c in manifest.checkpoints):  # paused: manifest paths are now consistent
            await self.host.request_checkpoint(wid, t.checkpoint)
        delta_start = time.perf_counter()
        run.fence_ms = (delta_start - fence_start) * 1000
        changed_ids = await self._changed_since_sent(run, user_ids)
        run.delta_bytes = await self._send_changes(run, changed_ids, fenced.epoch, "delta")
        run.delta_ms = (time.perf_counter() - delta_start) * 1000

        self._check(run)
        run.start_sent = True  # from here an abort must wait for the target's answer
        await self._phase(run, "STARTING_TARGET")
        start_sent_at = time.perf_counter()
        await self._send(target, MigStart(migrationId=st.id, epoch=fenced.epoch))
        started = await run.mailbox.expect(("started",), t.start)
        assert isinstance(started, MigStarted)
        if not started.ok:
            run.target_refused = True
            why = started.error or "unknown error"
            raise MigrationError(run.late_abort or f"The target could not start the workload: {why}.")
        if run.late_abort:
            _note(
                st,
                "abort.late",
                "warn",
                f"Too late to abort ({run.late_abort}): the target had already started.",
            )

        run.committed = True
        now = time.perf_counter()
        run.start_ms = (now - start_sent_at) * 1000
        st.interruptionMs = round((now - fence_start) * 1000, 1)
        await self._publish(st)  # journal the commit before anything else
        await auth.grant(wid, target, fenced.epoch)
        await self.host.kill(wid)
        await asyncio.to_thread(self._cache_code, run)
        await self._finish(run, "COMPLETED")

    def _cache_code(self, run: _SourceRun) -> None:
        """Keep the code unit we sent, so migrating back does not need to send it again."""
        src = run.outgoing / f"{CODE_UNIT}.tar.gz"
        if src.exists():
            cache = self.cache_dir(run.status.workloadId)
            cache.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, cache / f"{CODE_UNIT}.tar.gz")

    async def _transfer(self, run: _SourceRun, record: CheckpointRecord, epoch: int, stage: Stage) -> None:
        st, t = run.status, self.timeouts
        path = run.outgoing / f"{record.id}.tar.gz"
        chunks = await asyncio.to_thread(lambda: list(iter_chunks(path, run.chunk_size)))
        window = asyncio.Semaphore(t.window)
        retries = 0
        started = time.perf_counter()  # monotonic() only ticks every ~15 ms on Windows

        async def send_chunk(index: int, total: int, data: bytes, digest: str) -> None:
            nonlocal retries
            async with window:
                if t.chunk_delay:
                    await asyncio.sleep(t.chunk_delay)
                key: Key = ("ack", record.id, str(index))
                for attempt in range(t.retries + 1):
                    self._check(run)
                    if attempt:
                        retries += 1
                    run.mailbox.discard(key)
                    msg = MigChunk(
                        migrationId=st.id,
                        checkpointId=record.id,
                        index=index,
                        total=total,
                        dataB64=base64.b64encode(data).decode(),
                        sha256=digest,
                        epoch=epoch,
                    )
                    await self._send(st.targetId, msg)
                    try:
                        ack = await run.mailbox.expect(key, t.ack)
                    except TimeoutError:
                        log.warning("%s: no ack for %s[%d], resending", st.id, record.id, index)
                        continue
                    assert isinstance(ack, MigChunkAck)
                    if ack.ok:
                        st.bytesDone += len(data)
                        await self._progress(run)
                        return
                    log.warning("%s: target rejected %s[%d], resending", st.id, record.id, index)
                raise MigrationError(
                    f"Checkpoint {record.id} could not be sent intact "
                    f"(failed after {t.retries + 1} attempts): the link is too slow or keeps dropping."
                )

        try:
            async with asyncio.TaskGroup() as tg:
                for c in chunks:
                    tg.create_task(send_chunk(c.index, c.total, c.data, c.sha256))
        except BaseExceptionGroup as eg:
            raise eg.exceptions[0] from None
        elapsed_ms = (time.perf_counter() - started) * 1000
        run.metrics.append(_metric(record, stage, chunks=len(chunks), retries=retries, ms=elapsed_ms))
        self._mark(run, record, sent=True)
        await self._progress(run, force=True)

    async def _await_validated(self, run: _SourceRun) -> None:
        msg = await run.mailbox.expect(("validated",), self.timeouts.validate)
        assert isinstance(msg, MigValidated)
        if not msg.ok:
            raise MigrationError(
                f"The target could not verify {', '.join(msg.failed or []) or 'the checkpoints'}."
            )
        for r in run.status.checkpoints:
            if r.sent:
                self._mark(run, r, validated=True)
        await self._progress(run, force=True)

    async def _rollback(self, run: _SourceRun, reason: str) -> None:
        st, wid = run.status, run.status.workloadId
        st.error = reason
        st.reasons = [*st.reasons, Reason(code="rollback", severity="block", text=f"Rolled back: {reason}")]
        st.phase = "ROLLING_BACK"
        await self._publish(st)
        try:
            await self._send(st.targetId, MigAbort(migrationId=st.id, reason=reason))
        except Exception:
            log.info("%s: could not tell the target to discard (%s)", st.id, reason)
        lease = self.ctx.authority.get(wid)
        if lease.state == "FENCED" and lease.holder == self.ctx.device_id:
            await self.ctx.authority.rollback(wid)
        try:
            if self._local_state(wid) == "paused":
                self.host.resume(wid)
        except Exception:
            log.exception("%s: could not resume the source copy", st.id)
        await self._finish(run, "ROLLED_BACK", reason)

    # ------------------------------------------------------------------ pre-copy

    async def precopy(self, workload_id: str, target_id: str) -> MigrationMetrics:
        """Send the checkpoints the target does not hold yet, while the workload keeps running and
        keeps authority. A later migration then only transfers the final delta."""
        if target_id == self.ctx.device_id:
            raise MigrationError("target is this device")
        manifest = self.host.manifest(workload_id)
        if not self.ctx.authority.may_run(workload_id):
            raise MigrationError(f"this device does not hold {workload_id}")
        if active := self._active(workload_id):
            raise MigrationError(f"{workload_id} is busy ({active.status.id})")
        mid = f"pre-{uuid.uuid4().hex[:12]}"
        run = _SourceRun(
            status=self._new_status(mid, workload_id, target_id, "user_command"),
            outgoing=self.store.workload_dir(workload_id) / "outgoing" / mid,
            chunk_size=self.ctx.prefs.chunkSizeKb * 1024,
            precopy=True,
        )
        run.status.phase = "TRANSFERRING"
        self._sources[mid] = run
        try:
            await self.ctx.peers.connect(target_id)
            if link := self.ctx.peers.link_quality(target_id):
                run.status.link = link.link
            user_ids = [c.id for c in manifest.checkpoints]
            records = [await self._pack_code(run), *await self._snapshot(run, user_ids, True)]
            have = await self._offer(run, manifest, records, self.ctx.authority.get(workload_id).epoch)
            run.status.bytesTotal = sum(r.sizeBytes for r in records if r.id not in have)
            for r in records:
                if r.id not in have:
                    await self._transfer(run, r, self.ctx.authority.get(workload_id).epoch, "precopy")
            await self._await_validated(run)
            run.status.phase, run.status.endedAt = "COMPLETED", time.time()
            return self._metrics_of(run)
        finally:
            if run.status.phase != "COMPLETED":
                with contextlib.suppress(Exception):
                    await self._send(target_id, MigAbort(migrationId=mid, reason="pre-copy failed"))
            shutil.rmtree(run.outgoing, ignore_errors=True)
            self._sources.pop(mid, None)

    async def _precopy_loop(self) -> None:
        while True:
            interval = self.ctx.prefs.precopyIntervalS
            await asyncio.sleep(interval if interval > 0 else 1.0)
            if interval <= 0:
                continue
            target = self.ctx.prefs.precopyTargetId or next(iter(sorted(self._linked)), "")
            if not target:
                continue
            for manifest in self.host.list():
                wid = manifest.id
                if (
                    self._local_state(wid) != "running"
                    or self._active(wid)
                    or not self.ctx.authority.may_run(wid)
                ):
                    continue
                try:
                    m = await self.precopy(wid, target)
                    log.info("pre-copied %s to %s: %d bytes sent", wid, target, m.bytesDone)
                except Exception as e:
                    log.info("pre-copy of %s to %s skipped: %s", wid, target, e)

    # ------------------------------------------------------------------ restart recovery

    async def _recover(self) -> None:
        for entry in self.journal.load_all():
            if entry.status.phase in TERMINAL:
                self._archived[entry.status.id] = entry.status
            elif entry.role == "source":
                await self._recover_source(entry)
            else:
                await self._recover_target(entry)

    async def _recover_source(self, entry: JournalEntry) -> None:
        st, auth, me = entry.status, self.ctx.authority, self.ctx.device_id
        wid, target = st.workloadId, st.targetId
        run = _SourceRun(
            status=st,
            outgoing=self.store.workload_dir(wid) / "outgoing" / st.id,
            chunk_size=entry.chunkSize,
            prepared=True,
            start_sent=entry.startSent,
            committed=entry.committed,
            fence_epoch=entry.fenceEpoch,
            sent=dict(entry.sent),
        )
        self._sources[st.id] = run
        note = f"Agent restarted during {st.phase}."
        lease = auth.get(wid)
        if entry.committed or (lease.holder == target and lease.state == "TARGET"):
            # Authority had already moved: the old source stays stopped.
            if lease.holder != target:
                await auth.grant(wid, target, entry.fenceEpoch or lease.epoch)
            await self._kill_local(wid)
            _note(
                st,
                "recovery.moved",
                "warn",
                f"{note} The target already held authority, so this copy stays stopped.",
            )
            await self._finish(run, "COMPLETED")
        elif entry.startSent and lease.state == "FENCED" and lease.holder == me:
            await self._await_lease(run, note.rstrip("."))
        else:
            await self._rollback(run, f"{note} The target never got authority, so this copy resumes.")
            self._resume.add(wid)

    async def _recover_target(self, entry: JournalEntry) -> None:
        st, auth, me = entry.status, self.ctx.authority, self.ctx.device_id
        wid = st.workloadId
        assert entry.manifest is not None
        tgt = _TargetRun(
            status=st,
            manifest=entry.manifest,
            source_id=entry.peerId,
            prepare_epoch=entry.epoch or 0,
            epoch=entry.epoch or 0,
            staging=self.store.workload_dir(wid) / "staging" / st.id,
            records={},
            parts={},
            chunk_size=entry.chunkSize,
        )
        self._targets[st.id] = tgt
        note = f"Agent restarted during {st.phase}."
        lease = auth.get(wid)
        if lease.holder == me and lease.state == "TARGET" and lease.epoch == entry.epoch:
            # We took authority but cannot know if the source heard mig.started: its lease decides.
            tgt.awaiting = True
            self._hold.add(wid)
            _note(st, "recovery.wait", "warn", f"{note} Waiting for the source's lease before starting.")
            await self._publish(st)
        else:
            await self._discard_target(tgt, f"{note} The staged copy was discarded.", notify=False)

    # ------------------------------------------------------------------ split-brain guard

    async def _lease_loop(self) -> None:
        while True:
            await asyncio.sleep(self.ctx.prefs.leaseSyncS)
            await self._sync_leases()

    async def _sync_leases(self, only: str | None = None) -> None:
        peers = [only] if only else self.ctx.peer_directory.ids()
        cutoff = time.time() - 60
        self._recent_conflicts = [c for c in self._recent_conflicts if c.ts > cutoff]
        msg = AuthLeases(leases=self.ctx.authority.leases(), conflicts=self._recent_conflicts or None)
        for peer in peers:
            if self.ctx.peers.link_quality(peer) is None:
                continue
            try:
                await self._send(peer, msg)
            except Exception as e:
                log.debug("lease sync to %s failed: %s", peer, e)

    async def _on_link_update(self, event: LinkUpdateEvent) -> None:
        if event.link.peerId not in self._linked:
            self._linked.add(event.link.peerId)
            await self._sync_leases(event.link.peerId)  # (re)connected: compare leases now

    async def _on_leases(self, peer: str, msg: AuthLeases) -> None:
        async with self._lease_lock:
            remote = {lease.workloadId: lease for lease in msg.leases}
            await self._resolve_waiting(peer, remote)
            for conflict in msg.conflicts or []:  # the peer resolved one we may not have seen
                await self._report_conflict(conflict)
            for wid, theirs in remote.items():
                if wid in self._hold or self._active(wid) or self._target_active(wid):
                    continue
                await self._guard(peer, self.ctx.authority.get(wid), theirs)

    def _target_active(self, workload_id: str) -> bool:
        return any(
            t.manifest.id == workload_id and t.status.phase not in TERMINAL for t in self._targets.values()
        )

    async def _resolve_waiting(self, peer: str, remote: dict[str, Authority]) -> None:
        me, auth = self.ctx.device_id, self.ctx.authority
        for run in [r for r in self._sources.values() if r.awaiting and r.status.targetId == peer]:
            wid, theirs = run.status.workloadId, remote.get(run.status.workloadId)
            fence = run.fence_epoch or 0
            if theirs and theirs.holder == peer and theirs.state == "TARGET" and theirs.epoch >= fence:
                run.awaiting, run.committed = False, True
                await auth.adopt(theirs)
                await self._kill_local(wid)
                _note(
                    run.status,
                    "recovery.moved",
                    "pass",
                    "The target reports it holds authority: handover done.",
                )
                await self._finish(run, "COMPLETED")
            elif theirs is None or theirs.holder != peer or theirs.epoch < fence:
                run.awaiting = False
                await self._rollback(
                    run, "The target never took authority after the restart, so this copy resumes."
                )
                await self._relaunch({wid})
        for tgt in [t for t in self._targets.values() if t.awaiting and t.source_id == peer]:
            wid, theirs = tgt.manifest.id, remote.get(tgt.manifest.id)
            if theirs and theirs.holder == me and theirs.state == "TARGET":
                tgt.awaiting = False
                self._hold.discard(wid)
                tgt.started = True
                tgt.status.phase, tgt.status.endedAt = "COMPLETED", time.time()
                await self._publish(tgt.status)
                await self._relaunch({wid})
            elif theirs and theirs.holder == peer and theirs.state == "FENCED":
                continue  # the source is undecided too; it decides from our lease
            else:
                tgt.awaiting = False
                self._hold.discard(wid)
                await auth.release(wid)
                await self._discard_target(tgt, "The source kept authority after the restart.", notify=False)

    async def _guard(self, peer: str, mine: Authority, theirs: Authority) -> None:
        me, wid = self.ctx.device_id, mine.workloadId
        verdict = resolve(mine, theirs, me, peer)
        if verdict == "learn":
            await self.ctx.authority.adopt(theirs)
        elif verdict in ("stop_local", "stop_remote"):
            stopped, winner = (me, peer) if verdict == "stop_local" else (peer, me)
            if verdict == "stop_local":  # the loser never has the higher epoch, so adopting is safe
                await self._kill_local(wid)
                await self.ctx.authority.adopt(theirs)
            conflict = AuthorityConflict(
                workloadId=wid,
                deviceId=me,
                peerId=peer,
                localEpoch=mine.epoch,
                remoteEpoch=theirs.epoch,
                winner=winner,
                stopped=stopped,
                reason=(
                    f"Both devices held {wid} (epochs {mine.epoch} here, {theirs.epoch} on {peer}); "
                    f"the copy on {stopped} was stopped."
                ),
                ts=time.time(),
            )
            if await self._report_conflict(conflict):
                self._recent_conflicts.append(conflict)

    async def _report_conflict(self, conflict: AuthorityConflict) -> bool:
        """Publish a conflict once per (workload, stopped device, epoch), whoever detected it."""
        key = (conflict.workloadId, conflict.stopped, max(conflict.localEpoch, conflict.remoteEpoch))
        if key in self._reported:
            return False
        self._reported.add(key)
        log.warning("split brain on %s: %s", conflict.workloadId, conflict.reason)
        await self.ctx.bus.publish(AuthorityConflictEvent(conflict=conflict))
        return True

    # ------------------------------------------------------------------ peer messages

    async def _on_peer_message(self, from_id: str, msg: PeerMessage) -> None:
        if isinstance(msg, AuthLeases):
            await self._on_leases(from_id, msg)
            return
        if isinstance(msg, MigReady | MigChunkAck | MigValidated | MigStarted):
            src = self._sources.get(msg.migrationId)
            if src is None or src.status.targetId != from_id:
                return
            if isinstance(msg, MigChunkAck):
                src.mailbox.deliver(("ack", msg.checkpointId, str(msg.index)), msg)
            else:
                src.mailbox.deliver((msg.t.removeprefix("mig."),), msg)
            return
        if isinstance(msg, MigAbort) and (src := self._sources.get(msg.migrationId)):
            if src.status.targetId == from_id and not src.committed:
                self._abort_source(src, f"The target cancelled: {msg.reason}", hard=True)
            return
        if isinstance(msg, MigPrepare | MigChunk | MigFence | MigFenced | MigStart | MigAbort):
            async with self._target_lock:
                await self._on_target_message(from_id, msg)

    async def _on_device_lost(self, event: DeviceLostEvent) -> None:
        self._linked.discard(event.deviceId)
        task = asyncio.create_task(self._confirm_lost(event.deviceId))
        self._tasks.append(task)
        task.add_done_callback(lambda t: self._tasks.remove(t) if t in self._tasks else None)

    async def _peer_reachable(self, peer: str) -> bool:
        try:
            await asyncio.wait_for(self.ctx.peers.connect(peer), self.timeouts.relink)
        except Exception:
            return False
        return self.ctx.peers.link_quality(peer) is not None

    async def _confirm_lost(self, peer: str) -> None:
        """device.lost can be a blip (a slow heartbeat under load): reconnect once before giving up
        on the migrations with that peer."""
        involved = any(
            s.status.targetId == peer and s.status.phase not in TERMINAL for s in self._sources.values()
        ) or any(t.source_id == peer and t.status.phase not in TERMINAL for t in self._targets.values())
        if not involved:
            return
        if await self._peer_reachable(peer):
            log.info("link to %s came back; migrations with it continue", peer)
            return
        for src in self._sources.values():
            if src.status.targetId == peer and src.status.phase not in TERMINAL:
                if not src.committed and not src.awaiting:
                    self._abort_source(src, "Lost the link to the target.", hard=True)
        async with self._target_lock:
            for tgt in list(self._targets.values()):
                live = not tgt.started and not tgt.awaiting and tgt.status.phase not in TERMINAL
                if tgt.source_id == peer and live:
                    await self._discard_target(
                        tgt, "Lost the link to the source; the staged copy was discarded.", notify=False
                    )

    # ------------------------------------------------------------------ target side

    async def _on_target_message(self, src: str, msg: PeerMessage) -> None:
        try:
            await self._handle_target_message(src, msg)
        except Exception as e:
            mid = getattr(msg, "migrationId", "")
            reason, detail = _explain(e, None, "TRANSFERRING")
            if isinstance(e, OSError) and e.errno == errno.ENOSPC:
                reason = "The target ran out of disk space."
            log.exception("%s: target failed handling %s: %s", mid, msg.t, detail or reason)
            if tgt := self._targets.get(mid):
                await self._discard_target(tgt, reason, notify=True)
            else:
                with contextlib.suppress(Exception):
                    await self._send(src, MigAbort(migrationId=mid, reason=reason))

    async def _handle_target_message(self, src: str, msg: PeerMessage) -> None:
        if isinstance(msg, MigPrepare):
            await self._on_prepare(src, msg)
            return
        tgt = self._targets.get(msg.migrationId)  # type: ignore[union-attr]
        if tgt is None or tgt.source_id != src or tgt.status.phase in TERMINAL or tgt.awaiting:
            if isinstance(msg, MigChunk):
                await self._ack(src, msg, ok=False)
            elif isinstance(msg, MigStart):
                await self._send(
                    src, MigStarted(migrationId=msg.migrationId, ok=False, error="unknown migration")
                )
            return
        if isinstance(msg, MigChunk):
            await self._on_chunk(tgt, msg)
        elif isinstance(msg, MigFence):
            if msg.epoch <= tgt.epoch:
                log.warning("%s: ignoring stale fence epoch %d", tgt.status.id, msg.epoch)
                return
            tgt.epoch = msg.epoch
            tgt.status.phase = "FENCING"
            await self._publish(tgt.status)
        elif isinstance(msg, MigFenced):
            for rec in msg.changed:
                if rec.id not in tgt.records:
                    continue
                tgt.records[rec.id] = rec
                tgt.parts[rec.id] = Reassembler(rec, tgt.chunk_size)
                tgt.validated.discard(rec.id)
                tgt.failed.discard(rec.id)
                (tgt.staging / f"{rec.id}.tar.gz").unlink(missing_ok=True)
            tgt.owes_validation = True
            await self._maybe_validated(tgt)
        elif isinstance(msg, MigStart):
            await self._on_start(tgt, msg)
        elif isinstance(msg, MigAbort):
            await self._discard_target(tgt, f"The source cancelled: {msg.reason}", notify=False)

    def _disk_free(self, path: Path) -> int:
        return shutil.disk_usage(path).free

    def _stage_cached(
        self, workload_id: str, staging: Path, records: dict[str, CheckpointRecord]
    ) -> builtins.list[str]:
        """Fresh staging folder, pre-filled with every offered unit this device already holds."""
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        have: builtins.list[str] = []
        for cid, rec in records.items():
            if (data := self._cached_unit(workload_id, rec)) is not None:
                (staging / f"{cid}.tar.gz").write_bytes(data)
                have.append(cid)
        return have

    def _cached_unit(self, workload_id: str, record: CheckpointRecord) -> bytes | None:
        """A unit with this exact hash that this device already holds, or None."""
        candidates = [self.cache_dir(workload_id) / f"{record.id}.tar.gz"]
        if record.id != CODE_UNIT:
            candidates.append(self.store.unit_path(workload_id, record.id))
        for path in candidates:
            if path.exists() and path.stat().st_size == record.sizeBytes:
                data = path.read_bytes()
                if sha256_hex(data) == record.sha256:
                    return data
        return None

    async def _on_prepare(self, src: str, msg: MigPrepare) -> None:
        manifest, wid = msg.manifest, msg.manifest.id
        reasons: builtins.list[Reason] = []

        def block(code: str, text: str) -> None:
            reasons.append(Reason(code=code, severity="block", text=text))

        payload = prepare_payload(msg.migrationId, manifest, msg.checkpoints, msg.epoch)
        if not self.signer.verify_manifest(src, payload, msg.signature):
            block("signature", "The migration manifest signature is invalid.")
        if not self.ctx.authority.check_epoch(wid, msg.epoch):
            block("epoch", f"Epoch {msg.epoch} is older than {self.ctx.authority.get(wid).epoch}.")
        if self.ctx.authority.may_run(wid) or self._local_state(wid) in ("running", "paused"):
            block("running", f"{manifest.name} is already running on this device.")
        if wid in self._hold:
            block("recovering", f"{manifest.name} is still being recovered on this device.")
        ids = {r.id for r in msg.checkpoints}
        missing = [c.id for c in manifest.checkpoints if c.id not in ids]
        if not msg.precopy and (missing or CODE_UNIT not in ids):
            block("checkpoints", f"Checkpoints missing from the offer: {', '.join(missing) or CODE_UNIT}.")
        if msg.migrationId in self._targets:
            block("duplicate", "This migration was already offered.")
        if reasons:
            await self._send(src, MigReady(migrationId=msg.migrationId, ok=False, reasons=reasons))
            return

        chunk_size = msg.chunkSize or CHUNK_SIZE
        records = {r.id: r for r in msg.checkpoints}
        staging = self.store.workload_dir(wid) / "staging" / msg.migrationId
        have = await asyncio.to_thread(self._stage_cached, wid, staging, records)
        incoming = sum(r.sizeBytes for cid, r in records.items() if cid not in have)
        # Staged units, then the committed copy, then the unpacked work folder: about 3x, plus the
        # manifest's own disk need, before anything is sent.
        needed = incoming * 3 + manifest.minDiskMb * 2**20
        free = self._disk_free(staging)
        if free < needed:
            shutil.rmtree(staging, ignore_errors=True)
            text = (
                f"Not enough disk space on the target: {needed / 2**20:.0f} MB needed, "
                f"{free / 2**20:.0f} MB free."
            )
            reasons = [Reason(code="disk.full", severity="block", text=text)]
            await self._send(src, MigReady(migrationId=msg.migrationId, ok=False, reasons=reasons))
            return
        status = MigrationStatus(
            id=msg.migrationId,
            workloadId=wid,
            sourceId=src,
            targetId=self.ctx.device_id,
            phase="TRANSFERRING",
            trigger="user_command",
            link=(lq.link if (lq := self.ctx.peers.link_quality(src)) else "wifi"),
            decision="MIGRATE",
            reasons=[],
            checkpoints=[r.model_copy(update={"sent": False, "validated": False}) for r in records.values()],
            bytesTotal=sum(r.sizeBytes for cid, r in records.items() if cid not in have),
            bytesDone=0,
            authority=self.ctx.authority.get(wid),
            startedAt=time.time(),
        )
        tgt = _TargetRun(
            status=status,
            manifest=manifest,
            source_id=src,
            prepare_epoch=msg.epoch,
            epoch=msg.epoch,
            staging=staging,
            records=records,
            parts={cid: Reassembler(r, chunk_size) for cid, r in records.items() if cid not in have},
            chunk_size=chunk_size,
            precopy=bool(msg.precopy),
            validated=set(have),
        )
        self._targets[msg.migrationId] = tgt
        self._target_marks(tgt)
        text = f"Target staged the migration ({len(have)} of {len(records)} units already here)."
        ok = Reason(code="ready", severity="pass", text=text)
        await self._send(src, MigReady(migrationId=msg.migrationId, ok=True, reasons=[ok], have=have or None))
        await self._publish(status)
        await self._maybe_validated(tgt)

    async def _ack(self, src: str, msg: MigChunk, ok: bool) -> None:
        ack = MigChunkAck(migrationId=msg.migrationId, checkpointId=msg.checkpointId, index=msg.index, ok=ok)
        await self._send(src, ack)

    async def _on_chunk(self, tgt: _TargetRun, msg: MigChunk) -> None:
        cid = msg.checkpointId
        if msg.epoch < tgt.epoch or cid not in tgt.records:
            await self._ack(tgt.source_id, msg, ok=False)
            return
        if cid in tgt.validated:  # duplicate of an already validated checkpoint
            await self._ack(tgt.source_id, msg, ok=True)
            return
        part = tgt.parts[cid]
        try:
            data = base64.b64decode(msg.dataB64, validate=True)
            part.add(msg.index, msg.total, data, msg.sha256)
        except (ChunkError, binascii.Error) as e:
            log.warning("%s: rejected chunk: %s", tgt.status.id, e)
            await self._ack(tgt.source_id, msg, ok=False)
            return
        await self._ack(tgt.source_id, msg, ok=True)
        tgt.status.bytesDone += len(data)
        if part.complete:
            try:
                await asyncio.to_thread(self._finalize_unit, part, tgt.staging / f"{cid}.tar.gz")
                tgt.validated.add(cid)
            except (ChunkError, ValueError) as e:
                log.warning("%s: checkpoint %s failed validation: %s", tgt.status.id, cid, e)
                tgt.failed.add(cid)
            self._target_marks(tgt)
            await self._maybe_validated(tgt)

    @staticmethod
    def _finalize_unit(part: Reassembler, path: Path) -> None:
        unit = part.finalize()  # whole-unit SHA-256
        unpack_unit(unit)  # a valid, safe archive
        path.write_bytes(unit)  # OSError (e.g. disk full) propagates: the migration is aborted

    def _target_marks(self, tgt: _TargetRun) -> None:
        def sent(cid: str) -> bool:
            return cid in tgt.validated or (cid in tgt.parts and tgt.parts[cid].complete)

        tgt.status.checkpoints = [
            r.model_copy(update={"sent": sent(cid), "validated": cid in tgt.validated})
            for cid, r in tgt.records.items()
        ]

    async def _maybe_validated(self, tgt: _TargetRun) -> None:
        if not tgt.owes_validation or len(tgt.validated | tgt.failed) < len(tgt.records):
            return
        tgt.owes_validation = False
        failed = sorted(tgt.failed)
        reply = MigValidated(migrationId=tgt.status.id, ok=not failed, failed=failed or None)
        if tgt.precopy:
            if not failed:
                self._commit_precopy(tgt)
            await self._send(tgt.source_id, reply)
            return
        await self._send(tgt.source_id, reply)
        tgt.status.phase = "VALIDATING"
        self._target_marks(tgt)
        await self._publish(tgt.status)

    def _commit_precopy(self, tgt: _TargetRun) -> None:
        cache = self.cache_dir(tgt.manifest.id)
        cache.mkdir(parents=True, exist_ok=True)
        for cid in tgt.validated:
            src = tgt.staging / f"{cid}.tar.gz"
            if src.exists():
                shutil.copyfile(src, cache / f"{cid}.tar.gz")
        shutil.rmtree(tgt.staging, ignore_errors=True)
        tgt.status.phase, tgt.status.endedAt = "COMPLETED", time.time()
        self._targets.pop(tgt.status.id, None)

    async def _on_start(self, tgt: _TargetRun, msg: MigStart) -> None:
        wid, st = tgt.manifest.id, tgt.status

        async def refuse(error: str) -> None:
            await self._send(tgt.source_id, MigStarted(migrationId=st.id, ok=False, error=error))

        if tgt.precopy:
            await refuse("a pre-copy cannot be started")
            return
        if tgt.validated != set(tgt.records):
            await refuse(f"only {len(tgt.validated)} of {len(tgt.records)} checkpoints are validated")
            return
        if tgt.epoch == tgt.prepare_epoch:
            await refuse("the source is not fenced")
            return
        if msg.epoch != tgt.epoch or not self.ctx.authority.check_epoch(wid, msg.epoch):
            await refuse(f"stale epoch {msg.epoch} (expected {tgt.epoch})")
            return

        st.phase = "STARTING_TARGET"
        await self._publish(st)
        granted = started = False
        try:
            code_dir = await asyncio.to_thread(self._commit_staged, tgt)
            self.host.register(tgt.manifest, code_dir)
            st.authority = await self.ctx.authority.grant(wid, self.ctx.device_id, msg.epoch)
            granted = True
            await self._publish(st)  # journal the grant: a restart from here waits for the source
            await self.host.start(wid, restore=True)
            started = True
        except Exception as e:
            log.exception("%s: target start failed", st.id)
            if started:
                await self.host.kill(wid)
            if granted:
                await self.ctx.authority.release(wid)
            if isinstance(e, OSError) and e.errno == errno.ENOSPC:
                why = "the target ran out of disk space"
            else:
                why = _short(str(e) or type(e).__name__, 120)
            await self._discard_target(tgt, f"Could not start the workload: {why}.", notify=False)
            await refuse(why)
            return
        tgt.started = True
        await self._send(tgt.source_id, MigStarted(migrationId=st.id, ok=True))
        shutil.rmtree(tgt.staging, ignore_errors=True)
        st.phase, st.endedAt = "COMPLETED", time.time()
        await self._publish(st)

    def _commit_staged(self, tgt: _TargetRun) -> Path:
        """Validated staging -> checkpoint store, unpacked code and code cache. Returns the code folder."""
        wid = tgt.manifest.id
        self.store.delete(wid)
        for cid, record in tgt.records.items():
            if cid != CODE_UNIT:  # verified on arrival: move, do not re-hash (keeps the freeze short)
                self.store.adopt(wid, cid, tgt.staging / f"{cid}.tar.gz", record)
        code = (tgt.staging / f"{CODE_UNIT}.tar.gz").read_bytes()
        code_dir = self.store.workload_dir(wid) / "code"
        shutil.rmtree(code_dir, ignore_errors=True)
        unpack_unit(code, files_dest=code_dir)
        self.cache_dir(wid).mkdir(parents=True, exist_ok=True)
        (self.cache_dir(wid) / f"{CODE_UNIT}.tar.gz").write_bytes(code)
        return code_dir

    async def _discard_target(self, tgt: _TargetRun, reason: str, notify: bool) -> None:
        """Drop the staged copy. If our copy already started (the source never got mig.started),
        stop it: the source rolled back and keeps running at a newer epoch."""
        if tgt.status.phase in ("ROLLED_BACK",):
            return
        wid = tgt.manifest.id
        if tgt.started:
            await self._kill_local(wid)
            await self.ctx.authority.release(wid)
        shutil.rmtree(tgt.staging, ignore_errors=True)
        if notify:
            with contextlib.suppress(Exception):
                await self._send(tgt.source_id, MigAbort(migrationId=tgt.status.id, reason=reason))
        tgt.status.phase, tgt.status.error, tgt.status.endedAt = "ROLLED_BACK", reason, time.time()
        tgt.status.authority = self.ctx.authority.get(wid)
        await self._publish(tgt.status)
        if tgt.precopy:
            self._targets.pop(tgt.status.id, None)


def _note(status: MigrationStatus, code: str, severity: Literal["pass", "warn", "block"], text: str) -> None:
    status.reasons = [*status.reasons, Reason(code=code, severity=severity, text=text)]


def _metric(
    record: CheckpointRecord,
    stage: Stage,
    chunks: int = 0,
    retries: int = 0,
    ms: float = 0.0,
    skipped: bool = False,
) -> CheckpointMetric:
    mbps = record.sizeBytes * 8 / 1e6 / (ms / 1000) if ms > 0 else 0.0
    return CheckpointMetric(
        id=record.id,
        stage=stage,
        sizeBytes=record.sizeBytes,
        chunks=chunks,
        retries=retries,
        transferMs=round(ms, 2),
        mbps=round(mbps, 2),
        skipped=skipped,
    )


_DIGEST = DigestSigner()


def _short(text: str, limit: int = 160) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _explain(e: BaseException, abort_reason: str | None, phase: Phase) -> tuple[str, str]:
    """(short message for the dashboard, technical detail) for a failed migration."""
    where = phase.lower().replace("_", " ")
    if abort_reason:
        return _short(abort_reason), ""
    if isinstance(e, MigrationError):
        return _short(str(e)), e.detail
    if isinstance(e, TimeoutError):
        return f"The target did not answer in time ({where}).", ""
    if isinstance(e, OSError) and e.errno == errno.ENOSPC:
        return "This device ran out of disk space.", str(e)
    if isinstance(e, ConnectionError | OSError) or "connect" in str(e).lower():
        return f"Lost the link to the target ({where}).", f"{type(e).__name__}: {e}"
    if isinstance(e, KeyError):
        return "The workload is no longer registered on this device.", repr(e)
    return f"Unexpected error ({where}).", f"{type(e).__name__}: {e}"

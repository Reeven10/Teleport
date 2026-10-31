"""Migration manager (P1): source and target sides of checkpointed migration, with rollback.

Source: CONNECTING -> EVALUATING -> (MIGRATE) TRANSFERRING -> VALIDATING -> FENCING ->
STARTING_TARGET -> COMPLETED, or REMOTE_ACCESS, or FAILED (STAY / nothing sent yet), or
ROLLING_BACK -> ROLLED_BACK on any failure, timeout, abort or lost link before mig.started ok.
Authority only moves after every checkpoint is validated and the target confirmed it started.

Besides the user checkpoints, the workload folder travels as the system unit `teleport.code`.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import builtins
import json
import logging
import os
import shutil
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from teleport_sdk.unit import collect_files, pack_unit, unpack_unit

from contract.contract import (
    CheckpointRecord,
    DecisionLog,
    DeviceInfo,
    DeviceLostEvent,
    MigAbort,
    MigChunk,
    MigChunkAck,
    MigFence,
    MigFenced,
    MigPrepare,
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

from ..core.context import Context
from .store import CheckpointStore, ChunkError, Reassembler, iter_chunks, sha256_hex

log = logging.getLogger("teleport.migration")

CODE_UNIT = "teleport.code"
CODE_EXCLUDE = (".teleport-local", "__pycache__", "*.pyc", ".git", "node_modules", ".venv")
TERMINAL: set[Phase] = {"COMPLETED", "ROLLED_BACK", "REMOTE_ACCESS", "FAILED"}


class MigrationError(RuntimeError):
    pass


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
    ack: float = 5.0
    validate: float = 30.0
    checkpoint: float = 10.0
    start: float = 30.0
    retries: int = 3
    window: int = 8
    chunk_delay: float = 0.0  # dev/demo slow motion, TELEPORT_DEV_SLOW_TRANSFER_MS

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
    mailbox: _Mailbox = field(default_factory=_Mailbox)
    task: asyncio.Task[None] | None = None
    abort_reason: str | None = None
    prepared: bool = False
    start_sent: bool = False
    late_abort: str | None = None
    committed: bool = False
    sent: dict[str, CheckpointRecord] = field(default_factory=dict)
    last_publish: float = 0.0


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
    validated: set[str] = field(default_factory=set)
    failed: set[str] = field(default_factory=set)
    owes_validation: bool = True
    started: bool = False


class MigrationManager:
    def __init__(self, ctx: Context, timeouts: Timeouts | None = None) -> None:
        self.ctx = ctx
        self.timeouts = timeouts or Timeouts.from_env()
        self._sources: dict[str, _SourceRun] = {}
        self._targets: dict[str, _TargetRun] = {}
        self._target_lock = asyncio.Lock()
        self._unsubscribe: Callable[[], None] | None = None

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

    async def startup(self) -> None:
        self.ctx.peers.on_message(self._on_peer_message)
        self._unsubscribe = self.ctx.bus.subscribe(DeviceLostEvent, self._on_device_lost)

    async def shutdown(self) -> None:
        if self._unsubscribe:
            self._unsubscribe()
        for run in self._sources.values():
            if run.task and not run.task.done():
                self._abort_source(run, "agent shutting down")
        tasks = [r.task for r in self._sources.values() if r.task and not r.task.done()]
        if tasks:
            await asyncio.wait(tasks, timeout=10)

    # ------------------------------------------------------------------ MigrationManager Protocol

    def workloads(self) -> builtins.list[WorkloadManifest]:
        return self.host.list()

    async def launch_workload(self, manifest_path: str) -> WorkloadManifest:
        return await self.host.launch(manifest_path)

    async def start(self, workload_id: str, target_id: str, trigger: Trigger) -> MigrationStatus:
        if target_id == self.ctx.device_id:
            raise MigrationError("target is this device")
        self.host.manifest(workload_id)  # KeyError if unknown
        for r in self._sources.values():
            if r.status.workloadId == workload_id and r.status.phase not in TERMINAL:
                raise MigrationError(f"{workload_id} is already migrating ({r.status.id})")
        mid = f"mig-{uuid.uuid4().hex[:12]}"
        status = MigrationStatus(
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
        run = _SourceRun(status=status, outgoing=self.store.workload_dir(workload_id) / "outgoing" / mid)
        self._sources[mid] = run
        run.task = asyncio.create_task(self._run_source(run), name=mid)
        return status.model_copy(deep=True)

    async def abort(self, migration_id: str) -> MigrationStatus:
        if src := self._sources.get(migration_id):
            if src.status.phase not in TERMINAL and not src.committed:
                self._abort_source(src, "aborted by user")
                if src.task:
                    await asyncio.wait([src.task], timeout=15)
            return src.status.model_copy(deep=True)
        if tgt := self._targets.get(migration_id):
            async with self._target_lock:
                await self._discard_target(tgt, "aborted by user on target", notify=True)
            return tgt.status.model_copy(deep=True)
        raise KeyError(f"unknown migration {migration_id}")

    def status(self, migration_id: str) -> MigrationStatus | None:
        run = self._sources.get(migration_id) or self._targets.get(migration_id)
        return run.status.model_copy(deep=True) if run else None

    async def wait(self, migration_id: str, timeout: float | None = None) -> MigrationStatus:
        """Wait for a source migration to finish (tests, scripts)."""
        run = self._sources[migration_id]
        if run.task:
            await asyncio.wait_for(asyncio.shield(run.task), timeout)
        return run.status.model_copy(deep=True)

    def list(self) -> builtins.list[MigrationStatus]:
        runs = [r.status for r in self._sources.values()] + [r.status for r in self._targets.values()]
        return [s.model_copy(deep=True) for s in sorted(runs, key=lambda s: s.startedAt)]

    # ------------------------------------------------------------------ shared helpers

    async def _publish(self, status: MigrationStatus) -> None:
        await self.ctx.bus.publish(MigrationStatusEvent(status=status.model_copy(deep=True)))

    async def _send(self, device_id: str, msg: PeerMessage) -> None:
        await self.ctx.peers.send(device_id, msg)

    def _find_device(self, device_id: str) -> DeviceInfo:
        for d in [*self.ctx.devices.list_devices(), *self.ctx.peers.list_peers()]:
            if d.id == device_id:
                return d
        raise MigrationError(f"unknown target device {device_id}")

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
                await self._finish(run, "FAILED", f"Decision STAY: {blocks or 'no viable option'}")
            else:
                await self._migrate(run, manifest)
        except Exception as e:
            reason = run.abort_reason or (str(e) or type(e).__name__)
            if isinstance(e, TimeoutError) and not run.abort_reason:
                reason = f"timed out during {st.phase}"
            if run.committed:
                log.exception("%s: error after the target took over", st.id)
                await self._finish(run, "COMPLETED", f"cleanup after handover failed: {reason}")
            elif not run.prepared:
                await self._finish(run, "FAILED", reason)
            else:
                await self._rollback(run, reason)

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

    def _snapshot(self, run: _SourceRun, ids: builtins.list[str]) -> builtins.list[CheckpointRecord]:
        """Freeze the current units into outgoing/ so later writes cannot change what is sent."""
        wid = run.status.workloadId
        run.outgoing.mkdir(parents=True, exist_ok=True)
        out: builtins.list[CheckpointRecord] = []
        for cid in ids:
            data, rec = self.store.read(wid, cid), self.store.record(wid, cid)
            if data is None or rec is None:
                raise MigrationError(f"checkpoint {cid!r} has never been saved")
            (run.outgoing / f"{cid}.tar.gz").write_bytes(data)
            out.append(
                CheckpointRecord(
                    id=cid, seq=rec.seq, sizeBytes=len(data), sha256=sha256_hex(data), createdAt=rec.createdAt
                )
            )
        return out

    def _pack_code(self, run: _SourceRun) -> CheckpointRecord:
        wid = run.status.workloadId
        files = collect_files(["."], self.host.source_dir(wid), exclude=CODE_EXCLUDE)
        data = pack_unit(None, files)
        run.outgoing.mkdir(parents=True, exist_ok=True)
        (run.outgoing / f"{CODE_UNIT}.tar.gz").write_bytes(data)
        return CheckpointRecord(
            id=CODE_UNIT, seq=0, sizeBytes=len(data), sha256=sha256_hex(data), createdAt=time.time()
        )

    async def _migrate(self, run: _SourceRun, manifest: WorkloadManifest) -> None:
        st, t, auth = run.status, self.timeouts, self.ctx.authority
        wid, target = st.workloadId, st.targetId
        lease = auth.get(wid)
        if not auth.may_run(wid):
            raise MigrationError(f"this device does not hold {wid} ({lease.state}, holder {lease.holder})")
        if lease.state == "TARGET":  # it arrived here by migration; now it leaves as SOURCE
            lease = await auth.claim(wid, self.ctx.device_id)
        user_ids = [c.id for c in manifest.checkpoints]

        # Live snapshot: the workload keeps running and keeps authority.
        await self.host.request_checkpoint(wid, t.checkpoint)
        records = [self._pack_code(run), *self._snapshot(run, user_ids)]
        for r in records:
            run.sent[r.id] = r
            self._mark(run, r)
        st.bytesTotal = sum(r.sizeBytes for r in records)
        payload = prepare_payload(st.id, manifest, records, lease.epoch)
        self._check(run)
        run.prepared = True
        await self._send(
            target,
            MigPrepare(
                migrationId=st.id,
                manifest=manifest,
                checkpoints=records,
                epoch=lease.epoch,
                signature=self.signer.sign_manifest(payload),
            ),
        )
        ready = await run.mailbox.expect(("ready",), t.ready)
        assert isinstance(ready, MigReady)
        if not ready.ok:
            st.reasons = [*st.reasons, *ready.reasons]
            raise MigrationError("target refused: " + "; ".join(r.text for r in ready.reasons))

        await self._phase(run, "TRANSFERRING")
        for r in records:
            await self._transfer(run, r, lease.epoch)
        await self._phase(run, "VALIDATING")
        await self._await_validated(run)

        # Cutover. Final checkpoint while still running, then fence.
        await self.host.request_checkpoint(wid, t.checkpoint)
        self._check(run)
        fence_start = time.monotonic()
        await self._phase(run, "FENCING")
        self.host.pause(wid)
        fenced = await auth.fence(wid)
        st.authority = fenced
        await self._send(target, MigFence(migrationId=st.id, epoch=fenced.epoch))
        await self.host.request_checkpoint(wid, t.checkpoint)  # paused: manifest paths, now consistent
        current = {r.id: r.sha256 for r in self.store.records(wid)}
        changed_ids = [cid for cid in user_ids if current.get(cid) != run.sent[cid].sha256]
        changed = self._snapshot(run, changed_ids)
        for r in changed:
            run.sent[r.id] = r
            self._mark(run, r, sent=False, validated=False)
        st.bytesTotal += sum(r.sizeBytes for r in changed)
        await self._publish(st)
        await self._send(target, MigFenced(migrationId=st.id, changed=changed))
        for r in changed:
            await self._transfer(run, r, fenced.epoch)
        await self._await_validated(run)

        self._check(run)
        run.start_sent = True  # from here an abort must wait for the target's answer
        await self._phase(run, "STARTING_TARGET")
        await self._send(target, MigStart(migrationId=st.id, epoch=fenced.epoch))
        started = await run.mailbox.expect(("started",), t.start)
        assert isinstance(started, MigStarted)
        if not started.ok:
            raise MigrationError(
                run.late_abort or f"target failed to start: {started.error or 'unknown error'}"
            )
        if run.late_abort:
            st.reasons = [
                *st.reasons,
                Reason(
                    code="abort.late",
                    severity="warn",
                    text=f"Too late to abort ({run.late_abort}): the target had already started.",
                ),
            ]

        run.committed = True
        st.interruptionMs = round((time.monotonic() - fence_start) * 1000, 1)
        await auth.grant(wid, target, fenced.epoch)
        await self.host.kill(wid)
        await self._finish(run, "COMPLETED")

    async def _transfer(self, run: _SourceRun, record: CheckpointRecord, epoch: int) -> None:
        st, t = run.status, self.timeouts
        chunks = list(iter_chunks(run.outgoing / f"{record.id}.tar.gz"))
        window = asyncio.Semaphore(t.window)

        async def send_chunk(index: int, total: int, data: bytes, digest: str) -> None:
            async with window:
                if t.chunk_delay:
                    await asyncio.sleep(t.chunk_delay)
                key: Key = ("ack", record.id, str(index))
                for _attempt in range(t.retries + 1):
                    self._check(run)
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
                raise MigrationError(f"chunk {index} of {record.id} failed after {t.retries + 1} attempts")

        try:
            async with asyncio.TaskGroup() as tg:
                for c in chunks:
                    tg.create_task(send_chunk(c.index, c.total, c.data, c.sha256))
        except BaseExceptionGroup as eg:
            raise eg.exceptions[0] from None
        self._mark(run, record, sent=True)
        await self._progress(run, force=True)

    async def _await_validated(self, run: _SourceRun) -> None:
        msg = await run.mailbox.expect(("validated",), self.timeouts.validate)
        assert isinstance(msg, MigValidated)
        if not msg.ok:
            raise MigrationError(f"target failed to validate {', '.join(msg.failed or []) or 'checkpoints'}")
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
            if self.host.status(wid).state == "paused":
                self.host.resume(wid)
        except Exception:
            log.exception("%s: could not resume the source copy", st.id)
        await self._finish(run, "ROLLED_BACK", reason)

    # ------------------------------------------------------------------ peer messages

    async def _on_peer_message(self, from_id: str, msg: PeerMessage) -> None:
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
                self._abort_source(src, f"target aborted: {msg.reason}", hard=True)
            return
        if isinstance(msg, MigPrepare | MigChunk | MigFence | MigFenced | MigStart | MigAbort):
            async with self._target_lock:
                await self._on_target_message(from_id, msg)

    async def _on_device_lost(self, event: DeviceLostEvent) -> None:
        for src in self._sources.values():
            if src.status.targetId == event.deviceId and src.status.phase not in TERMINAL:
                if not src.committed:
                    self._abort_source(src, "link to target lost", hard=True)
        async with self._target_lock:
            for tgt in list(self._targets.values()):
                if tgt.source_id == event.deviceId and not tgt.started and tgt.status.phase not in TERMINAL:
                    await self._discard_target(tgt, "link to source lost", notify=False)

    # ------------------------------------------------------------------ target side

    async def _on_target_message(self, src: str, msg: PeerMessage) -> None:
        if isinstance(msg, MigPrepare):
            await self._on_prepare(src, msg)
            return
        tgt = self._targets.get(msg.migrationId)  # type: ignore[union-attr]
        if tgt is None or tgt.source_id != src or tgt.status.phase in TERMINAL:
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
                tgt.parts[rec.id] = Reassembler(rec)
                tgt.validated.discard(rec.id)
                tgt.failed.discard(rec.id)
                (tgt.staging / f"{rec.id}.tar.gz").unlink(missing_ok=True)
            tgt.owes_validation = True
            await self._maybe_validated(tgt)
        elif isinstance(msg, MigStart):
            await self._on_start(tgt, msg)
        elif isinstance(msg, MigAbort):
            await self._discard_target(tgt, f"source aborted: {msg.reason}", notify=False)

    def _local_copy_active(self, workload_id: str) -> bool:
        try:
            return self.host.status(workload_id).state in ("running", "paused")
        except KeyError:
            return False

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
        if self.ctx.authority.may_run(wid) or self._local_copy_active(wid):
            block("running", f"{manifest.name} is already running on this device.")
        ids = {r.id for r in msg.checkpoints}
        missing = [c.id for c in manifest.checkpoints if c.id not in ids]
        if missing or CODE_UNIT not in ids:
            block("checkpoints", f"Checkpoints missing from the offer: {', '.join(missing) or CODE_UNIT}.")
        if msg.migrationId in self._targets:
            block("duplicate", "This migration was already offered.")
        if reasons:
            await self._send(src, MigReady(migrationId=msg.migrationId, ok=False, reasons=reasons))
            return

        staging = self.store.workload_dir(wid) / "staging" / msg.migrationId
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        records = {r.id: r for r in msg.checkpoints}
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
            bytesTotal=sum(r.sizeBytes for r in records.values()),
            bytesDone=0,
            authority=self.ctx.authority.get(wid),
            startedAt=time.time(),
        )
        self._targets[msg.migrationId] = _TargetRun(
            status=status,
            manifest=manifest,
            source_id=src,
            prepare_epoch=msg.epoch,
            epoch=msg.epoch,
            staging=staging,
            records=records,
            parts={cid: Reassembler(r) for cid, r in records.items()},
        )
        ok = Reason(code="ready", severity="pass", text="Target staged the migration.")
        await self._send(src, MigReady(migrationId=msg.migrationId, ok=True, reasons=[ok]))
        await self._publish(status)

    async def _ack(self, src: str, msg: MigChunk, ok: bool) -> None:
        ack = MigChunkAck(migrationId=msg.migrationId, checkpointId=msg.checkpointId, index=msg.index, ok=ok)
        await self._send(src, ack)

    async def _on_chunk(self, tgt: _TargetRun, msg: MigChunk) -> None:
        cid = msg.checkpointId
        if msg.epoch < tgt.epoch or cid not in tgt.parts:
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
                unit = part.finalize()
                unpack_unit(unit)
                (tgt.staging / f"{cid}.tar.gz").write_bytes(unit)
                tgt.validated.add(cid)
            except (ChunkError, ValueError) as e:
                log.warning("%s: checkpoint %s failed validation: %s", tgt.status.id, cid, e)
                tgt.failed.add(cid)
            self._target_marks(tgt)
            await self._maybe_validated(tgt)

    def _target_marks(self, tgt: _TargetRun) -> None:
        tgt.status.checkpoints = [
            r.model_copy(update={"sent": tgt.parts[cid].complete, "validated": cid in tgt.validated})
            for cid, r in tgt.records.items()
        ]

    async def _maybe_validated(self, tgt: _TargetRun) -> None:
        if not tgt.owes_validation or len(tgt.validated | tgt.failed) < len(tgt.records):
            return
        tgt.owes_validation = False
        failed = sorted(tgt.failed)
        reply = MigValidated(migrationId=tgt.status.id, ok=not failed, failed=failed or None)
        await self._send(tgt.source_id, reply)
        tgt.status.phase = "VALIDATING"
        self._target_marks(tgt)
        await self._publish(tgt.status)

    async def _on_start(self, tgt: _TargetRun, msg: MigStart) -> None:
        wid, st = tgt.manifest.id, tgt.status

        async def refuse(error: str) -> None:
            await self._send(tgt.source_id, MigStarted(migrationId=st.id, ok=False, error=error))

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
            self.store.delete(wid)
            for cid in tgt.records:
                if cid != CODE_UNIT:
                    self.store.put(wid, cid, (tgt.staging / f"{cid}.tar.gz").read_bytes())
            code_dir = self.store.workload_dir(wid) / "code"
            shutil.rmtree(code_dir, ignore_errors=True)
            unpack_unit((tgt.staging / f"{CODE_UNIT}.tar.gz").read_bytes(), files_dest=code_dir)
            self.host.register(tgt.manifest, code_dir)
            st.authority = await self.ctx.authority.grant(wid, self.ctx.device_id, msg.epoch)
            granted = True
            await self.host.start(wid, restore=True)
            started = True
        except Exception as e:
            log.exception("%s: target start failed", st.id)
            if started:
                await self.host.kill(wid)
            if granted:
                await self.ctx.authority.release(wid)
            await self._discard_target(tgt, f"start failed: {e}", notify=False)
            await refuse(str(e) or type(e).__name__)
            return
        tgt.started = True
        await self._send(tgt.source_id, MigStarted(migrationId=st.id, ok=True))
        shutil.rmtree(tgt.staging, ignore_errors=True)
        st.phase, st.endedAt = "COMPLETED", time.time()
        await self._publish(st)

    async def _discard_target(self, tgt: _TargetRun, reason: str, notify: bool) -> None:
        """Drop the staged copy. If our copy already started (the source never got mig.started),
        stop it: the source rolled back and keeps running at a newer epoch."""
        if tgt.status.phase in ("ROLLED_BACK",):
            return
        wid = tgt.manifest.id
        if tgt.started:
            await self.host.kill(wid)
            await self.ctx.authority.release(wid)
        shutil.rmtree(tgt.staging, ignore_errors=True)
        if notify:
            try:
                await self._send(tgt.source_id, MigAbort(migrationId=tgt.status.id, reason=reason))
            except Exception:
                pass
        tgt.status.phase, tgt.status.error, tgt.status.endedAt = "ROLLED_BACK", reason, time.time()
        tgt.status.authority = self.ctx.authority.get(wid)
        await self._publish(tgt.status)


_DIGEST = DigestSigner()

"""Workload runner (P1): runs manifests as subprocesses and is the agent side of the SDK.

Per workload: TELEPORT_HOME/workloads/<id>/{work/, restore/, logs/run.log, checkpoints/}.
`work/` is a copy of the manifest folder; existing checkpoints are restored into it before start
(files in place, state under restore/ via TELEPORT_RESTORE_DIR).
"""

from __future__ import annotations

import asyncio
import builtins
import collections
import contextlib
import hmac
import logging
import os
import secrets
import shlex
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import psutil
from pydantic import BaseModel

from contract.contract import CheckpointRecord, RunState, WorkloadManifest, WorkloadRun

from ..migration.store import CheckpointStore
from .context import Context
from .manifest import load_manifest
from .settings import REPO_ROOT

SDK_DIR = REPO_ROOT / "sdk"
LOG_TAIL = 200


log = logging.getLogger("teleport.workloads")


class WorkloadError(RuntimeError):
    pass


class _Registered(BaseModel):
    manifest: WorkloadManifest
    sourceDir: str


class _RunFile(BaseModel):
    pid: int
    createTime: float


@dataclass
class _Run:
    manifest: WorkloadManifest
    source_dir: Path
    state: RunState = "idle"
    proc: subprocess.Popen[str] | None = None
    token: str = ""
    exit_code: int | None = None
    started_at: float | None = None
    restored: list[str] = field(default_factory=list)
    log_tail: collections.deque[str] = field(default_factory=lambda: collections.deque(maxlen=LOG_TAIL))
    fence_seq: int = 0
    fenced_seq: int = 0
    stop_requested: bool = False


def _command(manifest: WorkloadManifest) -> list[str]:
    argv = shlex.split(manifest.command, posix=True)
    if argv and argv[0] in ("python", "python3"):
        argv[0] = sys.executable  # run Python workloads with the agent's interpreter
    return argv


class WorkloadRunner:
    def __init__(self, ctx: Context, store: CheckpointStore) -> None:
        self.ctx = ctx
        self.store = store
        self._runs: dict[str, _Run] = {}
        self._interrupted: set[str] = set()
        self._shutting_down = False
        self._load_registry()

    # ------------------------------------------------------------------ registry
    # Each registered workload is saved to workloads/<id>/workload.json and each running process to
    # run.json, so a restarted agent knows its workloads and can kill orphans of the old process.

    def _load_registry(self) -> None:
        if not self.store.root.is_dir():
            return
        for path in sorted(self.store.root.glob("*/workload.json")):
            try:
                entry = _Registered.model_validate_json(path.read_text("utf-8"))
            except ValueError as e:
                log.warning("ignoring %s: %s", path, e)
                continue
            self._runs[entry.manifest.id] = _Run(manifest=entry.manifest, source_dir=Path(entry.sourceDir))

    def interrupted(self) -> set[str]:
        """Workloads that were running when the previous agent process stopped (crash or shutdown)."""
        return set(self._interrupted)

    def _kill_orphans(self) -> builtins.list[int]:
        killed: builtins.list[int] = []
        for path in self.store.root.glob("*/run.json") if self.store.root.is_dir() else []:
            if path.parent.name in self._runs:
                self._interrupted.add(path.parent.name)
            try:
                info = _RunFile.model_validate_json(path.read_text("utf-8"))
                proc = psutil.Process(info.pid)
                if abs(proc.create_time() - info.createTime) < 1.0:  # same process, not a reused pid
                    for p in [*proc.children(recursive=True), proc]:
                        p.kill()
                    killed.append(info.pid)
            except (ValueError, psutil.Error):
                pass
            path.unlink(missing_ok=True)
        return killed

    def list(self) -> list[WorkloadManifest]:
        return [r.manifest for r in self._runs.values()]

    def manifest(self, workload_id: str) -> WorkloadManifest:
        return self._run(workload_id).manifest

    def source_dir(self, workload_id: str) -> Path:
        return self._run(workload_id).source_dir

    def register(self, manifest: WorkloadManifest, source_dir: Path) -> None:
        run = self._runs.get(manifest.id)
        if run and run.state in ("running", "paused"):
            raise WorkloadError(f"workload {manifest.id} is already running")
        if self.store.root.resolve().is_relative_to(source_dir.resolve()):
            raise WorkloadError(f"workload folder {source_dir} must not contain TELEPORT_HOME")
        self._runs[manifest.id] = _Run(manifest=manifest, source_dir=source_dir)
        folder = self.store.workload_dir(manifest.id)
        folder.mkdir(parents=True, exist_ok=True)
        entry = _Registered(manifest=manifest, sourceDir=str(source_dir.resolve()))
        (folder / "workload.json").write_text(entry.model_dump_json(), "utf-8")

    async def launch(self, manifest_path: str) -> WorkloadManifest:
        """Load teleport.yaml (file or folder), register it, claim authority and start it."""
        manifest, source_dir = load_manifest(manifest_path)
        self.register(manifest, source_dir)
        await self.ctx.authority.claim(manifest.id, self.ctx.device_id)
        await self.start(manifest.id)
        return manifest

    def _run(self, workload_id: str) -> _Run:
        try:
            run = self._runs[workload_id]
        except KeyError:
            raise KeyError(f"unknown workload {workload_id}") from None
        self._refresh(run)
        return run

    def _refresh(self, run: _Run) -> None:
        if run.proc is not None and run.state in ("running", "paused"):
            code = run.proc.poll()
            if code is not None:
                run.exit_code = code
                run.state = "stopped" if run.stop_requested else "exited"
                if not self._shutting_down:  # it ended for good: do not relaunch after a restart
                    (self.store.workload_dir(run.manifest.id) / "run.json").unlink(missing_ok=True)

    def workdir(self, workload_id: str) -> Path:
        return self.store.workload_dir(workload_id) / "work"

    def status(self, workload_id: str) -> WorkloadRun:
        run = self._run(workload_id)
        return WorkloadRun(
            workloadId=workload_id,
            state=run.state,
            pid=run.proc.pid if run.proc and run.state in ("running", "paused") else None,
            exitCode=run.exit_code,
            startedAt=run.started_at,
            restored=list(run.restored),
            logTail=list(run.log_tail)[-50:],
        )

    def runs(self) -> builtins.list[WorkloadRun]:
        return [self.status(wid) for wid in self._runs]

    # ------------------------------------------------------------------ lifecycle

    async def start(self, workload_id: str, restore: bool = True) -> WorkloadRun:
        run = self._run(workload_id)
        if run.state in ("running", "paused"):
            raise WorkloadError(f"workload {workload_id} is already running")
        wdir = self.store.workload_dir(workload_id)
        work, restore_dir, logs = wdir / "work", wdir / "restore", wdir / "logs"
        ignore = shutil.ignore_patterns(".teleport-local", "__pycache__", "*.pyc")
        await asyncio.to_thread(shutil.copytree, run.source_dir, work, dirs_exist_ok=True, ignore=ignore)
        run.restored = (
            await asyncio.to_thread(self.store.extract, workload_id, work, restore_dir) if restore else []
        )
        logs.mkdir(parents=True, exist_ok=True)

        run.token = secrets.token_urlsafe(24)
        env = dict(os.environ)
        env.update(
            TELEPORT_AGENT_URL=f"http://127.0.0.1:{self.ctx.settings.port}",
            TELEPORT_WORKLOAD_ID=workload_id,
            TELEPORT_RUN_TOKEN=run.token,
            PYTHONUNBUFFERED="1",
            PYTHONPATH=os.pathsep.join(p for p in (str(SDK_DIR), env.get("PYTHONPATH")) if p),
        )
        env.pop("TELEPORT_RESTORE_DIR", None)
        if run.restored:
            env["TELEPORT_RESTORE_DIR"] = str(restore_dir)

        flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
        # Popen + reader thread, not asyncio subprocesses: works on any loop (incl. Windows selector).
        run.proc = subprocess.Popen(  # noqa: ASYNC220
            _command(run.manifest),
            cwd=work,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=flags,
            start_new_session=sys.platform != "win32",
        )
        run.state, run.exit_code, run.started_at = "running", None, time.time()
        with contextlib.suppress(psutil.Error):
            created = psutil.Process(run.proc.pid).create_time()
            (wdir / "run.json").write_text(_RunFile(pid=run.proc.pid, createTime=created).model_dump_json())
        run.stop_requested, run.fence_seq, run.fenced_seq = False, 0, 0
        run.log_tail.clear()
        threading.Thread(target=self._pump_logs, args=(run, logs / "run.log"), daemon=True).start()
        return self.status(workload_id)

    @staticmethod
    def _pump_logs(run: _Run, log_path: Path) -> None:
        proc = run.proc
        assert proc is not None and proc.stdout is not None
        with log_path.open("a", encoding="utf-8") as log:
            log.write(f"--- start pid={proc.pid} at {time.ctime()}\n")
            for line in proc.stdout:
                log.write(line)
                log.flush()
                run.log_tail.append(line.rstrip("\n"))

    def _processes(self, run: _Run) -> builtins.list[psutil.Process]:
        if run.proc is None:
            return []
        try:
            parent = psutil.Process(run.proc.pid)
            return [parent, *parent.children(recursive=True)]
        except psutil.NoSuchProcess:
            return []

    def pause(self, workload_id: str) -> WorkloadRun:
        run = self._run(workload_id)
        if run.state != "running":
            raise WorkloadError(f"cannot pause {workload_id} in state {run.state}")
        for p in self._processes(run):
            p.suspend()
        run.state = "paused"
        return self.status(workload_id)

    def resume(self, workload_id: str) -> WorkloadRun:
        run = self._run(workload_id)
        if run.state != "paused":
            raise WorkloadError(f"cannot resume {workload_id} in state {run.state}")
        for p in self._processes(run):
            p.resume()
        run.state = "running"
        return self.status(workload_id)

    async def request_checkpoint(
        self, workload_id: str, timeout: float = 10.0
    ) -> builtins.list[CheckpointRecord]:
        """Final checkpoint: ask the SDK (on_fence callbacks), wait for its ack, then pack manifest paths.

        Raises WorkloadError if the workload did not acknowledge within `timeout`.
        """
        run = self._run(workload_id)
        if run.state == "running":
            run.fence_seq += 1
            seq, deadline = run.fence_seq, time.monotonic() + timeout
            while run.fenced_seq < seq:
                self._refresh(run)
                if run.state != "running":
                    break
                if time.monotonic() > deadline:
                    raise WorkloadError(f"{workload_id} did not acknowledge the checkpoint request")
                await asyncio.sleep(0.05)
        work = self.workdir(workload_id)
        for ck in run.manifest.checkpoints:
            if ck.paths:
                await asyncio.to_thread(self.store.pack_paths, workload_id, ck.id, work, ck.paths)
        return self.store.records(workload_id)

    async def terminate(self, workload_id: str, grace: float = 5.0) -> WorkloadRun:
        """Cooperative stop (SDK should_stop), then terminate, then kill."""
        run = self._run(workload_id)
        if run.state not in ("running", "paused") or run.proc is None:
            return self.status(workload_id)
        run.stop_requested = True
        if run.state == "paused":
            self.resume(workload_id)
        proc = run.proc
        if not await self._wait(proc, grace):
            for p in reversed(self._processes(run)):
                p.terminate()
            if not await self._wait(proc, 2.0):
                for p in reversed(self._processes(run)):
                    p.kill()
                await self._wait(proc, 2.0)
        self._refresh(run)
        return self.status(workload_id)

    async def kill(self, workload_id: str) -> WorkloadRun:
        """Hard stop without resuming first (a fenced, paused copy must never run another step)."""
        run = self._run(workload_id)
        if run.state not in ("running", "paused") or run.proc is None:
            return self.status(workload_id)
        run.stop_requested = True
        for p in reversed(self._processes(run)):
            p.kill()
        await self._wait(run.proc, 5.0)
        self._refresh(run)
        return self.status(workload_id)

    @staticmethod
    async def _wait(proc: subprocess.Popen[str], timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while proc.poll() is None:
            if time.monotonic() > deadline:
                return False
            await asyncio.sleep(0.05)
        return True

    # ------------------------------------------------------------------ SDK side

    def check_token(self, workload_id: str, token: str) -> bool:
        run = self._runs.get(workload_id)
        return bool(run and run.token and hmac.compare_digest(run.token, token))

    def control(self, workload_id: str) -> dict[str, int | bool]:
        run = self._run(workload_id)
        return {"fenceSeq": run.fence_seq, "stop": run.stop_requested}

    def ack_fence(self, workload_id: str, seq: int) -> None:
        run = self._run(workload_id)
        run.fenced_seq = max(run.fenced_seq, min(seq, run.fence_seq))

    async def startup(self) -> None:
        if killed := self._kill_orphans():
            log.warning(
                "killed %d workload process(es) left over from a previous agent: %s", len(killed), killed
            )

    async def shutdown(self) -> None:
        self._shutting_down = True  # keep run.json: workloads stopped by shutdown resume on restart
        await asyncio.gather(*(self.terminate(wid, grace=2.0) for wid in list(self._runs)))

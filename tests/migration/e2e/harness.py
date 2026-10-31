"""Real agents as subprocesses (`python -m teleport`, like `npm run dev:two`), driven over HTTP/WS."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import psutil
from websockets.sync.client import ClientConnection, connect

REPO = Path(__file__).resolve().parents[3]
COUNTER_JOB = REPO / "tests" / "fixtures" / "counter_job"
DEV_PIN = "424242"
TERMINAL = {"COMPLETED", "ROLLED_BACK", "REMOTE_ACCESS", "FAILED"}


def wait_until(cond: Callable[[], Any], timeout: float = 30.0, what: str = "condition") -> Any:
    deadline = time.monotonic() + timeout
    while True:
        value = cond()
        if value:
            return value
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out after {timeout}s waiting for {what}")
        time.sleep(0.1)


class Agent:
    def __init__(self, name: str, port: int, home: Path, profile: str, env: dict[str, str]) -> None:
        self.name, self.port, self.home = name, port, home
        self.url = f"http://127.0.0.1:{port}"
        home.mkdir(parents=True, exist_ok=True)
        self.log_path = home / "agent.log"
        full_env = {**os.environ, "TELEPORT_DEV_PIN": DEV_PIN, **env}
        full_env.pop("TELEPORT_FORCE_LINK", None)
        cmd = [
            sys.executable, "-m", "teleport",
            "--port", str(port), "--home", str(home), "--sim-profile", profile, "--name", name,
        ]  # fmt: skip
        self._log = self.log_path.open("w", encoding="utf-8")
        self.proc = subprocess.Popen(cmd, cwd=REPO, env=full_env, stdout=self._log, stderr=subprocess.STDOUT)
        self.http = httpx.Client(base_url=self.url, timeout=15)
        wait_until(self._healthy, timeout=60, what=f"{name} /api/health")
        self.device_id: str = self.get("/api/health")["deviceId"]

    def _healthy(self) -> bool:
        if self.proc.poll() is not None:
            raise AssertionError(f"{self.name} exited:\n{self.log_path.read_text()[-3000:]}")
        try:
            return self.http.get("/api/health").status_code == 200
        except httpx.HTTPError:
            return False

    def get(self, path: str) -> Any:
        res = self.http.get(path)
        assert res.status_code == 200, f"GET {path}: {res.status_code} {res.text}"
        return res.json()

    def post(self, path: str, body: dict[str, Any] | None = None, expect: int = 200) -> Any:
        res = self.http.post(path, json=body or {})
        assert res.status_code == expect, f"POST {path}: {res.status_code} {res.text}"
        return res.json()

    def run(self, workload_id: str) -> dict[str, Any] | None:
        return next((r for r in self.get("/api/workloads/runs") if r["workloadId"] == workload_id), None)

    def migration(self, migration_id: str) -> dict[str, Any] | None:
        return next((m for m in self.get("/api/migrations") if m["id"] == migration_id), None)

    def wait_migration(self, migration_id: str, timeout: float = 60) -> dict[str, Any]:
        def done() -> dict[str, Any] | None:
            m = self.migration(migration_id)
            return m if m and m["phase"] in TERMINAL else None

        result: dict[str, Any] = wait_until(done, timeout, f"migration {migration_id} to finish")
        return result

    def kill(self) -> None:
        """Hard kill, like a crash or pulled plug: the agent and every child it started."""
        try:
            parent = psutil.Process(self.proc.pid)
            for p in [*parent.children(recursive=True), parent]:
                p.kill()
        except psutil.NoSuchProcess:
            pass
        self.proc.wait(10)

    def close(self) -> None:
        if self.proc.poll() is None:
            self.kill()
        self.http.close()
        self._log.close()


def pair(a: Agent, b: Agent) -> dict[str, Any]:
    """Pair A with B using B's PIN, the way the dashboard's Pair dialog does."""
    pin = b.get("/api/pair")["pin"]
    device: dict[str, Any] = a.post("/api/pair", {"addr": f"127.0.0.1:{b.port}", "pin": pin})
    wait_until(lambda: any(d["id"] == a.device_id for d in b.get("/api/devices")), what="B to know A")
    return device


class EventStream:
    """Collects every BusEvent from an agent's /ws/events on a background thread."""

    def __init__(self, agent: Agent) -> None:
        self.events: list[dict[str, Any]] = []
        self._url = f"ws://127.0.0.1:{agent.port}/ws/events"
        self._ws: ClientConnection | None = None
        self._open = threading.Event()
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()
        assert self._open.wait(10), "could not open /ws/events"

    def _read(self) -> None:
        try:
            with connect(self._url, max_size=None) as ws:
                self._ws = ws
                self._open.set()
                for raw in ws:
                    self.events.append(json.loads(raw))
        except Exception:
            self._open.set()

    def of(self, kind: str) -> list[dict[str, Any]]:
        return [e for e in list(self.events) if e["t"] == kind]

    def close(self) -> None:
        if self._ws is not None:
            self._ws.close()
        self._thread.join(5)

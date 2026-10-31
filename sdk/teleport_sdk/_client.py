"""SDK client. Agent mode when TELEPORT_AGENT_URL / TELEPORT_WORKLOAD_ID / TELEPORT_RUN_TOKEN are set
(the workload runner sets them), otherwise standalone mode writing to TELEPORT_LOCAL_DIR
(default ./.teleport-local). Standard library only.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import threading
import traceback
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from .unit import State, collect_files, decode_state, pack_unit, unpack_unit

FenceCallback = Callable[[], None]


class TeleportError(RuntimeError):
    pass


class Client:
    def __init__(
        self,
        agent_url: str | None = None,
        workload_id: str | None = None,
        token: str | None = None,
        restore_dir: str | Path | None = None,
        local_dir: str | Path | None = None,
        poll_interval: float = 0.25,
    ) -> None:
        self.agent_url = agent_url.rstrip("/") if agent_url else None
        self.workload_id = workload_id
        self.token = token
        self.restore_dir = Path(restore_dir) if restore_dir else None
        self.local_dir = Path(local_dir or ".teleport-local")
        self.poll_interval = poll_interval
        self._fence_callbacks: list[FenceCallback] = []
        self._stop = threading.Event()
        self._closed = threading.Event()
        self._handled_fence = 0
        self._poller: threading.Thread | None = None

    @classmethod
    def from_env(cls) -> Client:
        env = os.environ
        return cls(
            agent_url=env.get("TELEPORT_AGENT_URL"),
            workload_id=env.get("TELEPORT_WORKLOAD_ID"),
            token=env.get("TELEPORT_RUN_TOKEN"),
            restore_dir=env.get("TELEPORT_RESTORE_DIR"),
            local_dir=env.get("TELEPORT_LOCAL_DIR"),
        )

    @property
    def standalone(self) -> bool:
        return not (self.agent_url and self.workload_id and self.token)

    # ------------------------------------------------------------------ public API

    def checkpoint(
        self, checkpoint_id: str, state: State | None = None, files: Iterable[str | Path] | None = None
    ) -> dict[str, Any]:
        """Save one checkpoint unit. `files` are paths relative to the working folder."""
        unit = pack_unit(state, collect_files(files or [], Path.cwd()))
        if self.standalone:
            path = self.local_dir / "checkpoints" / f"{checkpoint_id}.tar.gz"
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(unit)
            tmp.replace(path)
            return {"id": checkpoint_id, "sizeBytes": len(unit), "standalone": True}
        result: dict[str, Any] = self._request(
            "POST", f"/checkpoints/{checkpoint_id}", unit, "application/gzip"
        )
        return result

    def restore(self, checkpoint_id: str) -> State | None:
        """State of a saved checkpoint (files are restored in place), or None if there is none."""
        if not self.standalone:
            if self.restore_dir is None:
                return None
            folder = self.restore_dir / checkpoint_id
            if not folder.is_dir():
                return None
            for name in ("state.json", "state.bin"):
                if (folder / name).exists():
                    return decode_state(name, (folder / name).read_bytes())
            return {}
        path = self.local_dir / "checkpoints" / f"{checkpoint_id}.tar.gz"
        if not path.exists():
            return None
        state_name, raw = unpack_unit(path.read_bytes(), files_dest=Path.cwd())
        return decode_state(state_name, raw)

    def on_fence(self, callback: FenceCallback) -> None:
        """Run `callback` (on a background thread) when the agent asks for a final checkpoint."""
        self._fence_callbacks.append(callback)

    def should_stop(self) -> bool:
        return self._stop.is_set()

    def request_stop(self) -> None:
        self._stop.set()

    def close(self) -> None:
        self._closed.set()

    # ------------------------------------------------------------------ agent link

    def start(self) -> None:
        if threading.current_thread() is threading.main_thread():
            try:
                signal.signal(signal.SIGTERM, lambda *_: self._stop.set())
            except (ValueError, OSError):
                pass
        if not self.standalone and self._poller is None:
            self._poller = threading.Thread(target=self._poll, name="teleport-sdk", daemon=True)
            self._poller.start()

    def _request(self, method: str, path: str, body: bytes | None = None, ctype: str = "") -> Any:
        url = f"{self.agent_url}/api/sdk/workloads/{self.workload_id}{path}"
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("Authorization", f"Bearer {self.token}")
        if ctype:
            req.add_header("Content-Type", ctype)
        try:
            with urllib.request.urlopen(req, timeout=10) as res:
                return json.loads(res.read() or b"null")
        except urllib.error.HTTPError as e:
            raise TeleportError(f"{method} {path}: {e.code} {e.read().decode(errors='replace')}") from e
        except OSError as e:
            raise TeleportError(f"{method} {path}: agent unreachable ({e})") from e

    def _poll(self) -> None:
        while not self._closed.wait(self.poll_interval):
            try:
                control = self._request("GET", "/control")
            except TeleportError:
                continue
            if control.get("stop"):
                self._stop.set()
            seq = int(control.get("fenceSeq", 0))
            if seq > self._handled_fence:
                for cb in list(self._fence_callbacks):
                    try:
                        cb()
                    except Exception:
                        traceback.print_exc(file=sys.stderr)
                self._handled_fence = seq
                body = json.dumps({"fenceSeq": seq}).encode()
                try:
                    self._request("POST", "/fenced", body, "application/json")
                except TeleportError:
                    traceback.print_exc(file=sys.stderr)


_client: Client | None = None
_lock = threading.Lock()


def init() -> Client:
    """Create (once) and start the process-wide client from the environment."""
    global _client
    with _lock:
        if _client is None:
            _client = Client.from_env()
            _client.start()
        return _client


def checkpoint(
    checkpoint_id: str, state: State | None = None, files: Iterable[str | Path] | None = None
) -> dict[str, Any]:
    return init().checkpoint(checkpoint_id, state, files)


def restore(checkpoint_id: str) -> State | None:
    return init().restore(checkpoint_id)


def on_fence(callback: FenceCallback) -> None:
    init().on_fence(callback)


def should_stop() -> bool:
    return init().should_stop()

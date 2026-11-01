"""Teleport workload: a project open in VS Code.

Runs in the workload's work folder. On the first start it imports the project folder named in
app.json into ./project. It then launches VS Code with a private profile (./.vscode-user) and the
Teleport extension, which keeps ./project/.teleport-vscode/state.json up to date: open tabs, the
active tab, cursors, scroll and unsaved edits. The project folder (with that file) is the
"project" checkpoint, so after a migration VS Code reopens on the other device exactly as it was.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import teleport_sdk as teleport

HERE = Path.cwd()
PROJECT = HERE / "project"
STATE_DIR = PROJECT / ".teleport-vscode"
PROFILE = HERE / ".vscode-user"
SKIP = shutil.ignore_patterns(".git", "node_modules", ".venv", "venv", "__pycache__")
SETTINGS = {
    "security.workspace.trust.enabled": False,
    "workbench.startupEditor": "none",
    "window.restoreWindows": "none",
    "update.mode": "none",
    "telemetry.telemetryLevel": "off",
    "extensions.ignoreRecommendations": True,
    "workbench.tips.enabled": False,
    "git.openRepositoryInParentFolders": "never",
    "files.exclude": {"**/.teleport-vscode": True},
}


def log(msg: str) -> None:
    print(f"[vscode] {msg}", flush=True)


def find_code() -> Path | None:
    try:
        from teleport.apps.vscode import find_vscode
    except ImportError:  # running without the agent package: fall back to the CLI on PATH
        found = shutil.which("code")
        return Path(found) if found else None
    return find_vscode()


def import_project() -> None:
    if PROJECT.is_dir() and any(PROJECT.iterdir()):
        return  # restored from a checkpoint (after a migration or a restart)
    app = json.loads((HERE / "app.json").read_text("utf-8"))
    source = Path(app["projectPath"])
    if not source.is_dir():
        raise SystemExit(f"Project folder {source} does not exist on this device.")
    shutil.copytree(source, PROJECT, ignore=SKIP, dirs_exist_ok=True)
    log(f"imported {source}")


def launch(code: Path) -> subprocess.Popen[bytes]:
    (PROFILE / "User").mkdir(parents=True, exist_ok=True)
    (PROFILE / "User" / "settings.json").write_text(json.dumps(SETTINGS, indent=2), "utf-8")
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    argv = [
        str(code),
        "--user-data-dir", str(PROFILE),
        "--extensions-dir", str(PROFILE / "extensions"),
        f"--extensionDevelopmentPath={HERE / 'extension'}",
        "--disable-workspace-trust",
        "--new-window",
        str(PROJECT),
    ]  # fmt: skip
    env = {k: v for k, v in os.environ.items() if k != "ELECTRON_RUN_AS_NODE"}
    log(f"launching {code.name} on {PROJECT}")
    return subprocess.Popen(argv, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=PROJECT)


def flush_editor_state(timeout: float = 3.0) -> bool:
    """Ask the extension to write state.json now and wait for its acknowledgement."""
    seq = str(time.time_ns())
    request, ack = STATE_DIR / "flush.request", STATE_DIR / "flush.ack"
    request.write_text(seq, "utf-8")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with contextlib.suppress(OSError):
            if ack.read_text("utf-8").strip() == seq:
                return True
        time.sleep(0.05)
    log("the editor did not confirm its state in time; using the last saved state")
    return False


def stop(proc: subprocess.Popen[bytes]) -> None:
    try:
        import psutil

        parent = psutil.Process(proc.pid)
        for p in [*parent.children(recursive=True), parent]:
            with contextlib.suppress(psutil.Error):
                p.terminate()
        psutil.wait_procs([parent], timeout=5)
    except Exception:
        proc.terminate()


def main() -> int:
    teleport.init()
    session = teleport.restore("session") or {}
    launches = int(session.get("launches", 0)) + 1 if isinstance(session, dict) else 1
    import_project()
    code = find_code()
    if code is None:
        log("VS Code is not installed on this device")
        return 2
    proc = launch(code)

    def save_session() -> None:
        teleport.checkpoint("session", {"launches": launches, "savedAt": time.time()})

    def on_fence() -> None:  # the agent is about to freeze this workload: capture the editor now
        flush_editor_state()
        save_session()

    teleport.on_fence(on_fence)
    save_session()
    log(f"running (launch {launches} of this project)")
    try:
        while not teleport.should_stop():
            if proc.poll() is not None:
                log("VS Code was closed")
                break
            time.sleep(0.3)
    finally:
        if proc.poll() is None:
            stop(proc)
    return 0


if __name__ == "__main__":
    sys.exit(main())

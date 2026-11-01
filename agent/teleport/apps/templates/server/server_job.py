"""Teleport workload: a Python or Node server project.

Runs in the workload's work folder on whichever device holds the server. On the first start it imports
the project folder named in app.json into ./project (without node_modules, .venv, .git). Then, on every
device, it:
  1. installs the dependencies for this device (npm ci / npm install, or pip into ./.deps-venv),
  2. starts the server with PORT set,
  3. waits until the server listens, and opens it in the browser on localhost.
The project folder is the "project" checkpoint (dependencies excluded), so after a migration the other
device gets the same files and data, reinstalls what it needs, and serves again on the same port.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shlex
import shutil
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

import teleport_sdk as teleport

HERE = Path.cwd()
PROJECT = HERE / "project"
MARKER = HERE / ".deps-installed.json"
SKIP = shutil.ignore_patterns(".git", "node_modules", ".venv", "venv", "__pycache__", ".next", ".deps-venv")
APP = json.loads((HERE / "app.json").read_text("utf-8"))
WIN = os.name == "nt"


def _venv_dir() -> Path:
    """Next to the project, unless that path is long: pip writes paths ~130 characters deep inside a
    venv, and Windows refuses paths over 260 characters, so long locations get a short folder."""
    local = HERE / ".deps-venv"
    if not WIN or len(str(local)) <= 100:
        return local
    # Not under AppData\Local: the Microsoft Store Python silently redirects writes there.
    base = Path.home() / ".teleport" / "venvs"
    return base / hashlib.sha256(str(HERE).encode()).hexdigest()[:12]


VENV = _venv_dir()


def log(msg: str) -> None:
    print(f"[server] {msg}", flush=True)


def import_project() -> None:
    if PROJECT.is_dir() and any(PROJECT.iterdir()):
        log("project files restored from the checkpoint")
        return
    source = Path(APP["projectPath"])
    if not source.is_dir():
        raise SystemExit(f"Project folder {source} does not exist on this device.")
    shutil.copytree(source, PROJECT, ignore=SKIP, dirs_exist_ok=True)
    log(f"imported {source}")


def _fingerprint(*names: str) -> str:
    h = hashlib.sha256()
    for name in names:
        f = PROJECT / name
        if f.is_file():
            h.update(name.encode() + f.read_bytes())
    return h.hexdigest()


def _already(fingerprint: str, ready: bool) -> bool:
    with contextlib.suppress(OSError, ValueError):
        return ready and json.loads(MARKER.read_text("utf-8")).get("fingerprint") == fingerprint
    return False


def _run(argv: list[str], what: str) -> None:
    log(f"{what}: {' '.join(argv)}")
    started = time.monotonic()
    res = subprocess.run(argv, cwd=PROJECT, stdin=subprocess.DEVNULL)  # output goes to the workload log
    if res.returncode != 0:
        raise SystemExit(f"{what} failed (exit code {res.returncode}); see the lines above.")
    log(f"{what} done in {time.monotonic() - started:.0f} s")


def tool(name: str) -> str:
    found = shutil.which(name)
    if not found:
        raise SystemExit(f"'{name}' is not installed on this device; install it and start again.")
    return found


def install_node() -> None:
    pkg = json.loads((PROJECT / "package.json").read_text("utf-8"))
    if not (pkg.get("dependencies") or pkg.get("devDependencies")):
        return
    fp = _fingerprint("package.json", "package-lock.json")
    if _already(fp, (PROJECT / "node_modules").is_dir()):
        log("dependencies already installed")
        return
    npm = tool("npm")
    flags = ["--no-audit", "--no-fund"]
    if (PROJECT / "package-lock.json").is_file():
        try:
            _run([npm, "ci", *flags], "installing dependencies")
        except SystemExit:
            _run([npm, "install", *flags], "installing dependencies (npm ci failed, retrying)")
    else:
        _run([npm, "install", *flags], "installing dependencies")
    MARKER.write_text(json.dumps({"fingerprint": fp}), "utf-8")


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if WIN else "bin/python")


def install_python() -> str:
    """Returns the interpreter that runs the server."""
    deps = list(APP.get("dependencies") or [])
    command = APP["command"]
    for tool_name in ("uvicorn", "flask"):
        if f"-m {tool_name}" in command and not any(d.lower().startswith(tool_name) for d in deps):
            deps.append(tool_name)
    requirements = (PROJECT / "requirements.txt").is_file()
    if not deps and not requirements:
        return sys.executable
    fp = _fingerprint("requirements.txt", "pyproject.toml") + ",".join(deps)
    if _already(fp, venv_python().is_file()):
        log("dependencies already installed")
        return str(venv_python())
    if not (VENV / ("Scripts/pip.exe" if WIN else "bin/pip")).is_file():
        shutil.rmtree(VENV, ignore_errors=True)  # a half-made venv from an earlier failed attempt
        VENV.parent.mkdir(parents=True, exist_ok=True)
        _run([sys.executable, "-m", "venv", str(VENV)], "creating a virtual environment")
    pip = [str(venv_python()), "-m", "pip", "install", "--disable-pip-version-check"]
    if requirements:
        _run([*pip, "-r", "requirements.txt"], "installing dependencies")
    extra = [d for d in deps if not requirements or d in ("uvicorn", "flask")]
    if extra:
        _run([*pip, *extra], "installing dependencies")
    MARKER.write_text(json.dumps({"fingerprint": fp}), "utf-8")
    return str(venv_python())


def server_argv(python: str) -> list[str]:
    argv = shlex.split(APP["command"].replace("{port}", str(APP["port"])), posix=not WIN)
    head = argv[0].lower()
    if head in ("python", "python3", "py"):
        argv[0] = python
    elif head in ("npm", "node", "npx", "yarn", "pnpm"):
        argv[0] = tool(head)
    return argv


def _tree(pid: int) -> set[int]:
    import psutil

    with contextlib.suppress(psutil.Error):
        parent = psutil.Process(pid)
        return {pid, *(c.pid for c in parent.children(recursive=True))}
    return {pid}


def listening_port(proc: subprocess.Popen[bytes]) -> int | None:
    """The port the server listens on: found from its processes, else the configured one if it answers."""
    import psutil

    pids = _tree(proc.pid)
    with contextlib.suppress(psutil.Error, OSError):
        ports = sorted(
            c.laddr.port
            for c in psutil.net_connections(kind="tcp")
            if c.status == "LISTEN" and c.pid in pids and c.laddr
        )
        preferred = int(APP["port"])
        if ports:
            return preferred if preferred in ports else ports[0]
    with contextlib.suppress(OSError), socket.create_connection(("127.0.0.1", int(APP["port"])), timeout=0.3):
        return int(APP["port"])
    return None


def stop(proc: subprocess.Popen[bytes]) -> None:
    import psutil

    procs = []
    with contextlib.suppress(psutil.Error):
        parent = psutil.Process(proc.pid)
        procs = [*parent.children(recursive=True), parent]
    for p in procs:
        with contextlib.suppress(psutil.Error):
            p.terminate()
    psutil.wait_procs(procs, timeout=5)


def main() -> int:
    teleport.init()
    teleport.on_fence(lambda: None)  # nothing in memory: the agent checkpoints ./project while paused
    teleport.should_stop()  # starts the SDK poller, so a migration is answered even during an install
    import_project()
    if APP["kind"] == "node":
        install_node()
        python = sys.executable
    else:
        python = install_python()

    env = {k: v for k, v in os.environ.items() if not k.startswith("TELEPORT_")}
    env.update(PORT=str(APP["port"]), BROWSER="none", PYTHONUNBUFFERED="1")
    argv = server_argv(python)
    log(f"starting: {' '.join(argv)}")
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if WIN else 0
    proc = subprocess.Popen(argv, cwd=PROJECT, env=env, stdin=subprocess.DEVNULL, creationflags=flags)

    opened, deadline = False, time.monotonic() + 180
    try:
        while not teleport.should_stop():
            if proc.poll() is not None:
                log(f"the server exited (code {proc.returncode})")
                return proc.returncode or 1
            if not opened and time.monotonic() < deadline:
                port = listening_port(proc)
                if port:
                    url = f"http://localhost:{port}"
                    log(f"ready on {url}")
                    if APP.get("openBrowser", True) and os.environ.get("TELEPORT_OPEN_BROWSER") != "0":
                        webbrowser.open(url)
                    opened = True
            time.sleep(0.5)
    finally:
        if proc.poll() is None:
            stop(proc)
    return 0


if __name__ == "__main__":
    sys.exit(main())

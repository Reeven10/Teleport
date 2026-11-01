"""Ready-made workloads the dashboard can start with one click (no manifest paths to type)."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

import yaml

from ..core.settings import REPO_ROOT
from .server import detect_project
from .vscode import find_vscode

TEMPLATES = Path(__file__).resolve().parent / "templates"
SKIP = shutil.ignore_patterns(".git", "node_modules", ".venv", "venv", "__pycache__", ".teleport-vscode")
MAX_PROJECT_MB = 500


def gallery() -> list[dict[str, Any]]:
    """What the Workloads page offers. VS Code needs the folder of a project on this device."""
    code = find_vscode()
    return [
        {
            "id": "counter",
            "title": "Counter demo",
            "description": "A tiny job that counts and checkpoints every step. Resumes on the other device.",
            "manifestPath": str(REPO_ROOT / "tests" / "fixtures" / "counter_job"),
            "needs": None,
            "available": True,
        },
        {
            "id": "vscode",
            "title": "VS Code project",
            "description": "A project folder in VS Code: open tabs, cursors and unsaved edits move with it.",
            "manifestPath": None,
            "needs": "projectPath",
            "available": code is not None,
            "detail": str(code) if code else "VS Code was not found on this device.",
        },
        {
            "id": "server",
            "title": "Server project",
            "description": "A Python or Node server: it moves with its files and data, reinstalls its "
            "dependencies on the other device and opens there on localhost.",
            "manifestPath": None,
            "needs": "projectPath",
            "available": True,
        },
    ]


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:40] or "project"


def instance_id(prefix: str, title: str, project: Path, origin: str) -> str:
    """Workload id for one project on one device. Two different projects never share an id (and so
    never share an authority lease), even when their folders have the same name."""
    digest = hashlib.sha256(f"{origin}|{project.resolve()}".encode()).hexdigest()[:6]
    return f"{prefix}-{_slug(title)[:32]}-{digest}"


def _size_mb(folder: Path) -> float:
    total = 0
    for f in folder.rglob("*"):
        parts = set(f.relative_to(folder).parts)
        if parts & {".git", "node_modules", ".venv", "venv", "__pycache__"}:
            continue
        if f.is_file():
            total += f.stat().st_size
    return total / 2**20


def create_vscode_workload(home: Path, project_path: str, name: str | None = None, origin: str = "") -> Path:
    """A workload folder for `project_path` under TELEPORT_HOME/apps/: teleport.yaml, the wrapper job
    and the editor-state extension. Returns the folder (what POST /api/workloads/start takes)."""
    project = Path(project_path.strip().strip('"')).expanduser()
    if not project.is_dir():
        raise FileNotFoundError(f"Project folder not found: {project_path}")
    size = _size_mb(project)
    if size > MAX_PROJECT_MB:
        raise ValueError(f"The project is {size:.0f} MB; the demo limit is {MAX_PROJECT_MB} MB.")
    title = name or project.resolve().name
    wid = instance_id("vscode", title, project, origin)
    folder = home / "apps" / wid
    if folder.exists():
        shutil.rmtree(folder / "extension", ignore_errors=True)
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copy2(TEMPLATES / "vscode" / "vscode_job.py", folder / "vscode_job.py")
    shutil.copytree(TEMPLATES / "vscode" / "extension", folder / "extension", dirs_exist_ok=True)
    (folder / "app.json").write_text(
        json.dumps({"projectPath": str(project.resolve()), "title": title}), "utf-8"
    )
    manifest = {
        "id": wid,
        "name": f"VS Code: {title}",
        "command": "python vscode_job.py",
        "runtime": {"name": "python", "minVersion": "3.11"},
        "arch": ["x86_64", "arm64"],
        "os": ["windows", "linux", "macos"],
        "minRamMb": 128,  # free RAM the target needs before VS Code starts there
        "minCpuCores": 1,
        "minDiskMb": int(max(50, size * 3)),
        "needsGpu": False,
        "libs": ["vscode"],  # the target must have VS Code (devices report it as a lib)
        "remoteCapable": True,
        "checkpoints": [
            {"id": "project", "name": "Project files and editor state", "paths": ["project"]},
            {"id": "session", "name": "Editor session", "paths": []},
        ],
    }
    (folder / "teleport.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), "utf-8")
    return folder


def create_server_workload(
    home: Path,
    project_path: str,
    origin: str = "",
    command: str | None = None,
    port: int | None = None,
    name: str | None = None,
) -> Path:
    """A workload folder for a Python or Node server project: teleport.yaml, the wrapper (installs the
    dependencies on each device, starts the server, opens it in the browser) and app.json."""
    project = Path(project_path.strip().strip('"')).expanduser()
    found = detect_project(project)
    size = _size_mb(project)
    if size > MAX_PROJECT_MB:
        raise ValueError(
            f"The project is {size:.0f} MB without dependencies; the limit is {MAX_PROJECT_MB} MB."
        )
    title = name or found["name"]
    wid = instance_id("server", title, project, origin)
    folder = home / "apps" / wid
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copy2(TEMPLATES / "server" / "server_job.py", folder / "server_job.py")
    app = {
        "projectPath": str(project.resolve()),
        "title": title,
        "kind": found["kind"],
        "command": (command or found["command"]).strip(),
        "port": int(port or found["port"]),
        "dependencies": found["dependencies"],
        "openBrowser": True,
    }
    (folder / "app.json").write_text(json.dumps(app, indent=2), "utf-8")
    manifest = {
        "id": wid,
        "name": f"Server: {title}",
        "command": "python server_job.py",
        "runtime": found["runtime"],  # node or python on the target, checked before migrating
        "arch": ["x86_64", "arm64"],
        "os": ["windows", "linux", "macos"],
        "minRamMb": 128,
        "minCpuCores": 1,
        "minDiskMb": int(max(100, size * 3 + (300 if found["kind"] == "node" else 150))),
        "needsGpu": False,
        "libs": [],
        "remoteCapable": True,
        "checkpoints": [
            {
                "id": "project",
                "name": "Project files and data (dependencies reinstalled)",
                "paths": ["project"],
            },
        ],
    }
    (folder / "teleport.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), "utf-8")
    return folder

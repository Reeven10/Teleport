"""Ready-made workloads the dashboard can start with one click (no manifest paths to type)."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

import yaml

from ..core.settings import REPO_ROOT
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
    ]


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:40] or "project"


def _size_mb(folder: Path) -> float:
    total = 0
    for f in folder.rglob("*"):
        parts = set(f.relative_to(folder).parts)
        if parts & {".git", "node_modules", ".venv", "venv", "__pycache__"}:
            continue
        if f.is_file():
            total += f.stat().st_size
    return total / 2**20


def create_vscode_workload(home: Path, project_path: str, name: str | None = None) -> Path:
    """A workload folder for `project_path` under TELEPORT_HOME/apps/: teleport.yaml, the wrapper job
    and the editor-state extension. Returns the folder (what POST /api/workloads/start takes)."""
    project = Path(project_path.strip().strip('"')).expanduser()
    if not project.is_dir():
        raise FileNotFoundError(f"Project folder not found: {project_path}")
    size = _size_mb(project)
    if size > MAX_PROJECT_MB:
        raise ValueError(f"The project is {size:.0f} MB; the demo limit is {MAX_PROJECT_MB} MB.")
    title = name or project.resolve().name
    wid = f"vscode-{_slug(title)}"
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

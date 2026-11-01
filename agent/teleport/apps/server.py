"""Recognise a server project folder: its language, how to install its dependencies, how to start it.

Detection only reads files (package.json, requirements.txt, pyproject.toml, the entry script); it never
runs anything. The dashboard shows the result before the server starts, and every field can be changed.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

PY_ENTRIES = ("app.py", "main.py", "server.py", "run.py", "wsgi.py", "api.py")
NODE_ENTRIES = ("server.js", "index.js", "app.js", "main.js", "server.mjs", "index.mjs")


def _read(path: Path) -> str:
    try:
        return path.read_text("utf-8", errors="replace")
    except OSError:
        return ""


def _port_in(text: str) -> int | None:
    """A port literal in source code: listen(3000), port=5000, PORT || 8080, --port 8000."""
    for pat in (
        r"listen\(\s*(\d{4,5})",
        r"\bport\s*[=:]\s*(\d{4,5})",
        r"PORT\s*(?:\|\||\?\?|or|,)\s*['\"]?(\d{4,5})",
        r"--port[ =](\d{4,5})",
    ):
        if m := re.search(pat, text, re.IGNORECASE):
            port = int(m.group(1))
            if 1024 <= port <= 65535:
                return port
    return None


def _min_version(spec: str | None, default: str) -> str:
    m = re.search(r"(\d+(?:\.\d+)?)", spec or "")
    return m.group(1) if m else default


def detect_node(folder: Path) -> dict[str, Any] | None:
    pkg_file = folder / "package.json"
    if not pkg_file.is_file():
        return None
    try:
        pkg = json.loads(_read(pkg_file) or "{}")
    except ValueError:
        pkg = {}
    scripts = pkg.get("scripts") or {}
    deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
    if "start" in scripts:
        command, source = "npm start", scripts["start"]
    elif "dev" in scripts:
        command, source = "npm run dev", scripts["dev"]
    else:
        entry = pkg.get("main") if isinstance(pkg.get("main"), str) else None
        entry = entry or next((e for e in NODE_ENTRIES if (folder / e).is_file()), None)
        if entry is None:
            return None
        command, source = f"node {entry}", ""
    entry_text = "".join(_read(folder / e) for e in NODE_ENTRIES if (folder / e).is_file())
    lock = (folder / "package-lock.json").is_file()
    return {
        "kind": "node",
        "runtime": {"name": "node", "minVersion": _min_version((pkg.get("engines") or {}).get("node"), "16")},
        "install": ("npm ci" if lock else "npm install") if deps else None,
        "dependencies": sorted(deps),
        "command": command,
        "port": _port_in(str(source)) or _port_in(entry_text) or 3000,
    }


def _python_deps(folder: Path) -> tuple[str | None, list[str]]:
    req = folder / "requirements.txt"
    if req.is_file():
        lines = [ln.split("#")[0].strip() for ln in _read(req).splitlines()]
        return "requirements.txt", [ln for ln in lines if ln and not ln.startswith("-")]
    pyproject = folder / "pyproject.toml"
    if pyproject.is_file():
        try:
            deps = tomllib.loads(_read(pyproject)).get("project", {}).get("dependencies", [])
        except tomllib.TOMLDecodeError:
            deps = []
        return ("pyproject.toml", [str(d) for d in deps]) if deps else (None, [])
    return None, []


def detect_python(folder: Path) -> dict[str, Any] | None:
    deps_file, deps = _python_deps(folder)
    names = {re.split(r"[<>=!~\[; ]", d, maxsplit=1)[0].lower() for d in deps}
    if (folder / "manage.py").is_file():  # Django
        return {
            "kind": "python",
            "runtime": {"name": "python", "minVersion": "3.10"},
            "install": f"pip install ({deps_file})" if deps_file else None,
            "dependencies": deps,
            "command": "python manage.py runserver 0.0.0.0:{port}",
            "port": 8000,
        }
    entry = next((e for e in PY_ENTRIES if (folder / e).is_file()), None)
    if entry is None:
        return None
    text = _read(folder / entry)
    module = entry.removesuffix(".py")
    if "__main__" in text:
        command = f"python {entry}"
    elif "FastAPI(" in text or "fastapi" in names:
        command = f"python -m uvicorn {module}:app --host 0.0.0.0 --port {{port}}"
    elif "Flask(" in text or "flask" in names:
        command = f"python -m flask --app {module} run --host 0.0.0.0 --port {{port}}"
    else:
        command = f"python {entry}"
    default = 5000 if "flask" in command else 8000
    return {
        "kind": "python",
        "runtime": {"name": "python", "minVersion": "3.10"},
        "install": f"pip install ({deps_file})" if deps_file else None,
        "dependencies": deps,
        "command": command,
        "port": _port_in(text) or default,
    }


def detect_project(folder: Path) -> dict[str, Any]:
    """What the dashboard shows before starting a server. Raises ValueError if nothing is recognised."""
    if not folder.is_dir():
        raise FileNotFoundError(f"Project folder not found: {folder}")
    found = detect_node(folder) or detect_python(folder)
    if found is None:
        raise ValueError(
            "No server found in this folder: Teleport looks for package.json (Node) or "
            f"{', '.join(PY_ENTRIES)} / manage.py (Python)."
        )
    return {**found, "name": folder.resolve().name, "path": str(folder.resolve())}

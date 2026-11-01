"""Finding VS Code. The Electron binary itself is launched (not the `code` CLI), so the editor is a
child of the workload process: pausing and stopping the workload pauses and closes the editor."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def find_vscode() -> Path | None:
    """The VS Code executable, or None. TELEPORT_VSCODE overrides the search."""
    if override := os.environ.get("TELEPORT_VSCODE"):
        return Path(override) if Path(override).exists() else None
    candidates: list[Path] = []
    cli = shutil.which("code")
    if sys.platform == "win32":
        for env, sub in (
            ("LOCALAPPDATA", "Programs/Microsoft VS Code/Code.exe"),
            ("ProgramFiles", "Microsoft VS Code/Code.exe"),
            ("ProgramFiles(x86)", "Microsoft VS Code/Code.exe"),
        ):
            if base := os.environ.get(env):
                candidates.append(Path(base) / sub)
        if cli:  # ...\Microsoft VS Code\bin\code.cmd -> ...\Microsoft VS Code\Code.exe
            candidates.append(Path(cli).resolve().parent.parent / "Code.exe")
    elif sys.platform == "darwin":
        for apps in (Path("/Applications"), Path.home() / "Applications"):
            for binary in ("Electron", "Code"):
                candidates.append(apps / "Visual Studio Code.app" / "Contents" / "MacOS" / binary)
    else:
        candidates += [
            Path("/usr/share/code/code"),
            Path("/opt/visual-studio-code/code"),
            Path("/snap/bin/code"),
        ]
        if cli:
            candidates.append(Path(cli).resolve())
    return next((c for c in candidates if c.is_file()), None)

"""Checkpoint unit format, shared by the SDK and the agent's checkpoint store.

A unit is a deterministic tar.gz (sorted entries, zeroed mtimes/owners), so equal content always
gives an equal SHA-256. Members: optional `state.json` (dict) or `state.bin` (bytes), plus
`files/<relative posix path>` for files saved alongside.
"""

from __future__ import annotations

import gzip
import io
import json
import shutil
import tarfile
from collections.abc import Iterable
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath
from typing import Any

State = dict[str, Any] | bytes
STATE_JSON = "state.json"
STATE_BIN = "state.bin"
FILES_PREFIX = "files/"


def collect_files(
    paths: Iterable[str | Path], base: Path, exclude: Iterable[str] = ()
) -> list[tuple[str, Path]]:
    """(arcname, path) for every file under `paths` (files or folders) relative to `base`.

    Missing paths are skipped; paths outside `base` raise ValueError; any path part matching an
    `exclude` glob (e.g. "__pycache__") is skipped.
    """
    patterns = list(exclude)
    base = base.resolve()
    out: dict[str, Path] = {}
    for p in paths:
        full = (base / p).resolve()
        if not full.is_relative_to(base):
            raise ValueError(f"checkpoint path {str(p)!r} is outside the working folder")
        candidates = sorted(f for f in full.rglob("*") if f.is_file()) if full.is_dir() else [full]
        for f in candidates:
            rel = f.relative_to(base)
            if f.is_file() and not any(fnmatch(part, pat) for part in rel.parts for pat in patterns):
                out[FILES_PREFIX + rel.as_posix()] = f
    return sorted(out.items())


def _add(tar: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = 0o644
    tar.addfile(info, io.BytesIO(data))


def pack_unit(state: State | None, files: Iterable[tuple[str, Path]] = (), level: int = 6) -> bytes:
    """Deterministic tar.gz. `level` is the gzip level (0 = store only, the fastest)."""
    entries: list[tuple[str, bytes]] = []
    if isinstance(state, bytes):
        entries.append((STATE_BIN, state))
    elif state is not None:
        entries.append((STATE_JSON, json.dumps(state, sort_keys=True, separators=(",", ":")).encode()))
    entries += [(name, path.read_bytes()) for name, path in files]
    buf = io.BytesIO()
    with (
        gzip.GzipFile(filename="", fileobj=buf, mode="wb", mtime=0, compresslevel=level) as gz,
        tarfile.open(fileobj=gz, mode="w", format=tarfile.GNU_FORMAT) as tar,
    ):
        for name, data in sorted(entries):
            _add(tar, name, data)
    return buf.getvalue()


def _safe_name(name: str) -> bool:
    p = PurePosixPath(name)
    if p.is_absolute() or ".." in p.parts or "\\" in name:
        return False
    return name in (STATE_JSON, STATE_BIN) or (name.startswith(FILES_PREFIX) and len(p.parts) > 1)


def unpack_unit(data: bytes, files_dest: Path | None = None) -> tuple[str | None, bytes | None]:
    """Validate a unit; write its files under `files_dest` (if given); return (state name, raw state).

    Raises ValueError on a corrupt archive or unsafe member.
    """
    state_name: str | None = None
    state_raw: bytes | None = None
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            for m in tar:
                if not m.isfile() or not _safe_name(m.name):
                    raise ValueError(f"unsafe checkpoint member {m.name!r}")
                src = tar.extractfile(m)
                assert src is not None
                if m.name in (STATE_JSON, STATE_BIN):
                    state_name, state_raw = m.name, src.read()
                elif files_dest is not None:
                    target = files_dest / m.name[len(FILES_PREFIX) :]
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open("wb") as out:
                        shutil.copyfileobj(src, out)
    except (tarfile.TarError, OSError, EOFError) as e:
        raise ValueError(f"corrupt checkpoint unit: {e}") from e
    return state_name, state_raw


def decode_state(name: str | None, raw: bytes | None) -> State:
    """Decoded state; a unit holding only files decodes to {}."""
    if name == STATE_BIN and raw is not None:
        return raw
    if name == STATE_JSON and raw is not None:
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("state.json must hold an object")
        return value
    return {}

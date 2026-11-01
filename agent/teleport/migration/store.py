"""Checkpoint store, chunker and reassembler (P1).

Layout: TELEPORT_HOME/workloads/<workloadId>/checkpoints/<checkpointId>/{unit.tar.gz, meta.json}.
meta.json is a CheckpointRecord. `seq` is a per-workload counter that only moves when content
(SHA-256) changes, so changed_since() is a plain hash comparison.
"""

from __future__ import annotations

import hashlib
import math
import re
import shutil
import tempfile
import threading
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from teleport_sdk.unit import collect_files, pack_unit, unpack_unit

from contract.contract import CheckpointRecord

CHUNK_SIZE = 256 * 1024
# Installed dependencies never travel: the target reinstalls them from the manifest files
# (package.json, requirements.txt), which is smaller, faster and right for its OS and CPU.
DEPENDENCY_DIRS = ("node_modules", ".venv", "venv", "__pycache__", "*.pyc", ".next", ".parcel-cache")
UNIT = "unit.tar.gz"
META = "meta.json"
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


class ChunkError(ValueError):
    pass


def _check_id(kind: str, value: str) -> str:
    if not _ID_RE.match(value):
        raise ValueError(f"invalid {kind} id {value!r}")
    return value


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def replace_file(src: Path, dst: Path, attempts: int = 40) -> None:
    """os.replace that survives Windows sharing violations.

    Windows refuses to replace a file while another handle has it open (a reader, Defender, the search
    indexer); those holds last milliseconds, so retry for up to ~1 s instead of failing the checkpoint.
    """
    for attempt in range(attempts):
        try:
            src.replace(dst)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.025)


def write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    replace_file(tmp, path)


class CheckpointStore:
    def __init__(self, home: Path) -> None:
        self.root = home / "workloads"
        # One lock for every read and write: a unit is never read while it is being replaced, which
        # Windows does not allow (WinError 5) and which could hand out a half-written meta.json.
        self._lock = threading.RLock()

    def workload_dir(self, workload_id: str) -> Path:
        return self.root / _check_id("workload", workload_id)

    def unit_dir(self, workload_id: str, checkpoint_id: str) -> Path:
        return self.workload_dir(workload_id) / "checkpoints" / _check_id("checkpoint", checkpoint_id)

    def unit_path(self, workload_id: str, checkpoint_id: str) -> Path:
        return self.unit_dir(workload_id, checkpoint_id) / UNIT

    def _next_seq(self, workload_id: str) -> int:
        path = self.workload_dir(workload_id) / "seq"
        seq = int(path.read_text()) + 1 if path.exists() else 1
        path.write_text(str(seq))
        return seq

    def put(self, workload_id: str, checkpoint_id: str, data: bytes) -> CheckpointRecord:
        """Store a packed unit (validated first). Unchanged content keeps the existing record."""
        unpack_unit(data)
        digest = sha256_hex(data)
        with self._lock:
            current = self.record(workload_id, checkpoint_id)
            if current is not None and current.sha256 == digest:
                return current
            folder = self.unit_dir(workload_id, checkpoint_id)
            folder.mkdir(parents=True, exist_ok=True)
            record = CheckpointRecord(
                id=checkpoint_id,
                seq=self._next_seq(workload_id),
                sizeBytes=len(data),
                sha256=digest,
                createdAt=time.time(),
            )
            write_atomic(folder / UNIT, data)
            write_atomic(folder / META, record.model_dump_json().encode())
            return record

    def adopt(
        self, workload_id: str, checkpoint_id: str, path: Path, record: CheckpointRecord
    ) -> CheckpointRecord:
        """Move an already verified unit file into the store (no re-read, re-hash or re-validate).

        The caller guarantees `path` holds exactly `record` (the migration target verified every
        chunk and the whole-unit SHA-256 on arrival). Same filesystem, so this is a rename.
        """
        with self._lock:
            folder = self.unit_dir(workload_id, checkpoint_id)
            folder.mkdir(parents=True, exist_ok=True)
            stored = record.model_copy(
                update={"seq": self._next_seq(workload_id), "sent": None, "validated": None}
            )
            replace_file(path, folder / UNIT)
            write_atomic(folder / META, stored.model_dump_json().encode())
            return stored

    def pack_paths(
        self, workload_id: str, checkpoint_id: str, workdir: Path, paths: Iterable[str], level: int = 6
    ) -> CheckpointRecord:
        """Agent-side checkpoint of manifest paths (relative to the workload's working folder)."""
        files = collect_files(paths, workdir, exclude=DEPENDENCY_DIRS)
        return self.put(workload_id, checkpoint_id, pack_unit(None, files, level))

    def read(self, workload_id: str, checkpoint_id: str) -> bytes | None:
        path = self.unit_path(workload_id, checkpoint_id)
        with self._lock:
            return path.read_bytes() if path.exists() else None

    def read_with_record(self, workload_id: str, checkpoint_id: str) -> tuple[bytes, CheckpointRecord] | None:
        """The unit and its record as one consistent pair (a checkpoint cannot land in between)."""
        with self._lock:
            data, record = self.read(workload_id, checkpoint_id), self.record(workload_id, checkpoint_id)
            return (data, record) if data is not None and record is not None else None

    def record(self, workload_id: str, checkpoint_id: str) -> CheckpointRecord | None:
        path = self.unit_dir(workload_id, checkpoint_id) / META
        with self._lock:
            if not path.exists():
                return None
            return CheckpointRecord.model_validate_json(path.read_text("utf-8"))

    def records(self, workload_id: str) -> list[CheckpointRecord]:
        base = self.workload_dir(workload_id) / "checkpoints"
        if not base.is_dir():
            return []
        found = (self.record(workload_id, d.name) for d in sorted(base.iterdir()) if d.is_dir())
        return sorted((r for r in found if r is not None), key=lambda r: r.seq)

    def changed_since(self, workload_id: str, known: Iterable[CheckpointRecord]) -> list[CheckpointRecord]:
        """Current records whose hash differs from (or is missing in) `known`."""
        seen = {r.id: r.sha256 for r in known}
        return [r for r in self.records(workload_id) if seen.get(r.id) != r.sha256]

    def verify(self, workload_id: str, checkpoint_id: str) -> bool:
        record, data = self.record(workload_id, checkpoint_id), self.read(workload_id, checkpoint_id)
        return record is not None and data is not None and sha256_hex(data) == record.sha256

    def extract(self, workload_id: str, workdir: Path, restore_dir: Path) -> list[str]:
        """Restore every unit: files into `workdir`, raw state into `restore_dir/<id>/`. Returns ids."""
        if restore_dir.exists():
            shutil.rmtree(restore_dir)
        restored: list[str] = []
        for record in self.records(workload_id):
            data = self.read(workload_id, record.id)
            if data is None or sha256_hex(data) != record.sha256:
                raise ValueError(f"checkpoint {record.id} of {workload_id} failed hash verification")
            target = restore_dir / record.id
            target.mkdir(parents=True, exist_ok=True)
            name, raw = unpack_unit(data, files_dest=workdir)
            if name is not None and raw is not None:
                (target / name).write_bytes(raw)
            restored.append(record.id)
        return restored

    def delete(self, workload_id: str) -> None:
        shutil.rmtree(self.workload_dir(workload_id) / "checkpoints", ignore_errors=True)
        (self.workload_dir(workload_id) / "seq").unlink(missing_ok=True)


# ---------------------------------------------------------------- chunking


@dataclass(frozen=True)
class Chunk:
    index: int
    total: int
    data: bytes
    sha256: str


def iter_chunks(source: bytes | Path, chunk_size: int = CHUNK_SIZE) -> Iterator[Chunk]:
    """Split a unit into chunks with per-chunk SHA-256 (an empty unit is one empty chunk)."""
    size = len(source) if isinstance(source, bytes) else source.stat().st_size
    total = max(1, math.ceil(size / chunk_size))
    if isinstance(source, bytes):
        for i in range(total):
            piece = source[i * chunk_size : (i + 1) * chunk_size]
            yield Chunk(i, total, piece, sha256_hex(piece))
        return
    with source.open("rb") as f:
        for i in range(total):
            piece = f.read(chunk_size)
            yield Chunk(i, total, piece, sha256_hex(piece))


class Reassembler:
    """Collects chunks of one checkpoint (any order, duplicates ok) and verifies the whole unit."""

    def __init__(self, record: CheckpointRecord, chunk_size: int = CHUNK_SIZE) -> None:
        self.record = record
        self.chunk_size = chunk_size
        self.total = max(1, math.ceil(record.sizeBytes / chunk_size))
        self._have: set[int] = set()
        self._spool: IO[bytes] = tempfile.TemporaryFile()

    def add(self, index: int, total: int, data: bytes, sha256: str) -> None:
        """Raises ChunkError for a corrupted or inconsistent chunk (caller nacks and resends)."""
        if total != self.total:
            raise ChunkError(f"{self.record.id}: total {total} != expected {self.total}")
        if not 0 <= index < total:
            raise ChunkError(f"{self.record.id}: chunk index {index} out of range")
        expected_len = min(self.chunk_size, self.record.sizeBytes - index * self.chunk_size)
        if len(data) != expected_len:
            raise ChunkError(
                f"{self.record.id}: chunk {index} has {len(data)} bytes, expected {expected_len}"
            )
        if sha256_hex(data) != sha256:
            raise ChunkError(f"{self.record.id}: chunk {index} failed SHA-256")
        self._spool.seek(index * self.chunk_size)
        self._spool.write(data)
        self._have.add(index)

    def missing(self) -> list[int]:
        return [i for i in range(self.total) if i not in self._have]

    @property
    def complete(self) -> bool:
        return not self.missing()

    def finalize(self) -> bytes:
        """The verified unit bytes. Raises ChunkError if chunks are missing or the hash differs."""
        if missing := self.missing():
            raise ChunkError(f"{self.record.id}: missing chunks {missing[:10]}")
        self._spool.seek(0)
        data = self._spool.read(self.record.sizeBytes)
        self._spool.close()
        if sha256_hex(data) != self.record.sha256:
            raise ChunkError(f"{self.record.id}: checkpoint SHA-256 mismatch")
        return data

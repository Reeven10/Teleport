"""Migration journal: TELEPORT_HOME/migrations/<id>.json, rewritten on every status change, so an
agent that restarts mid-migration can decide the safe state (see MigrationManager._recover)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from contract.contract import CheckpointRecord, MigrationStatus, WorkloadManifest

from .store import replace_file

log = logging.getLogger("teleport.migration.journal")


class JournalEntry(BaseModel):
    role: Literal["source", "target"]
    status: MigrationStatus
    peerId: str
    chunkSize: int
    fenceEpoch: int | None = None  # source: epoch after fencing
    startSent: bool = False  # source: mig.start went out
    committed: bool = False  # source: mig.started ok came back
    epoch: int | None = None  # target: current (fence) epoch
    sent: dict[str, CheckpointRecord] = {}  # source: last transferred version of each unit
    manifest: WorkloadManifest | None = None  # target: needed to resume or discard


class MigrationJournal:
    def __init__(self, home: Path) -> None:
        self.dir = home / "migrations"

    def save(self, entry: JournalEntry) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.dir / f"{entry.status.id}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(entry.model_dump_json(), "utf-8")
        replace_file(tmp, path)

    def load_all(self) -> list[JournalEntry]:
        if not self.dir.is_dir():
            return []
        out: list[JournalEntry] = []
        for path in sorted(self.dir.glob("*.json")):
            try:
                out.append(JournalEntry.model_validate_json(path.read_text("utf-8")))
            except ValueError as e:
                log.warning("ignoring unreadable migration journal %s: %s", path.name, e)
        return sorted(out, key=lambda e: e.status.startedAt)

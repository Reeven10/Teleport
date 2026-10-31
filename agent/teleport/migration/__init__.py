"""Migration manager (P1). Workload registry works; checkpointed migration is still a stub."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from contract.contract import MigrationStatus, Trigger, WorkloadManifest

from ..core.context import Context
from ..core.settings import REPO_ROOT


class MigrationManagerStub:
    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self._workloads: dict[str, WorkloadManifest] = {}
        self._migrations: dict[str, MigrationStatus] = {}

    def workloads(self) -> list[WorkloadManifest]:
        return list(self._workloads.values())

    async def launch_workload(self, manifest_path: str) -> WorkloadManifest:
        """Register a manifest (.json/.yaml; relative paths resolve from cwd, then the repo root)."""
        path = Path(manifest_path)
        if not path.is_absolute() and not path.exists():
            path = REPO_ROOT / path
        if not path.exists():
            raise FileNotFoundError(manifest_path)
        text = path.read_text("utf-8")
        data = yaml.safe_load(text) if path.suffix in (".yaml", ".yml") else json.loads(text)
        manifest = WorkloadManifest.model_validate(data)
        self._workloads[manifest.id] = manifest
        await self.ctx.authority.claim(manifest.id, self.ctx.device_id)
        return manifest

    async def start(self, workload_id: str, target_id: str, trigger: Trigger) -> MigrationStatus:
        raise NotImplementedError("migration is not implemented yet (P1)")

    async def abort(self, migration_id: str) -> MigrationStatus:
        raise NotImplementedError("migration abort is not implemented yet (P1)")

    def status(self, migration_id: str) -> MigrationStatus | None:
        return self._migrations.get(migration_id)

    def list(self) -> list[MigrationStatus]:
        return list(self._migrations.values())

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass


def create_migration_manager(ctx: Context) -> MigrationManagerStub:
    return MigrationManagerStub(ctx)

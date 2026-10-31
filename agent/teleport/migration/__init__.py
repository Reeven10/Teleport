"""Migration (P1): checkpointed migration with fencing and rollback. See manager.py."""

from __future__ import annotations

from ..core.context import Context
from .manager import (
    DigestSigner,
    ManifestSigner,
    MigrationAborted,
    MigrationError,
    MigrationManager,
    Timeouts,
    WorkloadHost,
)


def create_migration_manager(ctx: Context) -> MigrationManager:
    return MigrationManager(ctx)


__all__ = [
    "DigestSigner",
    "ManifestSigner",
    "MigrationAborted",
    "MigrationError",
    "MigrationManager",
    "Timeouts",
    "WorkloadHost",
    "create_migration_manager",
]

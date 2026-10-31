"""History store module (P3).

Provides SQLite persistence for devices, decisions, migrations, and event timelines.
"""

from __future__ import annotations

from ..core.context import Context
from .router import build_history_router
from .store import SqliteHistoryStore

__all__ = ["SqliteHistoryStore", "create_history_store", "build_history_router"]


def create_history_store(ctx: Context) -> SqliteHistoryStore:
    return SqliteHistoryStore(ctx)

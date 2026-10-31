"""History store module (P3).

Provides SQLite persistence for devices, decisions, migrations, and event timelines.
"""

from __future__ import annotations

from ..core.context import Context
from .store import SqliteHistoryStore

__all__ = ["SqliteHistoryStore", "create_history_store"]


def create_history_store(ctx: Context) -> SqliteHistoryStore:
    return SqliteHistoryStore(ctx)

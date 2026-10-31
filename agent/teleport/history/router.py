"""FastAPI history router (P3).

Provides REST endpoints for querying devices history, migration details,
decision logs, timeline events, and full history exports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from fastapi import APIRouter, HTTPException, Query

from ..core.context import Context

if TYPE_CHECKING:
    from .store import SqliteHistoryStore


def build_history_router(ctx: Context) -> APIRouter:
    """Build the /api/history APIRouter with full query, filtering, and export capabilities."""
    router = APIRouter(prefix="/api/history", tags=["history"])

    def _get_store() -> SqliteHistoryStore:
        from .store import SqliteHistoryStore

        return cast(SqliteHistoryStore, ctx.history)

    @router.get("/devices")
    async def get_devices() -> list[dict[str, Any]]:
        """Return every device ever seen with first/last seen, link types, and migration count."""
        store = _get_store()
        return await store.list_device_summaries()

    @router.get("/devices/{device_id}")
    async def get_device(device_id: str) -> dict[str, Any]:
        """Return device history detail with all migrations involving this device for revisit."""
        store = _get_store()
        dev = await store.get_device_detail(device_id)
        if not dev:
            raise HTTPException(status_code=404, detail=f"Device {device_id} not found in history")
        return dev

    @router.get("/migrations")
    async def get_migrations(
        device: str | None = None,
        workload: str | None = None,
        decision: str | None = None,
        outcome: str | None = None,
        since: float | None = None,
        until: float | None = None,
        date_range: str | None = None,
        limit: int = Query(default=50, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
    ) -> list[Any]:
        """Return migrations with optional filtering and paging."""
        if date_range and ":" in date_range:
            parts = date_range.split(":", 1)
            try:
                if parts[0]:
                    since = float(parts[0])
                if parts[1]:
                    until = float(parts[1])
            except ValueError:
                pass

        store = _get_store()
        return await store.list_migrations(
            device=device,
            workload=workload,
            decision=decision,
            outcome=outcome,
            since=since,
            until=until,
            limit=limit,
            offset=offset,
        )

    @router.get("/migrations/{migration_id}")
    async def get_migration(migration_id: str) -> dict[str, Any]:
        """Return the complete migration record including manifest, timeline,
        metrics, and replay snapshots.
        """
        store = _get_store()
        record = await store.get_migration(migration_id)
        if not record:
            raise HTTPException(
                status_code=404, detail=f"Migration {migration_id} not found in history"
            )
        return record

    @router.get("/decisions")
    async def get_decisions(
        limit: int = Query(default=100, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
        workload: str | None = None,
    ) -> list[Any]:
        """Return the decision log with reasons (including remote access and stay decisions)."""
        store = _get_store()
        return await store.list_decisions(limit=limit, offset=offset, workload=workload)

    @router.get("/export")
    async def export_history() -> dict[str, Any]:
        """Return the complete history database as JSON for backup and demo."""
        store = _get_store()
        return await store.export_history()

    return router

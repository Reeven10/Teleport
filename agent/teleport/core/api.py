"""REST routes from contract/contract.ts. Routes live here (P1) and delegate to module Protocols."""

from __future__ import annotations

import os
import time
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, ValidationError

from contract.contract import (
    DecisionLog,
    DeviceInfo,
    FeasibilityResult,
    MigrationMetrics,
    MigrationStatus,
    RemoteSession,
    Stats,
    Trigger,
    WorkloadManifest,
    WorkloadRun,
)

from .. import __version__
from .context import Context
from .settings import CHUNK_KB_MAX, CHUNK_KB_MIN, Mode, PreferredLink, Prefs, RemoteConsent


class PairRequest(BaseModel):
    addr: str
    pin: str


class WorkloadStartRequest(BaseModel):
    manifestPath: str


class FeasibilityRequest(BaseModel):
    workloadId: str
    targetId: str


class MigrationRequest(BaseModel):
    workloadId: str
    targetId: str
    trigger: Trigger = "user_command"


class PrecopyRequest(BaseModel):
    targetId: str


class RemoteStartRequest(BaseModel):
    workloadId: str
    viewerId: str


class StatsOverrideRequest(BaseModel):
    deviceId: str
    stats: dict[str, Any] | None


class PrefsUpdate(BaseModel):
    """Partial update; unknown fields are rejected so a typo is never silently dropped."""

    model_config = ConfigDict(extra="forbid")

    mode: Mode | None = None
    batteryLowPct: float | None = None
    cpuHighPct: float | None = None
    memHighPct: float | None = None
    chunkSizeKb: int | None = None
    precopyIntervalS: float | None = None
    precopyTargetId: str | None = None
    leaseSyncS: float | None = None
    compressLevel: int | None = None
    predictionWindowSec: float | None = None
    preferredLink: PreferredLink | None = None
    remoteConsent: RemoteConsent | None = None
    checkpointChunkKb: int | None = None  # deprecated alias of chunkSizeKb (dashboard), clamped

    def changes(self) -> dict[str, Any]:
        data = self.model_dump(exclude_none=True)
        if (alias := data.pop("checkpointChunkKb", None)) is not None and "chunkSizeKb" not in data:
            data["chunkSizeKb"] = min(max(int(alias), CHUNK_KB_MIN), CHUNK_KB_MAX)
        return data


def build_router(ctx: Context) -> APIRouter:
    r = APIRouter(prefix="/api")

    def find_device(device_id: str) -> DeviceInfo:
        for d in [*ctx.devices.list_devices(), *ctx.peers.list_peers()]:
            if d.id == device_id:
                return d
        raise HTTPException(404, f"unknown device {device_id}")

    def find_workload(workload_id: str) -> WorkloadManifest:
        for w in ctx.workloads.list():
            if w.id == workload_id:
                return w
        raise HTTPException(404, f"unknown workload {workload_id}")

    @r.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "ok": True,
            "deviceId": ctx.device_id,
            "name": ctx.devices.local_info().name,
            "port": ctx.settings.port,
            "simProfile": ctx.settings.simProfile,
            "agentVersion": __version__,
            "ts": time.time(),
        }

    @r.get("/devices")
    async def devices() -> list[DeviceInfo]:
        return ctx.devices.list_devices()

    @r.get("/stats")
    async def stats() -> list[Stats]:
        latest = (ctx.devices.latest_stats(d.id) for d in ctx.devices.list_devices())
        return [s for s in latest if s is not None]

    @r.get("/workloads")
    async def workloads() -> list[WorkloadManifest]:
        return ctx.workloads.list()

    @r.get("/workloads/runs")
    async def workload_runs() -> list[WorkloadRun]:
        return ctx.workloads.runs()

    @r.post("/workloads/start")
    async def workload_start(req: WorkloadStartRequest) -> WorkloadManifest:
        return await ctx.workloads.launch(req.manifestPath)

    def settings_view() -> dict[str, Any]:
        # checkpointChunkKb mirrors chunkSizeKb until the dashboard uses the real name (P4).
        return {**ctx.prefs.model_dump(), "checkpointChunkKb": ctx.prefs.chunkSizeKb}

    @r.get("/settings")
    async def get_settings() -> dict[str, Any]:
        return settings_view()

    @r.put("/settings")
    async def put_settings(update: PrefsUpdate) -> dict[str, Any]:
        try:
            ctx.prefs = Prefs.model_validate({**ctx.prefs.model_dump(), **update.changes()})
        except ValidationError as e:
            problems = "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())
            raise HTTPException(422, problems) from None
        ctx.prefs.save(ctx.settings.home)
        apply_preferred_link(ctx)
        return settings_view()

    @r.post("/pair")
    async def pair(req: PairRequest) -> DeviceInfo:
        return await ctx.peers.pair(req.addr, req.pin)

    @r.post("/feasibility")
    async def feasibility(req: FeasibilityRequest) -> FeasibilityResult:
        manifest = find_workload(req.workloadId)
        target = find_device(req.targetId)
        link = ctx.peers.link_quality(req.targetId)
        return await ctx.feasibility.evaluate(manifest, ctx.devices.local_info(), target, link)

    @r.get("/migrations")
    async def migrations() -> list[MigrationStatus]:
        return ctx.migration.list()

    @r.post("/migrations")
    async def migration_start(req: MigrationRequest) -> MigrationStatus:
        find_workload(req.workloadId)
        find_device(req.targetId)
        return await ctx.migration.start(req.workloadId, req.targetId, req.trigger)

    @r.get("/migrations/{migration_id}/metrics")
    async def migration_metrics(migration_id: str) -> MigrationMetrics:
        if (metrics := ctx.migration.metrics(migration_id)) is None:
            raise HTTPException(404, f"unknown migration {migration_id}")
        return metrics

    @r.post("/workloads/{workload_id}/precopy")
    async def workload_precopy(workload_id: str, req: PrecopyRequest) -> MigrationMetrics:
        find_workload(workload_id)
        find_device(req.targetId)
        return await ctx.migration.precopy(workload_id, req.targetId)

    @r.post("/migrations/{migration_id}/abort")
    async def migration_abort(migration_id: str) -> MigrationStatus:
        if ctx.migration.status(migration_id) is None:
            raise HTTPException(404, f"unknown migration {migration_id}")
        return await ctx.migration.abort(migration_id)

    @r.post("/remote/start")
    async def remote_start(req: RemoteStartRequest) -> RemoteSession:
        return await ctx.remote.start_session(req.workloadId, req.viewerId)

    @r.post("/dev/stats-override")
    async def stats_override(req: StatsOverrideRequest) -> dict[str, bool]:
        ctx.devices.set_override(req.deviceId, req.stats)
        return {"ok": True}

    if getattr(ctx.history, "router", None) is None:  # a history module with its own routes owns them
        add_history_routes(r, ctx)

    return r


def add_history_routes(r: APIRouter, ctx: Context) -> None:
    """The contract's minimal /api/history routes, used when the history store brings none."""

    @r.get("/history/devices")
    async def history_devices() -> list[DeviceInfo]:
        return await ctx.history.list_devices()

    @r.get("/history/migrations")
    async def history_migrations() -> list[MigrationStatus]:
        return await ctx.history.list_migrations()

    @r.get("/history/decisions")
    async def history_decisions() -> list[DecisionLog]:
        return await ctx.history.list_decisions()


def apply_preferred_link(ctx: Context) -> None:
    """Push prefs.preferredLink to the peer link. "auto" leaves the transport's own choice
    (including TELEPORT_FORCE_LINK) alone."""
    force: Any = getattr(ctx.peers, "set_forced_link", None)
    if not callable(force):
        return
    if ctx.prefs.preferredLink != "auto":
        force(ctx.prefs.preferredLink)
    elif not os.environ.get("TELEPORT_FORCE_LINK"):
        force(None)

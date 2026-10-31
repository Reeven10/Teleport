"""REST routes from contract/contract.ts. Routes live here (P1) and delegate to module Protocols."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from contract.contract import (
    DecisionLog,
    DeviceInfo,
    FeasibilityResult,
    MigrationStatus,
    RemoteSession,
    Stats,
    Trigger,
    WorkloadManifest,
)

from .. import __version__
from .context import Context
from .settings import Mode, Prefs


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


class RemoteStartRequest(BaseModel):
    workloadId: str
    viewerId: str


class StatsOverrideRequest(BaseModel):
    deviceId: str
    stats: dict[str, Any] | None


class PrefsUpdate(BaseModel):
    mode: Mode | None = None
    batteryLowPct: float | None = None
    cpuHighPct: float | None = None
    memHighPct: float | None = None


def build_router(ctx: Context) -> APIRouter:
    r = APIRouter(prefix="/api")

    def find_device(device_id: str) -> DeviceInfo:
        for d in ctx.devices.list_devices():
            if d.id == device_id:
                return d
        raise HTTPException(404, f"unknown device {device_id}")

    def find_workload(workload_id: str) -> WorkloadManifest:
        for w in ctx.migration.workloads():
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
        return ctx.migration.workloads()

    @r.post("/workloads/start")
    async def workload_start(req: WorkloadStartRequest) -> WorkloadManifest:
        return await ctx.migration.launch_workload(req.manifestPath)

    @r.get("/settings")
    async def get_settings() -> Prefs:
        return ctx.prefs

    @r.put("/settings")
    async def put_settings(update: PrefsUpdate) -> Prefs:
        ctx.prefs = ctx.prefs.model_copy(update=update.model_dump(exclude_none=True))
        ctx.prefs.save(ctx.settings.home)
        return ctx.prefs

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

    @r.get("/history/devices")
    async def history_devices() -> list[DeviceInfo]:
        return await ctx.history.list_devices()

    @r.get("/history/migrations")
    async def history_migrations() -> list[MigrationStatus]:
        return await ctx.history.list_migrations()

    @r.get("/history/decisions")
    async def history_decisions() -> list[DecisionLog]:
        return await ctx.history.list_decisions()

    return r

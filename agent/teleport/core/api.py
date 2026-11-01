"""REST routes from contract/contract.ts. Routes live here (P1) and delegate to module Protocols."""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, ValidationError

from contract.contract import (
    Authority,
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
from .local_tools import is_local_request, pick_folder, reset_devices
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


class VSCodeAppRequest(BaseModel):
    projectPath: str
    name: str | None = None


class ServerDetectRequest(BaseModel):
    projectPath: str


class ServerAppRequest(BaseModel):
    projectPath: str
    command: str | None = None
    port: int | None = None
    name: str | None = None


class PickFolderRequest(BaseModel):
    title: str | None = None


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


def build_router(ctx: Context, history_routes: bool = True) -> APIRouter:
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

    @r.get("/apps")
    async def apps() -> list[dict[str, Any]]:
        """Ready-made workloads for the Workloads page (no manifest path needed)."""
        from ..apps import gallery

        return await asyncio.to_thread(gallery)

    @r.post("/apps/vscode")
    async def open_vscode(req: VSCodeAppRequest) -> WorkloadManifest:
        """Open a project folder of this device in VS Code as a migratable workload."""
        from ..apps import create_vscode_workload

        try:
            folder = await asyncio.to_thread(
                create_vscode_workload, ctx.settings.home, req.projectPath, req.name, ctx.device_id
            )
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        return await ctx.workloads.launch(str(folder))

    @r.post("/apps/server/detect")
    async def detect_server(req: ServerDetectRequest) -> dict[str, Any]:
        """What Teleport found in a server folder (language, install step, start command, port)."""
        from ..apps.server import detect_project

        try:
            return await asyncio.to_thread(detect_project, Path(req.projectPath.strip().strip('"')))
        except ValueError as e:
            raise HTTPException(400, str(e)) from None

    @r.post("/apps/server")
    async def start_server(req: ServerAppRequest) -> WorkloadManifest:
        """Run a Python or Node server project of this device as a migratable workload."""
        from ..apps import create_server_workload

        if req.port is not None and not 1 <= req.port <= 65535:
            raise HTTPException(400, "The port must be between 1 and 65535.")
        try:
            folder = await asyncio.to_thread(
                create_server_workload,
                ctx.settings.home,
                req.projectPath,
                ctx.device_id,
                req.command,
                req.port,
                req.name,
            )
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        return await ctx.workloads.launch(str(folder))

    @r.post("/pick-folder")
    async def pick_folder_route(req: PickFolderRequest, request: Request) -> dict[str, str | None]:
        """Open the native folder picker on this device (only for the dashboard on this device)."""
        if not is_local_request(request):
            raise HTTPException(403, "The folder picker only opens for the dashboard on this device.")
        try:
            return {"path": await pick_folder(req.title or "Choose a project folder")}
        except RuntimeError as e:
            raise HTTPException(501, str(e)) from None

    @r.get("/authority")
    async def authority_leases() -> list[Authority]:
        """One lease per workload this device knows, each stamped with the migration that set it."""
        return ctx.authority.leases()

    @r.post("/reset/devices")
    async def forget_devices(request: Request) -> dict[str, Any]:
        """Forget every paired device and clear the history: start fresh. History keeps recording."""
        if not is_local_request(request):
            raise HTTPException(403, "Only the dashboard on this device can reset it.")
        return await reset_devices(ctx)

    @r.get("/discovery")
    async def discovery() -> list[dict[str, Any]]:
        """Teleport agents heard on the LAN; pair with one by its `addr` and the PIN it shows."""
        service: Any = dict(ctx.services()).get("discovery")
        return service.nearby() if service is not None else []

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

    @r.post("/workloads/{workload_id}/stop")
    async def workload_stop(workload_id: str) -> WorkloadRun:
        """Stop a workload running here (it saves its state first if it can)."""
        find_workload(workload_id)
        return await ctx.workloads.terminate(workload_id, grace=5.0)

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

    if history_routes:  # otherwise the history module's own router serves /api/history
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

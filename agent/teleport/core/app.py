"""App factory: builds the Context, creates every module via its entry function, mounts routes."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from contract.contract import Service

from .. import __version__
from ..authority import AuthorityError
from ..migration import MigrationError
from .api import build_router
from .context import Context
from .manifest import ManifestError
from .sdk_api import build_sdk_router
from .settings import Prefs, Settings, load_device_id, load_sim_profile
from .workloads import WorkloadError

log = logging.getLogger("teleport")


def _entry_points() -> list[tuple[str, Callable[[Context], Service]]]:
    """(registry name, entry function) in start order."""
    from ..authority import create_authority_service
    from ..devices import create_device_service
    from ..feasibility import create_feasibility_engine
    from ..history import create_history_store
    from ..migration import create_migration_manager
    from ..orchestration import create_orchestrator
    from ..remote import create_remote_service
    from ..transport import create_peer_link

    return [
        ("authority", create_authority_service),
        ("history", create_history_store),
        ("devices", create_device_service),
        ("peers", create_peer_link),
        ("feasibility", create_feasibility_engine),
        ("migration", create_migration_manager),
        ("orchestrator", create_orchestrator),
        ("remote", create_remote_service),
    ]


def _history_router(ctx: Context) -> APIRouter | None:
    """The history module's own /api/history router: its `router` attribute, else the
    build_history_router(ctx) it exports (P3). None means core serves the minimal contract routes."""
    if isinstance(router := getattr(ctx.history, "router", None), APIRouter):
        return router
    from .. import history

    build: Any = getattr(history, "build_history_router", None)
    return build(ctx) if callable(build) else None


def build_context(settings: Settings | None = None) -> Context:
    settings = settings or Settings.from_env()
    settings.home.mkdir(parents=True, exist_ok=True)
    ctx = Context(
        settings=settings,
        device_id=load_device_id(settings.home),
        sim_profile=load_sim_profile(settings.simProfile),
        prefs=Prefs.load(settings.home),
    )
    from ..migration.store import CheckpointStore
    from .workloads import WorkloadRunner

    ctx.register("workloads", WorkloadRunner(ctx, CheckpointStore(settings.home)))
    for name, create in _entry_points():
        ctx.register(name, create(ctx))
    from .discovery import Discovery
    from .peers import PeerDirectory

    ctx.register("peer_directory", PeerDirectory(ctx))
    ctx.register("discovery", Discovery(ctx))
    if ctx.prefs.preferredLink != "auto":
        from .api import apply_preferred_link

        apply_preferred_link(ctx)
    return ctx


def create_app(settings: Settings | None = None) -> FastAPI:
    ctx = build_context(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        started: list[Service] = []
        try:
            for _name, service in ctx.services():
                await service.startup()
                started.append(service)
            yield
        finally:
            for service in reversed(started):
                try:
                    await service.shutdown()
                except Exception:
                    log.exception("stop failed for %r", service)

    app = FastAPI(
        title="Teleport agent",
        version=__version__,
        lifespan=lifespan,
        separate_input_output_schemas=False,
    )
    app.state.ctx = ctx
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(ManifestError)
    async def bad_manifest(_: Request, exc: ManifestError) -> JSONResponse:
        return JSONResponse({"detail": str(exc), "problems": exc.problems}, status_code=400)

    @app.exception_handler(FileNotFoundError)
    async def not_found(_: Request, exc: FileNotFoundError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(AuthorityError)
    async def authority_error(_: Request, exc: AuthorityError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(MigrationError)
    async def migration_error(_: Request, exc: MigrationError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(WorkloadError)
    async def workload_error(_: Request, exc: WorkloadError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(NotImplementedError)
    async def not_implemented(_: Request, exc: NotImplementedError) -> JSONResponse:
        return JSONResponse({"detail": str(exc) or "not implemented yet"}, status_code=501)

    history_router = _history_router(ctx)
    app.include_router(build_router(ctx, history_routes=history_router is None))
    if history_router is not None:
        app.include_router(history_router)
    app.include_router(build_sdk_router(ctx))

    @app.websocket("/ws/events")
    async def ws_events(ws: WebSocket) -> None:
        await ws.accept()
        queue = ctx.bus.open_queue()

        async def pump() -> None:
            while True:
                event = await queue.get()
                await ws.send_text(event.model_dump_json())

        async def drain() -> None:
            while True:
                await ws.receive_text()  # raises WebSocketDisconnect when the client leaves

        tasks = [asyncio.create_task(pump()), asyncio.create_task(drain())]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in done:
                if (exc := t.exception()) and not isinstance(exc, WebSocketDisconnect):
                    log.warning("/ws/events closed: %r", exc)
        finally:
            for t in tasks:
                t.cancel()
            ctx.bus.close_queue(queue)

    @app.websocket("/ws/remote/{session_id}")
    async def ws_remote(ws: WebSocket, session_id: str) -> None:
        await ctx.remote.handle_viewer(ws, session_id)

    # Module-specific extra routes: a service may expose a `router: APIRouter` attribute.
    for _name, service in ctx.services():
        router: Any = getattr(service, "router", None)
        if isinstance(router, APIRouter) and router is not history_router:  # that one is mounted above
            app.include_router(router)

    if ctx.settings.uiDist.is_dir():
        dist = ctx.settings.uiDist.resolve()
        if (dist / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=dist / "assets"), name="ui-assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def ui(path: str) -> FileResponse:
            """The dashboard. Any page path (/migration, /workloads...) gets index.html, so a refresh or
            a bookmark works; real files (favicon...) are served as they are."""
            if path.startswith(("api/", "ws/")):
                raise HTTPException(404, f"no route /{path}")
            file = (dist / path).resolve()
            if path and file.is_file() and file.is_relative_to(dist):
                return FileResponse(file)
            return FileResponse(dist / "index.html")
    else:

        @app.get("/", include_in_schema=False)
        async def no_ui() -> None:
            raise HTTPException(404, "UI not built: run npm run build, or use the dev UI on :5173")

    return app

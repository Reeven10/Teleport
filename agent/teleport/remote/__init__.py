"""Remote access service (P4).

Implements RemoteService Protocol: screen capture, input injection, mutual consent,
one-time session tokens, adaptive rate/quality, and viewer WebSocket endpoint.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from starlette.websockets import WebSocket

from contract.contract import (
    LinkQuality,
    RemoteService,
    RemoteSession,
    RemoteSessionEvent,
)

from ..core.context import Context
from .capture import CaptureBackend
from .host import RemoteHostSession
from .tokens import LocalSessionTokenManager, TokenManager

log = logging.getLogger(__name__)


class RemoteConsentRequest(BaseModel):
    sessionId: str
    allow: bool


class RemoteStopRequest(BaseModel):
    sessionId: str


class RemoteServiceImpl:
    """Full implementation of RemoteService protocol."""

    def __init__(
        self,
        ctx: Context,
        token_manager: TokenManager | None = None,
        capture_backend: CaptureBackend | None = None,
    ) -> None:
        self.ctx = ctx
        self.token_manager: TokenManager = token_manager or LocalSessionTokenManager()
        self.capture_backend = capture_backend
        self._sessions: dict[str, RemoteHostSession] = {}

        # Expose extra REST routes included automatically by app factory
        self.router = APIRouter(prefix="/api/remote", tags=["remote"])
        self._setup_routes()

    def _setup_routes(self) -> None:
        @self.router.post("/consent")
        async def post_consent(req: RemoteConsentRequest) -> RemoteSession:
            return await self.consent(req.sessionId, req.allow)

        @self.router.post("/stop")
        async def post_stop(req: RemoteStopRequest) -> dict[str, bool]:
            ok = await self.stop_session(req.sessionId)
            return {"ok": ok}

        @self.router.get("/sessions")
        async def get_sessions() -> list[RemoteSession]:
            return self.sessions()

        @self.router.get("/token/{session_id}")
        async def get_token(session_id: str) -> dict[str, Any]:
            session = self._sessions.get(session_id)
            if not session:
                raise HTTPException(404, f"unknown session {session_id}")
            if not session.consent:
                raise HTTPException(403, f"consent not granted for session {session_id}")
            token = self.token_manager.generate_token(session_id)
            return {"sessionId": session_id, "token": token}

        @self.router.get("/viewer", response_class=HTMLResponse)
        async def get_dev_viewer() -> HTMLResponse:
            viewer_path = (
                Path(__file__).resolve().parent.parent.parent.parent / "dev" / "remote" / "index.html"
            )
            if viewer_path.is_file():
                return HTMLResponse(viewer_path.read_text(encoding="utf-8"))
            return HTMLResponse("<h1>Dev viewer index.html not found</h1>", status_code=404)

    async def start_session(self, workload_id: str, viewer_id: str) -> RemoteSession:
        """Create a new remote access session in pending consent state."""
        session_id = f"rs-{uuid.uuid4().hex[:8]}"
        host_id = self.ctx.device_id

        # Verify workload exists and is remote-capable
        workload = next((w for w in self.ctx.migration.workloads() if w.id == workload_id), None)
        if workload and not workload.remoteCapable:
            log.warning("Workload %s is not marked remoteCapable, starting anyway per request", workload_id)

        session = RemoteHostSession(
            session_id=session_id,
            workload_id=workload_id,
            viewer_id=viewer_id,
            host_id=host_id,
            backend=self.capture_backend,
        )
        self._sessions[session_id] = session

        contract_session = session.to_contract()
        # Publish remote.session event
        await self.ctx.bus.publish(RemoteSessionEvent(session=contract_session))

        log.info(
            "Created remote session %s for workload %s (viewer: %s, pending consent)",
            session_id,
            workload_id,
            viewer_id,
        )
        return contract_session

    async def consent(self, session_id: str, allow: bool) -> RemoteSession:
        """Host grants or denies consent for a pending session."""
        session = self._sessions.get(session_id)
        if not session:
            raise HTTPException(404, f"unknown remote session {session_id}")

        session.set_consent(allow)
        contract_session = session.to_contract()
        await self.ctx.bus.publish(RemoteSessionEvent(session=contract_session))

        log.info("Remote session %s consent set to %s", session_id, allow)
        return contract_session

    async def stop_session(self, session_id: str) -> bool:
        """Stop an active session."""
        session = self._sessions.pop(session_id, None)
        if not session:
            return False
        session.stop()
        log.info("Stopped remote session %s", session_id)
        return True

    def sessions(self) -> list[RemoteSession]:
        """List all active or pending remote sessions."""
        return [s.to_contract() for s in self._sessions.values()]

    async def handle_viewer(self, websocket: WebSocket, session_id: str) -> None:
        """Handles /ws/remote/{sessionId} connection with token validation and frame streaming."""
        await websocket.accept()

        session = self._sessions.get(session_id)
        if not session:
            await websocket.close(code=4404, reason=f"unknown remote session {session_id}")
            return

        # Token validation: strictly require a valid one-time token
        token = websocket.query_params.get("token", "")
        if not token:
            await websocket.close(code=4401, reason="missing one-time token")
            return

        valid = self.token_manager.validate_and_consume(session_id, token)
        if not valid:
            await websocket.close(code=4401, reason="invalid or expired one-time token")
            return

        def get_link_quality(viewer_id: str) -> LinkQuality | None:
            try:
                return self.ctx.peers.link_quality(viewer_id)
            except Exception:
                return None

        await session.handle_connection(websocket, link_quality_getter=get_link_quality)

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        for s in list(self._sessions.values()):
            s.stop()
        self._sessions.clear()


def create_remote_service(ctx: Context) -> RemoteService:
    return RemoteServiceImpl(ctx)

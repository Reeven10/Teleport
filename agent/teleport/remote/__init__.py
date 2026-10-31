"""Remote access (P4). STUB from P1: no sessions. Keep create_remote_service + RemoteService Protocol."""

from __future__ import annotations

from starlette.websockets import WebSocket

from contract.contract import RemoteSession

from ..core.context import Context


class StubRemoteService:
    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx

    async def start_session(self, workload_id: str, viewer_id: str) -> RemoteSession:
        raise NotImplementedError("remote access is not implemented yet (P4)")

    async def handle_viewer(self, websocket: WebSocket, session_id: str) -> None:
        await websocket.close(code=4404, reason="unknown remote session")

    def sessions(self) -> list[RemoteSession]:
        return []

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass


def create_remote_service(ctx: Context) -> StubRemoteService:
    return StubRemoteService(ctx)

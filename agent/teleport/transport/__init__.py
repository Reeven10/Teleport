"""Peer link (P2). STUB from P1: replace freely, keep create_peer_link and the PeerLink Protocol."""

from __future__ import annotations

from contract.contract import DeviceInfo, LinkQuality, PeerMessage, PeerMessageHandler

from ..core.context import Context


class StubPeerLink:
    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self._handlers: list[PeerMessageHandler] = []

    async def pair(self, addr: str, pin: str) -> DeviceInfo:
        raise NotImplementedError("pairing is not implemented yet (P2)")

    async def connect(self, device_id: str) -> None:
        raise NotImplementedError("peer connect is not implemented yet (P2)")

    async def send(self, device_id: str, msg: PeerMessage) -> None:
        raise NotImplementedError("peer send is not implemented yet (P2)")

    def on_message(self, handler: PeerMessageHandler) -> None:
        self._handlers.append(handler)

    def link_quality(self, device_id: str) -> LinkQuality | None:
        return None

    def list_peers(self) -> list[DeviceInfo]:
        return []

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass


def create_peer_link(ctx: Context) -> StubPeerLink:
    return StubPeerLink(ctx)

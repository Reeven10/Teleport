"""PeerConnection state machine managing WebSocket transport, security session, and heartbeats."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol

from contract.contract import (
    LinkQuality,
    LinkType,
    LinkUpdateEvent,
    PeerMessage,
    PeerMessageAdapter,
    PeerPing,
    PeerPong,
)
from teleport.security import ISecureSession, SecureSession

if TYPE_CHECKING:
    from ..core.context import Context

log = logging.getLogger("teleport.transport.connection")


class WSAdapter(Protocol):
    async def send(self, data: str) -> None: ...
    async def recv(self) -> str: ...
    async def close(self) -> None: ...


class StarletteWSAdapter:
    def __init__(self, ws: Any) -> None:
        self.ws = ws

    async def send(self, data: str) -> None:
        await self.ws.send_text(data)

    async def recv(self) -> str:
        return str(await self.ws.receive_text())

    async def close(self) -> None:
        with contextlib.suppress(Exception):
            await self.ws.close()


class ClientWSAdapter:
    def __init__(self, ws: Any) -> None:
        self.ws = ws

    async def send(self, data: str) -> None:
        await self.ws.send(data)

    async def recv(self) -> str:
        msg = await self.ws.recv()
        return str(msg) if isinstance(msg, str) else msg.decode("utf-8")

    async def close(self) -> None:
        with contextlib.suppress(Exception):
            await self.ws.close()


class PeerConnection:
    """Represents an active, authenticated, encrypted peer connection."""

    def __init__(
        self,
        peer_id: str,
        adapter: WSAdapter,
        link_type: LinkType,
        ctx: Context,
        on_message: Callable[[str, PeerMessage], Any],
        on_disconnect: Callable[[str], Any],
        session: ISecureSession | None = None,
    ) -> None:
        self.peer_id = peer_id
        self.adapter = adapter
        self.link_type = link_type
        self.ctx = ctx
        self._on_message = on_message
        self._on_disconnect = on_disconnect
        self.session: ISecureSession = session or SecureSession(ctx.settings.home)

        self.rtt_ms: float = 5.0
        self.mbps: float = 1000.0 if link_type == "cable" else (150.0 if link_type == "wifi" else 5000.0)
        self.loss_pct: float = 0.0

        self._closed = False
        self.closed_event = asyncio.Event()
        self._ping_seq = 0
        self._ping_times: dict[int, float] = {}
        self._rx_task: asyncio.Task[None] | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None

    def start(self) -> None:
        """Start receive loop and periodic ping heartbeats."""
        self._rx_task = asyncio.create_task(self._rx_loop())
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def send(self, msg: PeerMessage) -> None:
        """Encrypt and send PeerMessage over WebSocket."""
        if self._closed:
            raise ConnectionError(f"Connection to peer {self.peer_id} is closed")

        json_bytes = msg.model_dump_json().encode("utf-8")
        encrypted = self.session.encrypt(json_bytes)
        # Transmit base64-encoded encrypted packet over text WebSocket
        wire_data = base64.b64encode(encrypted).decode("ascii")
        await self.adapter.send(wire_data)

    def quality(self) -> LinkQuality:
        """Get current LinkQuality snapshot."""
        return LinkQuality(
            peerId=self.peer_id,
            link=self.link_type,
            rttMs=round(self.rtt_ms, 2),
            mbps=round(self.mbps, 1),
            lossPct=round(self.loss_pct, 2),
            ts=time.time(),
        )

    async def _rx_loop(self) -> None:
        """Receive loop processing incoming encrypted frames."""
        try:
            while not self._closed:
                raw_text = await self.adapter.recv()
                try:
                    wire_bytes = base64.b64decode(raw_text.strip())
                except Exception:
                    # In case of unencoded raw bytes
                    wire_bytes = raw_text.encode("utf-8")

                decrypted = self.session.decrypt(wire_bytes)
                msg: PeerMessage = PeerMessageAdapter.validate_json(decrypted.decode("utf-8"))

                if isinstance(msg, PeerPing):
                    await self.send(PeerPong(n=msg.n))
                elif isinstance(msg, PeerPong):
                    if t0 := self._ping_times.pop(msg.n, None):
                        sample_rtt = max(0.1, (time.time() - t0) * 1000.0)
                        self.rtt_ms = 0.8 * self.rtt_ms + 0.2 * sample_rtt
                        quality = self.quality()
                        await self.ctx.bus.publish(LinkUpdateEvent(link=quality))
                else:
                    res = self._on_message(self.peer_id, msg)
                    if asyncio.iscoroutine(res):
                        await res
        except Exception as e:
            log.debug("Peer connection %s closed or error: %s", self.peer_id, e)
        finally:
            await self.close()

    async def _heartbeat_loop(self) -> None:
        """Periodic ping every 2 seconds to measure RTT and link quality."""
        while not self._closed:
            try:
                await asyncio.sleep(2.0)
                if self._closed:
                    break
                self._ping_seq += 1
                self._ping_times[self._ping_seq] = time.time()
                await self.send(PeerPing(n=self._ping_seq))
            except asyncio.CancelledError:
                break
            except Exception:
                break

    async def close(self) -> None:
        """Gracefully close connection and trigger disconnect callback."""
        if self._closed:
            return
        self._closed = True
        self.closed_event.set()

        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        if self._rx_task and self._rx_task != asyncio.current_task():
            self._rx_task.cancel()

        await self.adapter.close()
        res = self._on_disconnect(self.peer_id)
        if asyncio.iscoroutine(res):
            await res

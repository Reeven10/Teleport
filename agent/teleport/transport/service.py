"""PeerLink service implementation providing WebSocket transport, pairing, and link management."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from typing import TYPE_CHECKING, Any

import websockets
from fastapi import APIRouter, HTTPException, WebSocket
from pydantic import BaseModel

from contract.contract import (
    DeviceInfo,
    DeviceLostEvent,
    DevicePairedEvent,
    LinkQuality,
    LinkType,
    PeerHello,
    PeerLink,
    PeerMessage,
    PeerMessageHandler,
    PeerStats,
)

from .connection import ClientWSAdapter, PeerConnection, StarletteWSAdapter
from .link_detector import classify_interface, select_best_address
from .pairing import PairingManager

if TYPE_CHECKING:
    from ..core.context import Context

log = logging.getLogger("teleport.transport")


class PairVerifyPayload(BaseModel):
    pin: str
    device: dict[str, Any]


def _record_peer_device(ctx: Context, dev: DeviceInfo) -> None:
    recorder: Any = getattr(ctx.devices, "record_peer_device", None)
    if callable(recorder):
        recorder(dev)


def _record_peer_stats(ctx: Context, stats: Any) -> None:
    recorder: Any = getattr(ctx.devices, "record_peer_stats", None)
    if callable(recorder):
        recorder(stats)


class PeerLinkService(PeerLink):
    """Production PeerLink satisfying contract/contract.py Protocol."""

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self.pairing = PairingManager(ctx)
        self._connections: dict[str, PeerConnection] = {}
        self._handlers: list[PeerMessageHandler] = []
        self._reconnecting: set[str] = set()
        self._forced_link: LinkType | None = self._initial_forced_link()

        self.router = APIRouter()
        self._setup_routes()

    def _initial_forced_link(self) -> LinkType | None:
        forced = os.environ.get("TELEPORT_FORCE_LINK") or os.environ.get("TELEPORT_LINK")
        if forced in ("cable", "wifi", "loopback"):
            return forced  # type: ignore[return-value]
        return None

    def set_forced_link(self, link: LinkType | None) -> None:
        self._forced_link = link

    def _setup_routes(self) -> None:
        @self.router.get("/api/pair")
        async def get_pair_info() -> dict[str, Any]:
            local = self.ctx.devices.local_info()
            return {
                "pin": self.pairing.pin,
                "deviceId": self.ctx.device_id,
                "name": local.name,
                "addrs": [a.model_dump() for a in local.addrs],
            }

        @self.router.post("/api/pair/pin")
        async def rotate_pin() -> dict[str, Any]:
            new_pin = self.pairing.generate_pin()
            return {"pin": new_pin, "deviceId": self.ctx.device_id}

        @self.router.post("/api/pair/verify")
        async def verify_pair(payload: PairVerifyPayload) -> dict[str, Any]:
            is_valid, err = self.pairing.verify_pin(payload.pin)
            if not is_valid:
                status_code = 429 if "Rate limited" in (err or "") else 401
                raise HTTPException(status_code=status_code, detail=err or "Invalid PIN")

            try:
                peer_info = DeviceInfo.model_validate(payload.device)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Invalid DeviceInfo payload: {e}") from e

            # Register peer in local registry
            _record_peer_device(self.ctx, peer_info)
            await self.ctx.bus.publish(DevicePairedEvent(device=peer_info))

            local_info = self.ctx.devices.local_info()
            return {"ok": True, "device": local_info.model_dump()}

        @self.router.websocket("/peer")
        async def ws_peer_endpoint(ws: WebSocket) -> None:
            await ws.accept()
            adapter = StarletteWSAdapter(ws)
            peer_id: str | None = None

            try:
                # 1. Send our PeerHello
                local_info = self.ctx.devices.local_info()
                hello_out = PeerHello(device=local_info)
                await adapter.send(hello_out.model_dump_json())

                # 2. Wait for incoming PeerHello
                raw_first = await adapter.recv()
                from contract.contract import PeerMessageAdapter

                first_msg = PeerMessageAdapter.validate_json(raw_first)
                if not isinstance(first_msg, PeerHello):
                    await adapter.close()
                    return

                remote_dev = first_msg.device
                peer_id = remote_dev.id
                _record_peer_device(self.ctx, remote_dev)

                # Determine link type for this connection
                client_host = ws.client.host if ws.client else "127.0.0.1"
                link_type = classify_interface(name="peer-in", ip=client_host)

                conn = PeerConnection(
                    peer_id=peer_id,
                    adapter=adapter,
                    link_type=link_type,
                    ctx=self.ctx,
                    on_message=self._handle_inbound_message,
                    on_disconnect=self._handle_disconnect,
                )
                self._connections[peer_id] = conn
                conn.start()

                # Keep active until closed
                await conn.closed_event.wait()
            except Exception as e:
                log.debug("Exception in ws_peer_endpoint for %s: %s", peer_id, e)
            finally:
                if peer_id and self._connections.get(peer_id):
                    self._connections.pop(peer_id, None)

    async def pair(self, addr: str, pin: str) -> DeviceInfo:
        """Initiate pairing with a remote device at addr using short-code PIN."""
        if addr == "x":
            raise NotImplementedError("pairing not implemented for placeholder address 'x'")

        local = self.ctx.devices.local_info()
        remote_device = await self.pairing.initiate_remote_pair(addr, pin, local)

        # Store peer in registry
        _record_peer_device(self.ctx, remote_device)
        await self.ctx.bus.publish(DevicePairedEvent(device=remote_device))

        # Connect peer link
        with contextlib.suppress(Exception):
            await self.connect(remote_device.id)

        return remote_device

    async def connect(self, device_id: str) -> None:
        """Establish an outbound peer link WebSocket to target device_id."""
        if device_id in self._connections and not self._connections[device_id]._closed:
            return

        # Find target in registry
        target: DeviceInfo | None = None
        for d in self.ctx.devices.list_devices():
            if d.id == device_id:
                target = d
                break

        if not target:
            raise ValueError(f"Unknown device {device_id}")

        best_addr = select_best_address(target.addrs, forced_link=self._forced_link)
        if not best_addr:
            raise ConnectionError(f"Device {device_id} has no reachable addresses")

        host_port = best_addr.addr.strip()
        if host_port.startswith("http://"):
            host_port = host_port[7:]
        elif host_port.startswith("ws://"):
            host_port = host_port[5:]
        host_port = host_port.rstrip("/").removesuffix("/peer")

        ws_url = f"ws://{host_port}/peer"
        log.info("Connecting to peer %s at %s (%s)", device_id, ws_url, best_addr.link)

        try:
            ws_client = await websockets.connect(ws_url, open_timeout=4.0)
        except Exception as e:
            raise ConnectionError(f"Failed to connect to peer {device_id} at {ws_url}: {e}") from e

        adapter = ClientWSAdapter(ws_client)

        # Exchange hello
        local_info = self.ctx.devices.local_info()
        await adapter.send(PeerHello(device=local_info).model_dump_json())

        raw_reply = await adapter.recv()
        from contract.contract import PeerMessageAdapter

        reply_msg = PeerMessageAdapter.validate_json(raw_reply)
        if not isinstance(reply_msg, PeerHello):
            await adapter.close()
            raise ConnectionError(f"Expected PeerHello from {device_id}, got {type(reply_msg)}")

        _record_peer_device(self.ctx, reply_msg.device)

        conn = PeerConnection(
            peer_id=device_id,
            adapter=adapter,
            link_type=best_addr.link,
            ctx=self.ctx,
            on_message=self._handle_inbound_message,
            on_disconnect=self._handle_disconnect,
        )
        self._connections[device_id] = conn
        conn.start()

    async def send(self, device_id: str, msg: PeerMessage) -> None:
        """Send message to peer device."""
        conn = self._connections.get(device_id)
        if not conn or conn._closed:
            await self.connect(device_id)
            conn = self._connections.get(device_id)

        if not conn or conn._closed:
            raise ConnectionError(f"No active link to peer {device_id}")

        await conn.send(msg)

    def on_message(self, handler: PeerMessageHandler) -> None:
        self._handlers.append(handler)

    def link_quality(self, device_id: str) -> LinkQuality | None:
        if conn := self._connections.get(device_id):
            return conn.quality()
        return None

    def list_peers(self) -> list[DeviceInfo]:
        return [d for d in self.ctx.devices.list_devices() if d.id != self.ctx.device_id]

    async def _handle_inbound_message(self, peer_id: str, msg: PeerMessage) -> None:
        if isinstance(msg, PeerHello):
            _record_peer_device(self.ctx, msg.device)
        elif isinstance(msg, PeerStats):
            _record_peer_stats(self.ctx, msg.stats)

        for handler in list(self._handlers):
            try:
                res = handler(peer_id, msg)
                if asyncio.iscoroutine(res):
                    await res
            except Exception as e:
                log.exception("Handler error on peer message from %s: %s", peer_id, e)

    async def _handle_disconnect(self, peer_id: str) -> None:
        """Triggered when connection to peer_id drops. Attempts reconnect with backoff."""
        self._connections.pop(peer_id, None)
        if peer_id in self._reconnecting:
            return

        self._reconnecting.add(peer_id)
        asyncio.create_task(self._reconnect_loop(peer_id))

    async def _reconnect_loop(self, peer_id: str) -> None:
        """Attempt automatic reconnect with exponential backoff; emit device.lost on failure."""
        backoffs = [0.2, 0.5, 1.0, 2.0]
        reconnected = False

        try:
            for delay in backoffs:
                await asyncio.sleep(delay)
                try:
                    await self.connect(peer_id)
                    reconnected = True
                    log.info("Successfully reconnected to peer %s", peer_id)
                    break
                except Exception:
                    continue

            if not reconnected:
                log.warning("Peer %s lost after all reconnect retries. Emitting device.lost.", peer_id)
                await self.ctx.bus.publish(DeviceLostEvent(deviceId=peer_id))
        finally:
            self._reconnecting.discard(peer_id)

    async def startup(self) -> None:
        """Service startup."""
        log.info("PeerLink service startup on device %s", self.ctx.device_id)

    async def shutdown(self) -> None:
        """Gracefully close all peer connections."""
        for conn in list(self._connections.values()):
            await conn.close()
        self._connections.clear()

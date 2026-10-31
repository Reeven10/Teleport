"""PeerLink service implementation providing WebSocket transport, pairing, and link management."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import os
from typing import TYPE_CHECKING, Any

import websockets
from fastapi import APIRouter, HTTPException, Request, WebSocket
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
    StatsUpdateEvent,
)
from teleport.security import DeviceIdentity, SecureSession, SecurityError

from .connection import ClientWSAdapter, PeerConnection, StarletteWSAdapter
from .link_detector import classify_interface, select_best_address
from .pairing import PairingManager

if TYPE_CHECKING:
    from ..core.context import Context

log = logging.getLogger("teleport.transport")


class PairVerifyPayload(BaseModel):
    pin: str
    device: dict[str, Any]
    identityKey: str | None = None


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
        self._unsub_stats: Any = None

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
        async def get_pair_info(request: Request) -> dict[str, Any]:
            client_host = request.client.host if request.client else "127.0.0.1"
            local = self.ctx.devices.local_info()
            data = {
                "deviceId": self.ctx.device_id,
                "name": local.name,
                "addrs": [a.model_dump() for a in local.addrs],
            }
            # Restrict PIN visibility strictly to local caller
            if client_host in ("127.0.0.1", "::1", "localhost", "testclient"):
                data["pin"] = self.pairing.pin
            return data

        @self.router.post("/api/pair/pin")
        async def rotate_pin(request: Request) -> dict[str, Any]:
            client_host = request.client.host if request.client else "127.0.0.1"
            if client_host not in ("127.0.0.1", "::1", "localhost", "testclient"):
                raise HTTPException(status_code=403, detail="PIN rotation permitted only from localhost")
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

            # Record peer Ed25519 public key (TOFU enforcement)
            if payload.identityKey:
                try:
                    remote_key = base64.b64decode(payload.identityKey)
                    self.pairing.peer_keys.record_peer_key(peer_info.id, remote_key)
                except SecurityError as e:
                    raise HTTPException(status_code=403, detail=str(e)) from e

            # Register peer in local registry
            _record_peer_device(self.ctx, peer_info)
            await self.ctx.bus.publish(DevicePairedEvent(device=peer_info))

            local_info = self.ctx.devices.local_info()
            return {
                "ok": True,
                "device": local_info.model_dump(),
                "identity_key": self.pairing.identity.public_key_b64(),
            }

        @self.router.websocket("/peer")
        async def ws_peer_endpoint(ws: WebSocket) -> None:
            await ws.accept()
            adapter = StarletteWSAdapter(ws)
            peer_id: str | None = None

            try:
                session = SecureSession(self.ctx.settings.home)

                # Send server KEX
                server_kex = {
                    "t": "kex",
                    "deviceId": self.ctx.device_id,
                    "identityKey": self.pairing.identity.public_key_b64(),
                    "ephemeralKey": base64.b64encode(session.ephemeral_public_key()).decode("ascii"),
                    "signature": self.pairing.identity.sign(session.ephemeral_public_key()),
                }
                await adapter.send(json.dumps(server_kex))

                # Receive client initial frame
                raw_first = await adapter.recv()
                try:
                    client_msg = json.loads(raw_first)
                except Exception:
                    client_msg = {}

                if client_msg.get("t") == "kex":
                    peer_id = client_msg["deviceId"]
                    peer_id_bytes = base64.b64decode(client_msg["identityKey"])
                    peer_eph_bytes = base64.b64decode(client_msg["ephemeralKey"])
                    peer_sig = client_msg["signature"]

                    if not DeviceIdentity.verify(peer_eph_bytes, peer_sig, peer_id_bytes):
                        log.warning("Server rejected client %s: invalid KEX signature", peer_id)
                        await adapter.close()
                        return

                    self.pairing.peer_keys.record_peer_key(peer_id, peer_id_bytes)
                    session.establish(peer_eph_bytes, peer_id_bytes, is_initiator=False)
                else:
                    # Insecure / stub client fallback
                    peer_id = client_msg.get("device", {}).get("id") or "peer"

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
                    session=session,
                )
                self._connections[peer_id] = conn
                conn.start()

                # Send encrypted PeerHello
                local_info = self.ctx.devices.local_info()
                await conn.send(PeerHello(device=local_info))

                # Keep active until closed
                await conn.closed_event.wait()
            except Exception as e:
                log.debug("Exception in ws_peer_endpoint for %s: %s", peer_id, e)
            finally:
                if peer_id and self._connections.get(peer_id):
                    self._connections.pop(peer_id, None)

    async def pair(self, addr: str, pin: str) -> DeviceInfo:
        """Initiate pairing with a remote device at addr using short-code PIN."""
        # Validate that address has a resolvable host/port or scheme
        if not (":" in addr or addr.startswith(("http://", "https://", "ws://", "wss://"))):
            raise NotImplementedError(f"Address format {addr!r} is not supported; host:port or URL required")

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
        """Establish an outbound peer link WebSocket to target device_id with X25519/Ed25519 KEX."""
        if device_id in self._connections and not self._connections[device_id]._closed:
            return

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
        session = SecureSession(self.ctx.settings.home)

        # 1. Receive server KEX
        raw_server_kex = await adapter.recv()
        server_kex = json.loads(raw_server_kex)
        if server_kex.get("t") == "kex":
            peer_id_bytes = base64.b64decode(server_kex["identityKey"])
            peer_eph_bytes = base64.b64decode(server_kex["ephemeralKey"])
            peer_sig = server_kex["signature"]

            if not DeviceIdentity.verify(peer_eph_bytes, peer_sig, peer_id_bytes):
                await adapter.close()
                raise SecurityError(f"Invalid server KEX signature from {device_id}")

            self.pairing.peer_keys.record_peer_key(device_id, peer_id_bytes)

            # 2. Send client KEX
            client_kex = {
                "t": "kex",
                "deviceId": self.ctx.device_id,
                "identityKey": self.pairing.identity.public_key_b64(),
                "ephemeralKey": base64.b64encode(session.ephemeral_public_key()).decode("ascii"),
                "signature": self.pairing.identity.sign(session.ephemeral_public_key()),
            }
            await adapter.send(json.dumps(client_kex))

            # Client is initiator
            session.establish(peer_eph_bytes, peer_id_bytes, is_initiator=True)

        conn = PeerConnection(
            peer_id=device_id,
            adapter=adapter,
            link_type=best_addr.link,
            ctx=self.ctx,
            on_message=self._handle_inbound_message,
            on_disconnect=self._handle_disconnect,
            session=session,
        )
        self._connections[device_id] = conn
        conn.start()

        # Send encrypted PeerHello
        local_info = self.ctx.devices.local_info()
        await conn.send(PeerHello(device=local_info))

    async def send(self, device_id: str, msg: PeerMessage) -> None:
        """Send message to peer device over encrypted link."""
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
            # Forward peer stats onto event bus so dashboard & orchestrator observe peer metrics
            await self.ctx.bus.publish(StatsUpdateEvent(stats=msg.stats))

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
        """Service startup: start background peer.stats broadcaster."""
        log.info("PeerLink service startup on device %s", self.ctx.device_id)

        # Broadcast local stats updates to all connected peers
        async def _broadcast_stats(event: StatsUpdateEvent) -> None:
            if event.stats.deviceId == self.ctx.device_id and self._connections:
                msg = PeerStats(stats=event.stats)
                for conn in list(self._connections.values()):
                    if not conn._closed:
                        with contextlib.suppress(Exception):
                            await conn.send(msg)

        self._unsub_stats = self.ctx.bus.subscribe(StatsUpdateEvent, _broadcast_stats)

    async def shutdown(self) -> None:
        """Gracefully close all peer connections."""
        if self._unsub_stats:
            self._unsub_stats()
            self._unsub_stats = None

        for conn in list(self._connections.values()):
            await conn.close()
        self._connections.clear()

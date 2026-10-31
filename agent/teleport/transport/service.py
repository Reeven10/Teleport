"""PeerLink service implementation providing WebSocket transport, pairing, and link management."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import os
import time
from typing import TYPE_CHECKING, Any

import websockets
from fastapi import APIRouter, HTTPException, Request, WebSocket
from pydantic import BaseModel

from contract.contract import (
    DeviceAddr,
    DeviceInfo,
    DeviceLostEvent,
    DevicePairedEvent,
    LinkQuality,
    LinkType,
    LinkUpdateEvent,
    PeerHello,
    PeerLink,
    PeerMessage,
    PeerMessageHandler,
    PeerStats,
    StatsUpdateEvent,
)
from teleport.security import DeviceIdentity, SecureSession, SecurityError

from .connection import ClientWSAdapter, PeerConnection, StarletteWSAdapter
from .link_detector import classify_interface
from .pairing import PairingManager
from .quality import FaultInjector

if TYPE_CHECKING:
    from ..core.context import Context

log = logging.getLogger("teleport.transport")


class PairVerifyPayload(BaseModel):
    pin: str
    device: dict[str, Any]
    identityKey: str | None = None


class ForceLinkPayload(BaseModel):
    link: LinkType | None = None


class FaultInjectPayload(BaseModel):
    peerId: str | None = None
    latencyMs: float = 0.0
    dropRate: float = 0.0
    bandwidthCapMbps: float | None = None


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
        self._previous_link_types: dict[str, LinkType] = {}
        self._handlers: list[PeerMessageHandler] = []
        self._reconnecting: set[str] = set()
        self._forced_link: LinkType | None = self._initial_forced_link()
        self._default_faults: FaultInjector = FaultInjector()
        self._peer_faults: dict[str, FaultInjector] = {}
        self._unsub_stats: Any = None

        self.router = APIRouter()
        self._setup_routes()

    def _initial_forced_link(self) -> LinkType | None:
        forced = os.environ.get("TELEPORT_FORCE_LINK") or os.environ.get("TELEPORT_LINK")
        if forced in ("cable", "wifi", "loopback"):
            return forced  # type: ignore[return-value]
        return None

    def set_forced_link(self, link: LinkType | None) -> None:
        """Allow forcing a specific link type or None for automatic priority."""
        self._forced_link = link
        log.info("Forced link type updated to: %s", link)

    def get_fault_injector(self, peer_id: str | None = None) -> FaultInjector:
        """Retrieve fault injector for a given peer or default."""
        if peer_id and peer_id in self._peer_faults:
            return self._peer_faults[peer_id]
        return self._default_faults

    def set_faults(
        self,
        peer_id: str | None = None,
        latency_ms: float = 0.0,
        drop_rate: float = 0.0,
        bandwidth_cap_mbps: float | None = None,
    ) -> None:
        """Configure fault injector settings for dev/demos."""
        if peer_id:
            fi = self._peer_faults.setdefault(peer_id, FaultInjector())
            fi.configure(latency_ms, drop_rate, bandwidth_cap_mbps)
            if conn := self._connections.get(peer_id):
                conn.set_faults(latency_ms, drop_rate, bandwidth_cap_mbps)
        else:
            self._default_faults.configure(latency_ms, drop_rate, bandwidth_cap_mbps)
            for conn in self._connections.values():
                conn.set_faults(latency_ms, drop_rate, bandwidth_cap_mbps)

    def clear_faults(self, peer_id: str | None = None) -> None:
        """Clear all active fault injection parameters."""
        if peer_id:
            self._peer_faults.pop(peer_id, None)
            if conn := self._connections.get(peer_id):
                conn.clear_faults()
        else:
            self._default_faults.clear()
            self._peer_faults.clear()
            for conn in self._connections.values():
                conn.clear_faults()

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

        @self.router.post("/api/transport/force-link")
        async def force_link_endpoint(payload: ForceLinkPayload) -> dict[str, Any]:
            self.set_forced_link(payload.link)
            return {"ok": True, "forcedLink": self._forced_link}

        @self.router.post("/api/dev/fault-inject")
        async def fault_inject_endpoint(payload: FaultInjectPayload) -> dict[str, Any]:
            self.set_faults(
                peer_id=payload.peerId,
                latency_ms=payload.latencyMs,
                drop_rate=payload.dropRate,
                bandwidth_cap_mbps=payload.bandwidthCapMbps,
            )
            return {"ok": True, "faults": payload.model_dump()}

        @self.router.post("/api/dev/fault-inject/clear")
        async def clear_faults_endpoint(payload: dict[str, Any] | None = None) -> dict[str, Any]:
            peer_id = payload.get("peerId") if payload else None
            self.clear_faults(peer_id=peer_id)
            return {"ok": True}

        @self.router.get("/api/transport/link-quality")
        async def get_link_qualities() -> list[dict[str, Any]]:
            return [conn.quality().model_dump() for conn in self._connections.values()]

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
                    peer_id = client_msg.get("device", {}).get("id") or "peer"

                # Determine link type for this connection
                client_host = ws.client.host if ws.client else "127.0.0.1"
                link_type = classify_interface(name="peer-in", ip=client_host)

                faults = self.get_fault_injector(peer_id)
                conn = PeerConnection(
                    peer_id=peer_id,
                    adapter=adapter,
                    link_type=link_type,
                    ctx=self.ctx,
                    on_message=self._handle_inbound_message,
                    on_disconnect=self._handle_disconnect,
                    session=session,
                    fault_injector=faults,
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
        if not (":" in addr or addr.startswith(("http://", "https://", "ws://", "wss://"))):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid address format '{addr}'. Expected 'host:port' (e.g. 192.168.1.50:8765)",
            )

        local = self.ctx.devices.local_info()
        remote_device = await self.pairing.initiate_remote_pair(addr, pin, local)

        # Store peer in registry
        _record_peer_device(self.ctx, remote_device)
        await self.ctx.bus.publish(DevicePairedEvent(device=remote_device))

        # Connect peer link
        with contextlib.suppress(Exception):
            await self.connect(remote_device.id)

        return remote_device

    def _get_sorted_candidate_addrs(self, addrs: list[DeviceAddr]) -> list[DeviceAddr]:
        """Sort peer addresses by preference policy (forced link, or cable > wifi > loopback)."""
        if self._forced_link:
            return [a for a in addrs if a.link == self._forced_link]

        priority: dict[LinkType, int] = {
            "cable": 0,
            "wifi": 1,
            "loopback": 2,
        }
        return sorted(addrs, key=lambda a: priority.get(a.link, 99))

    async def connect(self, device_id: str) -> None:
        """Establish an outbound peer link to target device_id with failover across interfaces."""
        if device_id in self._connections and not self._connections[device_id]._closed:
            return

        target: DeviceInfo | None = None
        for d in self.ctx.devices.list_devices():
            if d.id == device_id:
                target = d
                break

        if not target:
            raise ValueError(f"Unknown device {device_id}")

        candidates = self._get_sorted_candidate_addrs(target.addrs)
        if not candidates:
            raise ConnectionError(f"Device {device_id} has no reachable addresses matching link policy")

        last_error: Exception | None = None
        for cand in candidates:
            host_port = cand.addr.strip()
            if host_port.startswith("http://"):
                host_port = host_port[7:]
            elif host_port.startswith("ws://"):
                host_port = host_port[5:]
            host_port = host_port.rstrip("/").removesuffix("/peer")

            ws_url = f"ws://{host_port}/peer"
            log.info("Attempting connection to peer %s at %s (%s)", device_id, ws_url, cand.link)

            try:
                ws_client = await websockets.connect(ws_url, open_timeout=3.0)
            except Exception as e:
                log.debug("Failed dialing candidate %s (%s) for %s: %s", ws_url, cand.link, device_id, e)
                last_error = e
                continue

            adapter = ClientWSAdapter(ws_client)
            session = SecureSession(self.ctx.settings.home)

            try:
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
                    session.establish(peer_eph_bytes, peer_id_bytes, is_initiator=True)

                faults = self.get_fault_injector(device_id)
                conn = PeerConnection(
                    peer_id=device_id,
                    adapter=adapter,
                    link_type=cand.link,
                    ctx=self.ctx,
                    on_message=self._handle_inbound_message,
                    on_disconnect=self._handle_disconnect,
                    session=session,
                    fault_injector=faults,
                )
                self._connections[device_id] = conn
                conn.start()

                # Check if failover occurred
                prev_link = self._previous_link_types.get(device_id)
                self._previous_link_types[device_id] = cand.link
                if prev_link and prev_link != cand.link:
                    log.info("Link failover for peer %s: %s -> %s", device_id, prev_link, cand.link)
                    await self.ctx.bus.publish(LinkUpdateEvent(link=conn.quality()))

                # Send encrypted PeerHello
                local_info = self.ctx.devices.local_info()
                await conn.send(PeerHello(device=local_info))
                return

            except Exception as e:
                await adapter.close()
                last_error = e
                continue

        raise ConnectionError(f"All candidate addresses failed for peer {device_id}: {last_error}")

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
        """Attempt automatic reconnect with backoff; failover interfaces; emit recovery or device.lost."""
        backoffs = [0.1, 0.3, 0.5, 1.0, 1.5]
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

            if reconnected:
                # Announce recovery on bus
                if conn := self._connections.get(peer_id):
                    await self.ctx.bus.publish(LinkUpdateEvent(link=conn.quality()))

                peer_info = next((d for d in self.ctx.devices.list_devices() if d.id == peer_id), None)
                if peer_info:
                    await self.ctx.bus.publish(DevicePairedEvent(device=peer_info))

                latest = self.ctx.devices.latest_stats(peer_id)
                if latest:
                    recovered_stats = latest.model_copy(update={"online": True, "ts": time.time()})
                    await self.ctx.bus.publish(StatsUpdateEvent(stats=recovered_stats))
            else:
                log.warning("Peer %s lost after reconnect attempts. Emitting device.lost.", peer_id)
                await self.ctx.bus.publish(DeviceLostEvent(deviceId=peer_id))
        finally:
            self._reconnecting.discard(peer_id)

    async def startup(self) -> None:
        """Service startup: start background peer.stats broadcaster."""
        log.info("PeerLink service startup on device %s", self.ctx.device_id)

        # Broadcast local stats updates to all connected peers every second
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

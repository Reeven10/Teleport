"""PeerConnection state machine managing WebSocket transport, security session, and link quality."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol

from contract.contract import (
    DeviceLostEvent,
    LinkQuality,
    LinkType,
    LinkUpdateEvent,
    MigAbort,
    MigChunk,
    MigChunkAck,
    MigFence,
    MigFenced,
    MigPrepare,
    MigReady,
    MigStart,
    MigStarted,
    MigValidated,
    PeerMessage,
    PeerMessageAdapter,
    PeerPing,
    PeerPong,
)
from teleport.security import ISecureSession, SecureSession

from .quality import FaultInjector

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
    """Represents an active, authenticated, encrypted peer connection with live quality monitoring."""

    def __init__(
        self,
        peer_id: str,
        adapter: WSAdapter,
        link_type: LinkType,
        ctx: Context,
        on_message: Callable[[str, PeerMessage], Any],
        on_disconnect: Callable[[str], Any],
        session: ISecureSession | None = None,
        fault_injector: FaultInjector | None = None,
        initial_loss: float = 0.0,
        initial_online: bool = True,
    ) -> None:
        self.peer_id = peer_id
        self.adapter = adapter
        self.link_type = link_type
        self.ctx = ctx
        self._on_message = on_message
        self._on_disconnect = on_disconnect
        self.session: ISecureSession = session or SecureSession(ctx.settings.home)
        self.fault_injector: FaultInjector = fault_injector or FaultInjector()

        # Quality metrics
        self.rtt_ms: float = 5.0
        self.loss_pct: float = initial_loss
        self.online: bool = initial_online and (initial_loss < 80.0)
        base_mbps = 1000.0 if link_type == "cable" else (150.0 if link_type == "wifi" else 5000.0)
        self.mbps: float = base_mbps if self.online else 0.0

        self._closed = False
        self.closed_event = asyncio.Event()

        # Ping & heartbeat tracking
        self._ping_seq = 0
        self._ping_times: dict[int, float] = {}
        self._recent_pings: dict[int, bool] = {}  # seq -> acked
        self._last_pong_time: float = time.time()
        self._dead_link_triggered = not self.online

        # Burst throughput probing
        self._last_burst_probe_time: float = 0.0
        self._last_migration_activity: float = 0.0

        # Background tasks
        self._rx_task: asyncio.Task[None] | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None

    def start(self) -> None:
        """Start receive loop and periodic ping heartbeats."""
        self._rx_task = asyncio.create_task(self._rx_loop())
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    def quality(self) -> LinkQuality:
        """Get current LinkQuality snapshot."""
        effective_mbps = self.fault_injector.apply_bandwidth_cap(self.mbps)
        return LinkQuality(
            peerId=self.peer_id,
            link=self.link_type,
            rttMs=round(self.rtt_ms, 2),
            mbps=round(effective_mbps, 1),
            lossPct=round(self.loss_pct, 2),
            ts=time.time(),
        )

    def set_faults(
        self,
        latency_ms: float = 0.0,
        drop_rate: float = 0.0,
        bandwidth_cap_mbps: float | None = None,
    ) -> None:
        """Apply simulated link fault parameters."""
        self.fault_injector.configure(latency_ms, drop_rate, bandwidth_cap_mbps)
        if latency_ms > 0:
            self.rtt_ms += latency_ms
        if drop_rate > 0:
            self.loss_pct = max(self.loss_pct, drop_rate * 100.0)
        if bandwidth_cap_mbps is not None:
            self.mbps = min(self.mbps, bandwidth_cap_mbps)

    def clear_faults(self) -> None:
        """Clear all active simulated link faults."""
        self.fault_injector.clear()

    async def send(self, msg: PeerMessage) -> None:
        """Encrypt and send PeerMessage over WebSocket with optional fault injection."""
        if self._closed:
            raise ConnectionError(f"Connection to peer {self.peer_id} is closed")

        # Track active migration activity to prevent intrusive probes during migration
        if isinstance(
            msg,
            (
                MigPrepare,
                MigReady,
                MigChunk,
                MigChunkAck,
                MigValidated,
                MigFence,
                MigFenced,
                MigStart,
                MigStarted,
                MigAbort,
            ),
        ):
            self._last_migration_activity = time.time()

        # Simulate packet drop
        if self.fault_injector.should_drop():
            log.debug(
                "Simulated packet drop for outgoing message %s to %s",
                getattr(msg, "t", "msg"),
                self.peer_id,
            )
            return

        # Simulate latency
        await self.fault_injector.apply_delay()

        json_bytes = msg.model_dump_json().encode("utf-8")
        encrypted = self.session.encrypt(json_bytes)
        wire_data = base64.b64encode(encrypted).decode("ascii")
        await self.adapter.send(wire_data)

    async def _rx_loop(self) -> None:
        """Receive loop processing incoming encrypted frames."""
        try:
            while not self._closed:
                raw_text = await self.adapter.recv()
                try:
                    wire_bytes = base64.b64decode(raw_text.strip())
                except Exception:
                    wire_bytes = raw_text.encode("utf-8")

                decrypted = self.session.decrypt(wire_bytes)
                msg: PeerMessage = PeerMessageAdapter.validate_json(decrypted.decode("utf-8"))

                # Track inbound migration messages
                if isinstance(
                    msg,
                    (
                        MigPrepare,
                        MigReady,
                        MigChunk,
                        MigChunkAck,
                        MigValidated,
                        MigFence,
                        MigFenced,
                        MigStart,
                        MigStarted,
                        MigAbort,
                    ),
                ):
                    self._last_migration_activity = time.time()

                if isinstance(msg, PeerPing):
                    if not self.fault_injector.should_drop():
                        await self.send(PeerPong(n=msg.n))
                elif isinstance(msg, PeerPong):
                    self._handle_pong(msg.n)
                else:
                    res = self._on_message(self.peer_id, msg)
                    if asyncio.iscoroutine(res):
                        await res
        except Exception as e:
            log.debug("Peer connection %s closed or error: %s", self.peer_id, e)
        finally:
            await self.close()

    def _handle_pong(self, n: int) -> None:
        """Process incoming PeerPong, updating RTT and recovery status."""
        now = time.time()
        self._last_pong_time = now
        self._recent_pings[n] = True

        if t0 := self._ping_times.pop(n, None):
            sample_rtt = max(0.1, (now - t0) * 1000.0) + self.fault_injector.extra_latency_ms
            self.rtt_ms = 0.7 * self.rtt_ms + 0.3 * sample_rtt

        # If previously marked dead or offline, report recovery!
        if self._dead_link_triggered or not self.online:
            self._dead_link_triggered = False
            self.online = True
            log.info("Peer link %s recovered! Emitting link.update (online=True)", self.peer_id)
            asyncio.create_task(self.ctx.bus.publish(LinkUpdateEvent(link=self.quality())))

    async def _heartbeat_loop(self) -> None:
        """Periodic ping every 1.0s to measure RTT, loss, dead links, and probe throughput."""
        while not self._closed:
            try:
                await asyncio.sleep(1.0)
                if self._closed:
                    break

                now = time.time()
                time_since_pong = now - self._last_pong_time

                # Dead link detection: no response for ~3 seconds
                if time_since_pong >= 2.8 and not self._dead_link_triggered:
                    self._dead_link_triggered = True
                    self.online = False
                    self.loss_pct = 100.0
                    self.mbps = 0.0
                    log.warning(
                        "Dead link detected for %s (no pong in %.1fs). Emitting device.lost.",
                        self.peer_id,
                        time_since_pong,
                    )
                    await self.ctx.bus.publish(LinkUpdateEvent(link=self.quality()))
                    await self.ctx.bus.publish(DeviceLostEvent(deviceId=self.peer_id))

                    # Trigger disconnect callback to start reconnect / failover
                    res = self._on_disconnect(self.peer_id)
                    if asyncio.iscoroutine(res):
                        await res
                    continue

                # Calculate loss over recent sliding window (last 10 pings)
                if self._recent_pings:
                    total_pings = len(self._recent_pings)
                    missed = sum(1 for acked in self._recent_pings.values() if not acked)
                    computed_loss = (missed / total_pings) * 100.0
                    if self.fault_injector.drop_rate > 0:
                        computed_loss = max(computed_loss, self.fault_injector.drop_rate * 100.0)
                    self.loss_pct = 0.7 * self.loss_pct + 0.3 * computed_loss

                # Prune old ping history
                if len(self._recent_pings) > 12:
                    oldest_keys = sorted(self._recent_pings.keys())[: len(self._recent_pings) - 10]
                    for k in oldest_keys:
                        self._recent_pings.pop(k, None)

                if self._dead_link_triggered:
                    self.loss_pct = 100.0
                    self.online = False
                    self.mbps = 0.0

                # Send regular ping
                self._ping_seq += 1
                seq = self._ping_seq
                self._ping_times[seq] = now
                self._recent_pings[seq] = False
                await self.send(PeerPing(n=seq))

                # Rate-limited burst throughput probe (every ~8 seconds, only when not migrating)
                should_probe = (now - self._last_burst_probe_time >= 8.0) and (
                    now - self._last_migration_activity >= 5.0
                )
                if should_probe:
                    self._last_burst_probe_time = now
                    asyncio.create_task(self._run_burst_probe())

                # Periodically publish link quality update
                await self.ctx.bus.publish(LinkUpdateEvent(link=self.quality()))

            except asyncio.CancelledError:
                break
            except Exception as e:
                log.debug("Error in heartbeat loop for %s: %s", self.peer_id, e)
                break

    async def _run_burst_probe(self) -> None:
        """Short encrypted burst probe estimating available throughput without impacting migrations."""
        if self._closed or not self.online:
            return

        t_start = time.time()
        probe_pings = 3
        try:
            for _i in range(probe_pings):
                self._ping_seq += 1
                await self.send(PeerPing(n=self._ping_seq))
            elapsed = time.time() - t_start
            # 3 frames ~ 1.5 KB encrypted data
            measured_mbps = (1.5 * 8 / 1024) / max(0.005, elapsed)
            # Baseline weight based on physical media
            base_mbps = 1000.0 if self.link_type == "cable" else (
                150.0 if self.link_type == "wifi" else 5000.0
            )
            target_mbps = 0.8 * base_mbps + 0.2 * (measured_mbps * 50.0)
            self.mbps = self.fault_injector.apply_bandwidth_cap(target_mbps)
        except Exception:
            pass

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

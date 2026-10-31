"""In-memory PeerLink pair with fault injection for testing and cross-module reuse by P1."""

from __future__ import annotations

import asyncio
import random
import time
from typing import TYPE_CHECKING, Any

from contract.contract import (
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
    PeerPing,
    PeerPong,
    PeerStats,
)

if TYPE_CHECKING:
    from teleport.core import Context


def _record_peer_device(ctx: Context, dev: DeviceInfo) -> None:
    recorder: Any = getattr(ctx.devices, "record_peer_device", None)
    if callable(recorder):
        recorder(dev)


def _record_peer_stats(ctx: Context, stats: Any) -> None:
    recorder: Any = getattr(ctx.devices, "record_peer_stats", None)
    if callable(recorder):
        recorder(stats)


class InMemoryPeerLink(PeerLink):
    """In-memory peer link implementation supporting fault injection (delay, drop, cut)."""

    def __init__(self, ctx: Context, link_type: LinkType = "cable") -> None:
        self.ctx = ctx
        self.link_type = link_type
        self.counterpart: InMemoryPeerLink | None = None
        self._handlers: list[PeerMessageHandler] = []
        self._connected = False

        # Fault injection controls
        self.delay_ms: float = 0.0
        self.drop_rate: float = 0.0
        self.is_cut: bool = False
        self.pin: str = "123456"

    def attach_counterpart(self, peer: InMemoryPeerLink) -> None:
        self.counterpart = peer

    def cut(self) -> None:
        """Cut the communication channel."""
        self.is_cut = True
        self._connected = False
        peer_id = self.counterpart.ctx.device_id if self.counterpart else "unknown"
        asyncio.create_task(self.ctx.bus.publish(DeviceLostEvent(deviceId=peer_id)))
        dead_link = LinkQuality(
            peerId=peer_id,
            link=self.link_type,
            rttMs=999.0,
            mbps=0.0,
            lossPct=100.0,
            ts=time.time(),
        )
        asyncio.create_task(self.ctx.bus.publish(LinkUpdateEvent(link=dead_link)))

    def restore(self) -> None:
        """Restore cut communication channel."""
        self.is_cut = False
        self._connected = True
        if self.counterpart:
            peer_id = self.counterpart.ctx.device_id
            if quality := self.link_quality(peer_id):
                asyncio.create_task(self.ctx.bus.publish(LinkUpdateEvent(link=quality)))

    async def pair(self, addr: str, pin: str) -> DeviceInfo:
        if not self.counterpart:
            raise ConnectionError("No counterpart attached")
        if self.is_cut:
            raise ConnectionError("Link is cut")

        if pin != self.counterpart.pin:
            raise ValueError("Invalid PIN")

        peer_dev = self.counterpart.ctx.devices.local_info()
        local_dev = self.ctx.devices.local_info()

        # Both store each other in registry
        _record_peer_device(self.ctx, peer_dev)
        _record_peer_device(self.counterpart.ctx, local_dev)

        # Both emit device.paired
        await self.ctx.bus.publish(DevicePairedEvent(device=peer_dev))
        await self.counterpart.ctx.bus.publish(DevicePairedEvent(device=local_dev))

        self._connected = True
        self.counterpart._connected = True
        return peer_dev

    async def connect(self, device_id: str) -> None:
        if not self.counterpart or self.counterpart.ctx.device_id != device_id:
            raise ValueError(f"Unknown device {device_id}")
        if self.is_cut:
            raise ConnectionError("Link is cut")

        self._connected = True
        self.counterpart._connected = True

        # Exchange hello
        local = self.ctx.devices.local_info()
        await self.counterpart._receive(self.ctx.device_id, PeerHello(device=local))

    async def send(self, device_id: str, msg: PeerMessage) -> None:
        if not self.counterpart or self.counterpart.ctx.device_id != device_id:
            raise ConnectionError(f"No route to device {device_id}")
        if self.is_cut or self.counterpart.is_cut:
            raise ConnectionError("Link is cut")

        # Packet drop simulation
        if self.drop_rate > 0.0 and random.random() < self.drop_rate:
            return

        # Latency delay simulation
        if self.delay_ms > 0.0:
            await asyncio.sleep(self.delay_ms / 1000.0)

        await self.counterpart._receive(self.ctx.device_id, msg)

    async def _receive(self, from_device: str, msg: PeerMessage) -> None:
        if self.is_cut:
            return

        if isinstance(msg, PeerHello):
            _record_peer_device(self.ctx, msg.device)
        elif isinstance(msg, PeerStats):
            _record_peer_stats(self.ctx, msg.stats)
        elif isinstance(msg, PeerPing):
            await self.send(from_device, PeerPong(n=msg.n))
            return

        for handler in list(self._handlers):
            try:
                res = handler(from_device, msg)
                if asyncio.iscoroutine(res):
                    await res
            except Exception:
                pass

    def on_message(self, handler: PeerMessageHandler) -> None:
        self._handlers.append(handler)

    def link_quality(self, device_id: str) -> LinkQuality | None:
        if not self.counterpart or self.counterpart.ctx.device_id != device_id or self.is_cut:
            return None
        return LinkQuality(
            peerId=device_id,
            link=self.link_type,
            rttMs=max(1.0, self.delay_ms * 2),
            mbps=1000.0 if self.link_type == "cable" else 150.0,
            lossPct=self.drop_rate * 100.0,
            ts=time.time(),
        )

    def list_peers(self) -> list[DeviceInfo]:
        return [d for d in self.ctx.devices.list_devices() if d.id != self.ctx.device_id]

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        self.cut()


def create_in_memory_peer_links(
    ctx_a: Context,
    ctx_b: Context,
    link_type: LinkType = "cable",
) -> tuple[InMemoryPeerLink, InMemoryPeerLink]:
    """Helper creating a bidirectional in-memory peer link pair for testing."""
    link_a = InMemoryPeerLink(ctx_a, link_type=link_type)
    link_b = InMemoryPeerLink(ctx_b, link_type=link_type)
    link_a.attach_counterpart(link_b)
    link_b.attach_counterpart(link_a)
    return link_a, link_b

"""LAN discovery (core): agents announce themselves with a small UDP broadcast every 2 s, so the
dashboard can list nearby devices and pair with a click instead of typing an IP address.

The beacon only says "a Teleport agent called X listens on port P". Trust still comes from pairing
(the PIN shown on the other device's own dashboard), so a spoofed beacon cannot pair by itself.
Off when the agent is bound to loopback (nothing outside this machine could reach it anyway) or
with TELEPORT_DISCOVERY=0.
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import json
import logging
import os
import socket
import sys
import time
from typing import Any

import psutil

from .context import Context

log = logging.getLogger("teleport.discovery")

DISCOVERY_PORT = int(os.environ.get("TELEPORT_DISCOVERY_PORT", "8767"))
BEACON_EVERY_S = 2.0
FORGET_AFTER_S = 10.0
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


def broadcast_addresses() -> list[str]:
    """The directed broadcast address of every IPv4 interface (more reliable than 255.255.255.255,
    which Windows sends out of one interface only), plus the limited broadcast as a fallback."""
    out: set[str] = {"255.255.255.255"}
    for addrs in psutil.net_if_addrs().values():
        for a in addrs:
            if a.family != socket.AF_INET or not a.netmask or a.address.startswith("127."):
                continue
            with contextlib.suppress(ValueError):
                net = ipaddress.IPv4Network(f"{a.address}/{a.netmask}", strict=False)
                if net.prefixlen < 31:
                    out.add(str(net.broadcast_address))
    return sorted(out)


class _Protocol(asyncio.DatagramProtocol):
    def __init__(self, owner: Discovery) -> None:
        self.owner = owner

    def datagram_received(self, data: bytes, addr: tuple[str | Any, int]) -> None:
        self.owner.on_beacon(data, str(addr[0]))

    def error_received(self, exc: Exception) -> None:
        log.debug("discovery socket error: %s", exc)


class Discovery:
    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        off = os.environ.get("TELEPORT_DISCOVERY", "1") == "0"
        self.enabled = not off and ctx.settings.host not in LOOPBACK_HOSTS
        self._seen: dict[str, dict[str, Any]] = {}
        self._transport: asyncio.DatagramTransport | None = None
        self._task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------ API

    def nearby(self) -> list[dict[str, Any]]:
        """Devices heard in the last few seconds: {deviceId, name, os, addr, lastSeen, paired}."""
        now = time.time()
        known = {d.id for d in self.ctx.devices.list_devices()}
        out = []
        for device_id, info in sorted(self._seen.items(), key=lambda kv: kv[1]["name"]):
            if now - info["lastSeen"] <= FORGET_AFTER_S:
                out.append({**info, "deviceId": device_id, "paired": device_id in known})
        return out

    # ------------------------------------------------------------------ wire

    def _beacon(self) -> bytes:
        local = self.ctx.devices.local_info()
        body = {
            "t": "teleport.beacon",
            "v": 1,
            "deviceId": self.ctx.device_id,
            "name": local.name,
            "os": local.os,
            "port": self.ctx.settings.port,
        }
        return json.dumps(body).encode()

    def on_beacon(self, data: bytes, src_ip: str) -> None:
        try:
            msg = json.loads(data)
        except ValueError:
            return
        if not isinstance(msg, dict) or msg.get("t") != "teleport.beacon":
            return
        device_id, port = str(msg.get("deviceId", "")), msg.get("port")
        if not device_id or device_id == self.ctx.device_id or not isinstance(port, int):
            return
        self._seen[device_id] = {
            "name": str(msg.get("name", device_id))[:80],
            "os": str(msg.get("os", ""))[:20],
            "addr": f"{src_ip}:{port}",  # the address that actually reached us: pair over this one
            "lastSeen": time.time(),
        }

    async def _announce(self) -> None:
        while True:
            if self._transport is not None:
                payload = await asyncio.to_thread(self._beacon)
                for target in broadcast_addresses():
                    with contextlib.suppress(OSError):
                        self._transport.sendto(payload, (target, DISCOVERY_PORT))
            await asyncio.sleep(BEACON_EVERY_S)

    def _socket(self) -> socket.socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # several agents on one machine
        if hasattr(socket, "SO_REUSEPORT") and sys.platform != "win32":
            with contextlib.suppress(OSError):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(("", DISCOVERY_PORT))
        sock.setblocking(False)
        return sock

    async def startup(self) -> None:
        if not self.enabled:
            return
        try:
            loop = asyncio.get_running_loop()
            transport, _ = await loop.create_datagram_endpoint(lambda: _Protocol(self), sock=self._socket())
            self._transport = transport
        except OSError as e:
            log.warning("LAN discovery off (UDP %d unavailable: %s); pair by address", DISCOVERY_PORT, e)
            return
        self._task = asyncio.create_task(self._announce())
        log.info("LAN discovery on UDP %d", DISCOVERY_PORT)

    async def shutdown(self) -> None:
        if self._task:
            self._task.cancel()
        if self._transport:
            self._transport.close()

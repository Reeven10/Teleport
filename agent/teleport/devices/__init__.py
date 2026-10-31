"""Device service (P2). STUB from P1: replace freely, keep create_device_service and the Protocol.

Today it reports local info/stats from psutil (or the TELEPORT_SIM_PROFILE, labeled simulated)
and publishes stats.update every second. No peers are known.
"""

from __future__ import annotations

import asyncio
import contextlib
import platform
import shutil
import socket
import sys
import time
from typing import Any

import psutil

from contract.contract import Arch, DeviceInfo, OsName, Stats, StatsUpdateEvent

from .. import __version__
from ..core.context import Context


def _os() -> OsName:
    return {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")  # type: ignore[return-value]


def _arch() -> Arch:
    return "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x86_64"


class StubDeviceService:
    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self._overrides: dict[str, dict[str, Any]] = {}
        self._latest: Stats | None = None
        self._task: asyncio.Task[None] | None = None

    def local_info(self) -> DeviceInfo:
        info: dict[str, Any] = {
            "id": self.ctx.device_id,
            "name": socket.gethostname(),
            "os": _os(),
            "arch": _arch(),
            "cpuCores": psutil.cpu_count() or 1,
            "ramMb": psutil.virtual_memory().total // 2**20,
            "gpu": None,
            "diskFreeMb": shutil.disk_usage(self.ctx.settings.home).free // 2**20,
            "runtimes": {"python": platform.python_version()},
            "libs": [],
            "addrs": [{"addr": f"127.0.0.1:{self.ctx.settings.port}", "link": "loopback"}],
            "agentVersion": __version__,
        }
        if profile := self.ctx.sim_profile:
            info.update(profile.device, simulated=True)
        if self.ctx.settings.deviceName:
            info["name"] = self.ctx.settings.deviceName
        return DeviceInfo.model_validate(info)

    def list_devices(self) -> list[DeviceInfo]:
        return [self.local_info()]

    def latest_stats(self, device_id: str) -> Stats | None:
        return self._latest if device_id == self.ctx.device_id else None

    def set_override(self, device_id: str, partial_stats: dict[str, Any] | None) -> None:
        if partial_stats is None:
            self._overrides.pop(device_id, None)
        else:
            self._overrides.setdefault(device_id, {}).update(partial_stats)

    def _sample(self) -> Stats:
        vm = psutil.virtual_memory()
        bat = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
        stats: dict[str, Any] = {
            "deviceId": self.ctx.device_id,
            "ts": time.time(),
            "cpuPct": psutil.cpu_percent(),
            "memPct": vm.percent,
            "memFreeMb": vm.available // 2**20,
            "diskFreeMb": shutil.disk_usage(self.ctx.settings.home).free // 2**20,
            "battery": {"pct": bat.percent, "charging": bool(bat.power_plugged)} if bat else None,
            "online": True,
        }
        simulated = False
        if profile := self.ctx.sim_profile:
            stats.update(profile.stats)
            simulated = True
        if override := self._overrides.get(self.ctx.device_id):
            stats.update(override)
            simulated = True
        if simulated:
            stats["simulated"] = True
        return Stats.model_validate(stats)

    async def _loop(self) -> None:
        while True:
            self._latest = self._sample()
            await self.ctx.bus.publish(StatsUpdateEvent(stats=self._latest))
            await asyncio.sleep(1)

    async def startup(self) -> None:
        self._latest = self._sample()
        self._task = asyncio.create_task(self._loop())

    async def shutdown(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task


def create_device_service(ctx: Context) -> StubDeviceService:
    return StubDeviceService(ctx)

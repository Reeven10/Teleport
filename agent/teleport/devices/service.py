"""DeviceService implementation: capability probe, stats sampler, simulator, and registry."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import shutil
import time
from typing import TYPE_CHECKING, Any

import psutil

from contract.contract import Battery, DeviceInfo, DeviceService, Stats, StatsUpdateEvent

from .capabilities import probe_local_device
from .registry import DeviceRegistry
from .simulator import StatsSimulator, get_active_profile

if TYPE_CHECKING:
    from ..core.context import Context

log = logging.getLogger("teleport.devices")


class DeviceServiceImpl(DeviceService):
    """Production DeviceService satisfying contract/contract.py Protocol."""

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self.registry = DeviceRegistry(ctx.settings.home)
        self.simulator = StatsSimulator()
        self._latest_stats: dict[str, Stats] = {}
        self._cached_local_info: DeviceInfo | None = None
        self._task: asyncio.Task[None] | None = None

        # Eagerly evaluate and register local device info and initial stats
        local = self.local_info()
        self.registry.upsert(local, last_seen=time.time())
        self._latest_stats[self.ctx.device_id] = self._sample_sync()

    def local_info(self, force_refresh: bool = False) -> DeviceInfo:
        """Probe local device capabilities with simulation profile overrides applied if active."""
        if self._cached_local_info is not None and not force_refresh:
            return self._cached_local_info

        base_info = probe_local_device(self.ctx)
        info_dict = base_info.model_dump()

        profile = get_active_profile(self.ctx)
        if profile and "device" in profile:
            info_dict.update(profile["device"])
            info_dict["simulated"] = True

        if self.ctx.settings.deviceName:
            info_dict["name"] = self.ctx.settings.deviceName

        self._cached_local_info = DeviceInfo.model_validate(info_dict)
        return self._cached_local_info

    def list_devices(self) -> list[DeviceInfo]:
        """Return local device first, then every known peer (in-memory lookup)."""
        return self.registry.list_devices(local_id=self.ctx.device_id)

    def latest_stats(self, device_id: str) -> Stats | None:
        """Latest stats reported for device_id (local or peer)."""
        return self._latest_stats.get(device_id)

    def set_override(self, device_id: str, partial_stats: dict[str, Any] | None) -> None:
        """Dev simulator: merge partial Stats fields over real ones; None clears."""
        self.simulator.set_override(device_id, partial_stats)
        if device_id == self.ctx.device_id:
            # Recompute local stats immediately so changes reflect within < 100ms
            updated = self._sample_sync()
            self._latest_stats[self.ctx.device_id] = updated
            if self._task and not self._task.done():
                with contextlib.suppress(Exception):
                    asyncio.create_task(self.ctx.bus.publish(StatsUpdateEvent(stats=updated)))

    def record_peer_device(self, device: DeviceInfo) -> None:
        """Register or update a known peer device."""
        self.registry.upsert(device, last_seen=time.time())

    def record_peer_stats(self, stats: Stats) -> None:
        """Store the latest stats received from a peer device."""
        self._latest_stats[stats.deviceId] = stats
        if peer := self.registry.get(stats.deviceId):
            self.registry.upsert(peer, last_seen=stats.ts)

    def _sample_sync(self) -> Stats:
        """Synchronous sample using psutil (executed in worker thread to prevent event loop blocking)."""
        vm = psutil.virtual_memory()
        cpu_val = float(psutil.cpu_percent(interval=None))
        free_disk_mb = int(shutil.disk_usage(self.ctx.settings.home).free // (1024 * 1024))

        battery: Battery | None = None
        if hasattr(psutil, "sensors_battery"):
            try:
                bat = psutil.sensors_battery()
                if bat is not None and bat.percent is not None:
                    charging = bool(bat.power_plugged) if bat.power_plugged is not None else False
                    battery = Battery(pct=float(bat.percent), charging=charging)
            except Exception:
                battery = None

        stats_dict: dict[str, Any] = {
            "deviceId": self.ctx.device_id,
            "ts": time.time(),
            "cpuPct": cpu_val,
            "memPct": float(vm.percent),
            "memFreeMb": int(vm.available // (1024 * 1024)),
            "diskFreeMb": free_disk_mb,
            "battery": battery,
            "online": True,
        }

        simulated = False
        profile = get_active_profile(self.ctx)
        if profile and "stats" in profile:
            stats_dict.update(profile["stats"])
            simulated = True

        if override := self.simulator.get_override(self.ctx.device_id):
            stats_dict.update(override)
            simulated = True

        if simulated:
            stats_dict["simulated"] = True

        return Stats.model_validate(stats_dict)

    async def _sample_async(self) -> Stats:
        """Sample without blocking the asyncio event loop."""
        return await asyncio.to_thread(self._sample_sync)

    async def _loop(self) -> None:
        """Publish Stats on ctx.bus every 1 second."""
        while True:
            try:
                stats = await self._sample_async()
                self._latest_stats[self.ctx.device_id] = stats
                await self.ctx.bus.publish(StatsUpdateEvent(stats=stats))
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.warning("error in device stats sampler loop: %s", e)
            await asyncio.sleep(1)

    async def startup(self) -> None:
        """Service lifecycle startup."""
        initial = await self._sample_async()
        self._latest_stats[self.ctx.device_id] = initial
        self.registry.upsert(self.local_info(), last_seen=time.time())
        self._task = asyncio.create_task(self._loop())

    async def shutdown(self) -> None:
        """Service lifecycle shutdown."""
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

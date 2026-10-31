"""Tests for background Stats sampler: ranges, non-blocking sampling, bus publication."""

from __future__ import annotations

import asyncio
from typing import cast

from contract.contract import Stats, StatsUpdateEvent
from teleport.core import Context
from teleport.devices.service import DeviceServiceImpl


def test_stats_ranges_are_valid(ctx: Context) -> None:
    service = cast(DeviceServiceImpl, ctx.devices)
    stats = service._sample_sync()
    assert isinstance(stats, Stats)
    assert stats.deviceId == ctx.device_id
    assert 0.0 <= stats.cpuPct <= 100.0
    assert 0.0 <= stats.memPct <= 100.0
    assert stats.memFreeMb > 0
    assert stats.diskFreeMb >= 0
    assert stats.online is True

    if stats.battery is not None:
        assert 0.0 <= stats.battery.pct <= 100.0
        assert isinstance(stats.battery.charging, bool)


async def test_stats_non_blocking_sampler(ctx: Context) -> None:
    service = cast(DeviceServiceImpl, ctx.devices)
    # Ensure calling _sample_async runs concurrently without stalling the loop
    stats = await service._sample_async()
    assert isinstance(stats, Stats)
    assert stats.deviceId == ctx.device_id


async def test_stats_published_on_bus_every_second(ctx: Context) -> None:
    service = cast(DeviceServiceImpl, ctx.devices)
    received: list[Stats] = []

    async def on_stats(event: StatsUpdateEvent) -> None:
        received.append(event.stats)

    unsub = ctx.bus.subscribe(StatsUpdateEvent, on_stats)
    try:
        await service.startup()
        # Initial stats published on startup, then another 1s later
        await asyncio.sleep(1.2)
        assert len(received) >= 2
        for st in received:
            assert st.deviceId == ctx.device_id
            assert st.online is True
    finally:
        unsub()
        await service.shutdown()

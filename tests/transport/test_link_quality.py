"""Tests for link quality monitoring, fault injection, dead link detection, failover, and stale stats."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from contract.contract import (
    DeviceAddr,
    DeviceInfo,
    DeviceLostEvent,
    LinkQuality,
    LinkUpdateEvent,
    PeerPing,
    Stats,
)
from teleport.core import Settings, build_context, create_app
from teleport.devices.service import DeviceServiceImpl
from teleport.transport.service import PeerLinkService

from .in_memory_peer_link import create_in_memory_peer_links


@pytest.mark.asyncio
async def test_rtt_within_tolerance_on_loopback(tmp_path: Path) -> None:
    ctx_a = build_context(Settings(home=tmp_path / "a", port=8765, deviceName="Node A"))
    ctx_b = build_context(Settings(home=tmp_path / "b", port=8766, deviceName="Node B"))

    link_a, link_b = create_in_memory_peer_links(ctx_a, ctx_b, link_type="loopback")
    await link_a.pair("127.0.0.1:8766", pin="123456")

    # Exchange pings
    await link_a.send(ctx_b.device_id, PeerPing(n=1))
    await asyncio.sleep(0.05)

    quality = link_a.link_quality(ctx_b.device_id)
    assert quality is not None
    assert quality.link == "loopback"
    # Loopback RTT should be fast (< 20ms)
    assert 0.0 <= quality.rttMs < 20.0
    assert quality.lossPct == 0.0


@pytest.mark.asyncio
async def test_loss_detected_under_injected_drop(tmp_path: Path) -> None:
    ctx_a = build_context(Settings(home=tmp_path / "a", port=8765, deviceName="Node A"))
    ctx_b = build_context(Settings(home=tmp_path / "b", port=8766, deviceName="Node B"))

    link_a, link_b = create_in_memory_peer_links(ctx_a, ctx_b)
    await link_a.pair("127.0.0.1:8766", pin="123456")

    # Inject 40% packet drop and 25ms extra latency
    link_a.drop_rate = 0.4
    link_a.delay_ms = 25.0

    quality = link_a.link_quality(ctx_b.device_id)
    assert quality is not None
    assert quality.lossPct == 40.0
    assert quality.rttMs >= 50.0  # 25ms each direction


@pytest.mark.asyncio
async def test_dead_link_detected_within_time_limit_and_recovery_reported(tmp_path: Path) -> None:
    ctx_a = build_context(Settings(home=tmp_path / "a", port=8765, deviceName="Node A"))
    ctx_b = build_context(Settings(home=tmp_path / "b", port=8766, deviceName="Node B"))

    link_a, link_b = create_in_memory_peer_links(ctx_a, ctx_b)
    await link_a.pair("127.0.0.1:8766", pin="123456")

    lost_events: list[str] = []
    link_updates: list[LinkQuality] = []

    async def on_lost(ev: DeviceLostEvent) -> None:
        lost_events.append(ev.deviceId)

    async def on_link(ev: LinkUpdateEvent) -> None:
        link_updates.append(ev.link)

    ctx_a.bus.subscribe(DeviceLostEvent, on_lost)
    ctx_a.bus.subscribe(LinkUpdateEvent, on_link)

    # 1. Cut the link (pull network / inject drop)
    t_cut = time.time()
    link_a.cut()

    # Wait for dead link event: must happen within ~3.0s
    await asyncio.sleep(0.1)
    t_detected = time.time()

    assert len(lost_events) == 1
    assert lost_events[0] == ctx_b.device_id
    assert (t_detected - t_cut) < 3.0

    # Assert link update with dead link metrics was published
    assert len(link_updates) >= 1
    assert link_updates[-1].lossPct == 100.0

    # 2. Restore network link -> recovery must be published
    link_a.restore()
    await asyncio.sleep(0.05)

    assert len(link_updates) >= 2
    assert link_updates[-1].lossPct == 0.0


@pytest.mark.asyncio
async def test_stale_stats_flagged_after_5_seconds(tmp_path: Path) -> None:
    ctx = build_context(Settings(home=tmp_path / "node", port=8765))
    dev_service = cast(DeviceServiceImpl, ctx.devices)

    peer_id = "dev-peer-stats-test"

    # Fresh stats
    fresh_stats = Stats(
        deviceId=peer_id,
        ts=time.time(),
        cpuPct=20.0,
        memPct=45.0,
        memFreeMb=4096,
        diskFreeMb=50000,
        battery=None,
        online=True,
    )
    dev_service.record_peer_stats(fresh_stats)

    res_fresh = dev_service.latest_stats(peer_id)
    assert res_fresh is not None
    assert res_fresh.online is True

    # Stale stats: ts older than 5 seconds ago
    stale_stats = Stats(
        deviceId=peer_id,
        ts=time.time() - 6.0,
        cpuPct=99.0,
        memPct=90.0,
        memFreeMb=512,
        diskFreeMb=1000,
        battery=None,
        online=True,
    )
    dev_service.record_peer_stats(stale_stats)

    res_stale = dev_service.latest_stats(peer_id)
    assert res_stale is not None
    assert res_stale.online is False


@pytest.mark.asyncio
async def test_failover_cable_to_wifi(tmp_path: Path) -> None:
    ctx_a = build_context(Settings(home=tmp_path / "a", port=8795, deviceName="Node A"))
    service_a = cast(PeerLinkService, ctx_a.peers)
    service_a.set_forced_link(None)

    # Device B with both cable and wifi addresses
    peer_id = "dev-b-multi"
    multi_addrs = [
        DeviceAddr(addr="127.0.0.1:9991", link="cable"),  # dead cable address
        DeviceAddr(addr="127.0.0.1:9992", link="wifi"),   # working wifi address
    ]
    dev_b = DeviceInfo(
        id=peer_id,
        name="Node B Multi",
        os="linux",
        arch="x86_64",
        cpuCores=4,
        ramMb=8192,
        gpu=None,
        diskFreeMb=50000,
        runtimes={},
        libs=[],
        addrs=multi_addrs,
        agentVersion="0.1.0",
    )
    cast(Any, ctx_a.devices).record_peer_device(dev_b)

    # Preference without forced link selects candidates sorted by cable first, then wifi
    candidates = service_a._get_sorted_candidate_addrs(multi_addrs)
    assert len(candidates) == 2
    assert candidates[0].link == "cable"
    assert candidates[1].link == "wifi"

    # Forcing wifi link selects only wifi
    service_a.set_forced_link("wifi")
    forced_candidates = service_a._get_sorted_candidate_addrs(multi_addrs)
    assert len(forced_candidates) == 1
    assert forced_candidates[0].link == "wifi"

    # Clear forced link
    service_a.set_forced_link(None)
    assert service_a._forced_link is None


def test_fault_injector_rest_endpoints(tmp_path: Path) -> None:
    settings = Settings(home=tmp_path / "node", port=8765)
    app = create_app(settings)

    with TestClient(app) as client:
        # 1. Apply fault injection via POST /api/dev/fault-inject
        res = client.post(
            "/api/dev/fault-inject",
            json={
                "latencyMs": 45.0,
                "dropRate": 0.15,
                "bandwidthCapMbps": 25.0,
            },
        )
        assert res.status_code == 200
        assert res.json()["ok"] is True

        # 2. Force link type via POST /api/transport/force-link
        res_force = client.post("/api/transport/force-link", json={"link": "cable"})
        assert res_force.status_code == 200
        assert res_force.json()["forcedLink"] == "cable"

        # 3. Query link qualities via GET /api/transport/link-quality
        res_lq = client.get("/api/transport/link-quality")
        assert res_lq.status_code == 200
        assert isinstance(res_lq.json(), list)

        # 4. Clear faults via POST /api/dev/fault-inject/clear
        res_clear = client.post("/api/dev/fault-inject/clear", json={})
        assert res_clear.status_code == 200
        assert res_clear.json()["ok"] is True

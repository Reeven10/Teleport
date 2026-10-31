"""Tests for short-code PIN pairing and rate-limiting."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from contract.contract import DeviceInfo, DevicePairedEvent
from teleport.core import Context, Settings, build_context, create_app
from teleport.transport.service import PeerLinkService


def test_pairing_manager_rate_limit(ctx: Context) -> None:
    service = cast(PeerLinkService, ctx.peers)
    correct_pin = service.pairing.pin

    # Attempt 1: wrong PIN
    ok, err = service.pairing.verify_pin("000000")
    assert not ok
    assert "2 attempts remaining" in (err or "")

    # Attempt 2: wrong PIN
    ok, err = service.pairing.verify_pin("000000")
    assert not ok
    assert "1 attempts remaining" in (err or "")

    # Attempt 3: triggers rate limit lockout
    ok, err = service.pairing.verify_pin("000000")
    assert not ok
    assert "Rate limited" in (err or "")

    # Further attempt with CORRECT PIN while locked out is still rejected
    ok, err = service.pairing.verify_pin(correct_pin)
    assert not ok
    assert "Rate limited" in (err or "")

    # Rotating PIN resets lockout
    service.pairing.generate_pin()
    new_pin = service.pairing.pin
    ok, err = service.pairing.verify_pin(new_pin)
    assert ok
    assert err is None


def test_pairing_api_endpoints(tmp_path: Path) -> None:
    settings_b = Settings(home=tmp_path / "b", port=8766, deviceName="Device B")
    app_b = create_app(settings_b)

    with TestClient(app_b) as client_b:
        # 1. Device B shows 6-digit PIN under GET /api/pair
        resp = client_b.get("/api/pair")
        assert resp.status_code == 200
        data = resp.json()
        assert "pin" in data and len(data["pin"]) == 6
        assert data["pin"].isdigit()
        pin_b = data["pin"]

        # 2. Verify with wrong PIN via POST /api/pair/verify -> 401
        dummy_dev = {
            "id": "dev-a",
            "name": "Device A",
            "os": "linux",
            "arch": "x86_64",
            "cpuCores": 4,
            "ramMb": 8192,
            "gpu": None,
            "diskFreeMb": 50000,
            "runtimes": {"python": "3.11.9"},
            "libs": [],
            "addrs": [{"addr": "127.0.0.1:8765", "link": "loopback"}],
            "agentVersion": "0.1.0",
        }
        res_fail = client_b.post("/api/pair/verify", json={"pin": "999999", "device": dummy_dev})
        assert res_fail.status_code == 401

        # 3. Verify with right PIN -> 200, returns Device B info
        res_ok = client_b.post("/api/pair/verify", json={"pin": pin_b, "device": dummy_dev})
        assert res_ok.status_code == 200
        body = res_ok.json()
        assert body.get("ok") is True
        assert body["device"]["name"] == "Device B"


async def test_full_bidirectional_pairing(tmp_path: Path) -> None:
    ctx_a = build_context(Settings(home=tmp_path / "a", port=8765, deviceName="Device A"))
    ctx_b = build_context(Settings(home=tmp_path / "b", port=8766, deviceName="Device B"))

    service_b = cast(PeerLinkService, ctx_b.peers)

    pin_b = service_b.pairing.pin
    paired_events_a: list[DeviceInfo] = []
    paired_events_b: list[DeviceInfo] = []

    async def on_paired_a(ev: DevicePairedEvent) -> None:
        paired_events_a.append(ev.device)

    async def on_paired_b(ev: DevicePairedEvent) -> None:
        paired_events_b.append(ev.device)

    ctx_a.bus.subscribe(DevicePairedEvent, on_paired_a)
    ctx_b.bus.subscribe(DevicePairedEvent, on_paired_b)

    # Directly verify and pair
    local_a = ctx_a.devices.local_info()
    is_valid, _ = service_b.pairing.verify_pin(pin_b)
    assert is_valid

    # Device B records Device A
    cast(Any, ctx_b.devices).record_peer_device(local_a)
    await ctx_b.bus.publish(DevicePairedEvent(device=local_a))

    # Device A records Device B
    local_b = ctx_b.devices.local_info()
    cast(Any, ctx_a.devices).record_peer_device(local_b)
    await ctx_a.bus.publish(DevicePairedEvent(device=local_b))

    # Both registries contain the peer
    assert any(d.id == ctx_b.device_id for d in ctx_a.devices.list_devices())
    assert any(d.id == ctx_a.device_id for d in ctx_b.devices.list_devices())

    # Both emitted device.paired on bus
    assert len(paired_events_a) == 1
    assert paired_events_a[0].id == ctx_b.device_id
    assert len(paired_events_b) == 1
    assert paired_events_b[0].id == ctx_a.device_id


@pytest.mark.asyncio
async def test_live_two_agents_pair_and_see_device_info(tmp_path: Path) -> None:
    import httpx
    import uvicorn

    port_a = 8785
    port_b = 8786

    app_a = create_app(
        Settings(home=tmp_path / "a", port=port_a, simProfile="default", deviceName="Device A")
    )
    app_b = create_app(
        Settings(home=tmp_path / "b", port=port_b, simProfile="arm64-lowspec", deviceName="Device B")
    )

    config_a = uvicorn.Config(app_a, host="127.0.0.1", port=port_a, log_level="error")
    config_b = uvicorn.Config(app_b, host="127.0.0.1", port=port_b, log_level="error")

    server_a = uvicorn.Server(config_a)
    server_b = uvicorn.Server(config_b)

    task_a = asyncio.create_task(server_a.serve())
    task_b = asyncio.create_task(server_b.serve())

    try:
        # Wait for both servers to be ready
        for _ in range(30):
            if server_a.started and server_b.started:
                break
            await asyncio.sleep(0.1)

        async with httpx.AsyncClient(timeout=5.0) as client:
            # 1. Device B shows 6-digit PIN under GET /api/pair
            resp_b = await client.get(f"http://127.0.0.1:{port_b}/api/pair")
            assert resp_b.status_code == 200
            pin_b = resp_b.json()["pin"]
            assert len(pin_b) == 6

            # 2. Device A calls POST /api/pair with Device B's address and PIN
            pair_resp = await client.post(
                f"http://127.0.0.1:{port_a}/api/pair",
                json={"addr": f"127.0.0.1:{port_b}", "pin": pin_b},
            )
            assert pair_resp.status_code == 200
            paired_dev = pair_resp.json()
            assert paired_dev["name"] == "Device B"
            assert paired_dev["arch"] == "arm64"

            # 3. Check Device A's known devices: Device A first, then Device B
            devs_a_resp = await client.get(f"http://127.0.0.1:{port_a}/api/devices")
            assert devs_a_resp.status_code == 200
            devs_a = devs_a_resp.json()
            assert len(devs_a) == 2
            assert devs_a[0]["name"] == "Device A"
            assert devs_a[1]["name"] == "Device B"

            # 4. Check Device B's known devices: Device B first, then Device A
            devs_b_resp = await client.get(f"http://127.0.0.1:{port_b}/api/devices")
            assert devs_b_resp.status_code == 200
            devs_b = devs_b_resp.json()
            assert len(devs_b) == 2
            assert devs_b[0]["name"] == "Device B"
            assert devs_b[1]["name"] == "Device A"
    finally:
        server_a.should_exit = True
        server_b.should_exit = True
        await asyncio.gather(task_a, task_b, return_exceptions=True)

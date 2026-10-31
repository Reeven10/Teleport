"""Tests for stats simulator override, simulated labeling, and profile selection."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from contract.contract import BusEventAdapter, StatsUpdateEvent
from teleport.core import Context, Settings, build_context


def test_override_merges_and_marked_simulated(ctx: Context) -> None:
    # Initially not simulated
    stats = ctx.devices.latest_stats(ctx.device_id)
    if stats:
        assert stats.simulated is not True

    # Apply override for battery and CPU
    ctx.devices.set_override(
        ctx.device_id,
        {"battery": {"pct": 8.0, "charging": False}, "cpuPct": 94.5},
    )

    overridden = ctx.devices.latest_stats(ctx.device_id)
    assert overridden is not None
    assert overridden.battery is not None
    assert overridden.battery.pct == 8.0
    assert overridden.battery.charging is False
    assert overridden.cpuPct == 94.5
    assert overridden.simulated is True

    # Clear override
    ctx.devices.set_override(ctx.device_id, None)
    cleared = ctx.devices.latest_stats(ctx.device_id)
    assert cleared is not None
    assert cleared.simulated is not True


def test_override_changes_published_battery_within_one_second(client: TestClient) -> None:
    # Connect to WebSocket event stream
    with client.websocket_connect("/ws/events") as ws:
        # Read initial stats event
        ev1 = BusEventAdapter.validate_json(ws.receive_text())
        assert isinstance(ev1, StatsUpdateEvent)

        # POST override to /api/dev/stats-override
        resp = client.post(
            "/api/dev/stats-override",
            json={
                "deviceId": ev1.stats.deviceId,
                "stats": {"battery": {"pct": 7.0, "charging": False}},
            },
        )
        assert resp.status_code == 200

        # Receive next event on WebSocket; must reflect new battery within 1s
        ev2 = BusEventAdapter.validate_json(ws.receive_text())
        assert isinstance(ev2, StatsUpdateEvent)
        assert ev2.stats.battery is not None
        assert ev2.stats.battery.pct == 7.0
        assert ev2.stats.battery.charging is False
        assert ev2.stats.simulated is True


def test_profile_selection_default_and_arm64(tmp_path: Path) -> None:
    # Default profile (used by dev:two Device A)
    ctx_def = build_context(Settings(home=tmp_path / "def", simProfile="default"))
    info_def = ctx_def.devices.local_info()
    assert info_def.arch == "x86_64"
    assert info_def.simulated is True
    stats_def = ctx_def.devices.latest_stats(ctx_def.device_id)
    assert stats_def is not None
    assert stats_def.simulated is True
    assert stats_def.battery is not None
    assert stats_def.battery.pct == 85.0

    # arm64-lowspec profile (used by dev:two Device B)
    ctx_arm = build_context(Settings(home=tmp_path / "arm", simProfile="arm64-lowspec"))
    info_arm = ctx_arm.devices.local_info()
    assert info_arm.arch == "arm64"
    assert info_arm.cpuCores == 4
    assert info_arm.simulated is True
    stats_arm = ctx_arm.devices.latest_stats(ctx_arm.device_id)
    assert stats_arm is not None
    assert stats_arm.simulated is True
    assert stats_arm.battery is None  # Board with no battery (AC)


def test_dev_two_profiles_match_requirements(tmp_path: Path) -> None:
    # Device A on port 8765 with default profile
    ctx_a = build_context(
        Settings(home=tmp_path / "a", port=8765, simProfile="default", deviceName="Device A")
    )
    info_a = ctx_a.devices.local_info()
    assert info_a.name == "Device A"
    assert info_a.arch == "x86_64"
    assert info_a.cpuCores == 8
    assert info_a.ramMb == 16384
    assert info_a.simulated is True

    # Device B on port 8766 with arm64-lowspec profile
    ctx_b = build_context(
        Settings(home=tmp_path / "b", port=8766, simProfile="arm64-lowspec", deviceName="Device B")
    )
    info_b = ctx_b.devices.local_info()
    assert info_b.name == "Device B"
    assert info_b.arch == "arm64"
    assert info_b.cpuCores == 4
    assert info_b.ramMb == 2048
    assert info_b.simulated is True

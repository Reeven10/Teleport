"""Tests for DeviceInfo capability probe: hardware, runtimes, libs, addrs, and device ID."""

from __future__ import annotations

from pathlib import Path

from contract.contract import DeviceInfo
from teleport.core import Context, Settings, build_context
from teleport.devices.capabilities import (
    get_installed_libraries,
    get_network_addresses,
    get_runtimes,
    probe_local_device,
)


def test_probe_returns_all_fields(ctx: Context) -> None:
    info = probe_local_device(ctx)
    assert isinstance(info, DeviceInfo)
    assert info.id == ctx.device_id
    assert info.name is not None and len(info.name) > 0
    assert info.os in ("windows", "linux", "macos")
    assert info.arch in ("x86_64", "arm64")
    assert info.cpuCores >= 1
    assert info.ramMb > 0
    assert info.diskFreeMb >= 0
    assert isinstance(info.runtimes, dict)
    assert "python" in info.runtimes
    assert isinstance(info.libs, list)
    assert isinstance(info.addrs, list)
    assert len(info.addrs) >= 1
    # Loopback address must be present
    assert any(a.link == "loopback" for a in info.addrs)
    assert info.agentVersion == "0.1.0"


def test_stable_device_id_persists(tmp_path: Path) -> None:
    home1 = tmp_path / "home1"
    ctx1 = build_context(Settings(home=home1, port=8765))
    id1 = ctx1.device_id
    assert (home1 / "device.json").exists()

    # Re-reading same home gives exact same device_id
    ctx2 = build_context(Settings(home=home1, port=8765))
    assert ctx2.device_id == id1


def test_runtimes_and_libraries(ctx: Context) -> None:
    runtimes = get_runtimes()
    assert "python" in runtimes
    assert len(runtimes["python"]) > 0

    libs = get_installed_libraries()
    assert isinstance(libs, list)
    # Check cache idempotency
    assert libs is get_installed_libraries()


def test_network_addrs_with_link_guess() -> None:
    addrs = get_network_addresses(8765)
    assert len(addrs) > 0
    links = {a.link for a in addrs}
    for link in links:
        assert link in ("cable", "wifi", "loopback")
    assert "127.0.0.1:8765" in {a.addr for a in addrs}

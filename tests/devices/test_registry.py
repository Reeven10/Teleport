"""Tests for DeviceRegistry and DeviceService integration."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from contract.contract import DeviceAddr, DeviceInfo
from teleport.devices.registry import DeviceRegistry


def test_registry_persists_and_reloads(tmp_path: Path) -> None:
    reg1 = DeviceRegistry(tmp_path)
    peer_info = DeviceInfo(
        id="dev-peer-1",
        name="Peer Laptop",
        os="linux",
        arch="x86_64",
        cpuCores=8,
        ramMb=16384,
        gpu=None,
        diskFreeMb=50000,
        runtimes={"python": "3.11.9"},
        libs=["sqlite3"],
        addrs=[DeviceAddr(addr="192.168.1.50:8765", link="wifi")],
        agentVersion="0.1.0",
    )
    reg1.upsert(peer_info)

    # Verify JSON file on disk
    assert (tmp_path / "devices.json").exists()
    content = json.loads((tmp_path / "devices.json").read_text("utf-8"))
    assert "dev-peer-1" in content["devices"]

    # Reload in a separate registry instance
    reg2 = DeviceRegistry(tmp_path)
    loaded = reg2.get("dev-peer-1")
    assert loaded is not None
    assert loaded.id == "dev-peer-1"
    assert loaded.name == "Peer Laptop"
    assert reg2.get_last_seen("dev-peer-1") is not None


def test_local_device_first_then_peers(tmp_path: Path) -> None:
    reg = DeviceRegistry(tmp_path)
    local_dev = DeviceInfo(
        id="dev-local",
        name="Local Machine",
        os="windows",
        arch="x86_64",
        cpuCores=16,
        ramMb=32768,
        gpu="RTX 4090",
        diskFreeMb=100000,
        runtimes={"python": "3.11.9"},
        libs=[],
        addrs=[DeviceAddr(addr="127.0.0.1:8765", link="loopback")],
        agentVersion="0.1.0",
    )
    peer1 = local_dev.model_copy(update={"id": "dev-peer-1", "name": "Peer 1"})
    peer2 = local_dev.model_copy(update={"id": "dev-peer-2", "name": "Peer 2"})

    reg.upsert(peer1, last_seen=100.0)
    reg.upsert(local_dev, last_seen=200.0)
    reg.upsert(peer2, last_seen=300.0)

    devices = reg.list_devices(local_id="dev-local")
    # Local device must ALWAYS be first
    assert devices[0].id == "dev-local"
    # Followed by peers sorted by lastSeen descending
    assert [d.id for d in devices] == ["dev-local", "dev-peer-2", "dev-peer-1"]


def test_device_service_protocol_and_rest(client: TestClient) -> None:
    # Verify GET /api/devices returns array containing local device
    resp_devices = client.get("/api/devices")
    assert resp_devices.status_code == 200
    devices = resp_devices.json()
    assert len(devices) >= 1
    assert "id" in devices[0]
    assert "cpuCores" in devices[0]

    # Verify GET /api/stats returns array of latest stats
    resp_stats = client.get("/api/stats")
    assert resp_stats.status_code == 200
    stats = resp_stats.json()
    assert len(stats) >= 1
    assert "cpuPct" in stats[0]
    assert "memPct" in stats[0]
    assert "online" in stats[0]

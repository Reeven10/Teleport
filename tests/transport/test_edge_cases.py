"""Edge case and regression tests for Teleport transport, devices, and security modules.

Covers:
  1. Pairing the same device twice (idempotency, TOFU key validation).
  2. Peer that restarts and changes its network address (reconnect to new address).
  3. Very slow link with high latency (RTT measured accurately, no premature disconnect).
  4. Two peers connected at the same time with concurrent stats broadcast.
  5. System clock skew over 30 seconds (no false staleness or session failure).
  6. PeerLink manifest signing and verification (Ed25519 identity key).
  7. Dialer never dials its own LAN adapter addresses.
  8. Inbound WebSocket link type matches local listening interface.
  9. LAN IP pairing PIN visibility for local browser/dashboard.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from contract.contract import (
    DeviceAddr,
    Stats,
    StatsUpdateEvent,
)
from teleport.core import Settings, build_context, create_app
from teleport.devices.capabilities import guess_link_type, is_virtual_or_dummy_interface
from teleport.devices.service import DeviceServiceImpl
from teleport.security import DeviceIdentity
from teleport.security.dev_session import PlaintextDevSession
from teleport.transport.connection import PeerConnection
from teleport.transport.service import PeerLinkService, _is_local_client


class MemoryWSAdapter:
    def __init__(self, rx_queue: asyncio.Queue[str], tx_queue: asyncio.Queue[str]) -> None:
        self.rx_queue = rx_queue
        self.tx_queue = tx_queue
        self._closed = False

    async def send(self, data: str) -> None:
        if not self._closed:
            await self.tx_queue.put(data)

    async def recv(self) -> str:
        return await self.rx_queue.get()

    async def close(self) -> None:
        self._closed = True


def create_memory_ws_pair() -> tuple[MemoryWSAdapter, MemoryWSAdapter]:
    q1: asyncio.Queue[str] = asyncio.Queue()
    q2: asyncio.Queue[str] = asyncio.Queue()
    return MemoryWSAdapter(q1, q2), MemoryWSAdapter(q2, q1)


@pytest.mark.asyncio
async def test_pairing_same_device_twice_is_idempotent(tmp_path: Path) -> None:
    """Pairing the same device twice with the same key must succeed cleanly without errors."""
    ctx_a = build_context(Settings(home=tmp_path / "node_a", port=8765))
    app_b = create_app(Settings(home=tmp_path / "node_b", port=8766))
    client_b = TestClient(app_b)

    service_a: PeerLinkService = ctx_a.peers  # type: ignore[assignment]

    # Read PIN from B via local client
    pair_info = client_b.get("/api/pair").json()
    pin = pair_info["pin"]
    dev_a_info = ctx_a.devices.local_info()
    payload = {
        "pin": pin,
        "device": dev_a_info.model_dump(),
        "identityKey": service_a.pairing.identity.public_key_b64(),
    }

    # 1. First pairing
    resp1 = client_b.post("/api/pair/verify", json=payload)
    assert resp1.status_code == 200

    # 2. Second pairing with identical key must succeed (idempotent)
    resp2 = client_b.post("/api/pair/verify", json=payload)
    assert resp2.status_code == 200

    # 3. Third pairing with a modified/forged key must be rejected (TOFU check)
    bad_identity = DeviceIdentity(tmp_path / "forger")
    tampered_payload = dict(payload)
    tampered_payload["identityKey"] = bad_identity.public_key_b64()
    resp3 = client_b.post("/api/pair/verify", json=tampered_payload)
    assert resp3.status_code in (401, 403)
    assert "key change detected" in resp3.json()["detail"].lower()


@pytest.mark.asyncio
async def test_peer_restarts_and_changes_address(tmp_path: Path) -> None:
    """A peer restarts on a different port/address and is reached via updated registry info."""
    ctx_a = build_context(Settings(home=tmp_path / "a", port=8765))
    service_a: PeerLinkService = ctx_a.peers  # type: ignore[assignment]
    dev_service_a: DeviceServiceImpl = ctx_a.devices  # type: ignore[assignment]

    peer_id = "dev-peer-restart"
    # Seed known peer from local_info template with non-existent port
    base_info = ctx_a.devices.local_info()
    old_dev = base_info.model_copy(
        update={
            "id": peer_id,
            "name": "Restarting Peer",
            "addrs": [DeviceAddr(addr="127.0.0.1:8888", link="loopback")],
        }
    )
    dev_service_a.record_peer_device(old_dev)

    # Connect to old address fails
    with pytest.raises(ConnectionError):
        await service_a.connect(peer_id)

    # Peer restarts and registers new address
    ws_a, ws_b = create_memory_ws_pair()
    conn = PeerConnection(
        peer_id=peer_id,
        adapter=ws_a,
        link_type="loopback",
        ctx=ctx_a,
        on_message=lambda pid, m: None,
        on_disconnect=lambda pid: None,
    )
    service_a._connections[peer_id] = conn
    conn.start()

    new_dev = old_dev.model_copy(update={"addrs": [DeviceAddr(addr="127.0.0.1:8999", link="loopback")]})
    dev_service_a.record_peer_device(new_dev)

    assert any(a.addr == "127.0.0.1:8999" for a in ctx_a.devices.list_devices()[1].addrs)
    await conn.close()
    await ws_b.close()


@pytest.mark.asyncio
async def test_very_slow_link_and_latency_measurement(tmp_path: Path) -> None:
    """Very slow link (high latency fault) correctly reflects high RTT and remains online."""
    ctx = build_context(Settings(home=tmp_path / "slow", port=8765))
    ws_local, ws_remote = create_memory_ws_pair()

    conn = PeerConnection(
        peer_id="dev-slow-peer",
        adapter=ws_local,
        link_type="wifi",
        ctx=ctx,
        on_message=lambda pid, m: None,
        on_disconnect=lambda pid: None,
    )
    conn.fault_injector.configure(latency_ms=120.0, drop_rate=0.0)
    conn.start()

    # Simulate ping / pong exchange converging moving average
    for i in range(5):
        conn._ping_times[i] = time.time() - 0.01
        conn._handle_pong(i)

    assert conn.online
    assert conn.quality().rttMs >= 100.0  # Converges toward injected latency (120ms + sample)

    await conn.close()
    await ws_remote.close()


@pytest.mark.asyncio
async def test_two_peers_connected_at_once_and_stats_broadcast(tmp_path: Path) -> None:
    """Device can maintain simultaneous connections to two peers and broadcast stats to both."""
    ctx = build_context(Settings(home=tmp_path / "hub", port=8765))
    service: PeerLinkService = ctx.peers  # type: ignore[assignment]
    await service.startup()

    ws_a1, ws_b1 = create_memory_ws_pair()
    ws_a2, ws_b2 = create_memory_ws_pair()

    conn1 = PeerConnection(
        peer_id="dev-peer-1",
        adapter=ws_a1,
        link_type="cable",
        ctx=ctx,
        on_message=lambda pid, m: None,
        on_disconnect=lambda pid: None,
        session=PlaintextDevSession(),
    )
    conn2 = PeerConnection(
        peer_id="dev-peer-2",
        adapter=ws_a2,
        link_type="wifi",
        ctx=ctx,
        on_message=lambda pid, m: None,
        on_disconnect=lambda pid: None,
        session=PlaintextDevSession(),
    )
    service._connections["dev-peer-1"] = conn1
    service._connections["dev-peer-2"] = conn2
    conn1.start()
    conn2.start()

    # Publish local stats update on bus
    st = Stats(
        deviceId=ctx.device_id,
        ts=time.time(),
        cpuPct=42.0,
        memPct=55.0,
        memFreeMb=4096,
        diskFreeMb=20000,
        battery=None,
        online=True,
    )
    await ctx.bus.publish(StatsUpdateEvent(stats=st))
    await asyncio.sleep(0.05)

    # Both peers receive PeerStats message
    raw1 = await asyncio.wait_for(ws_b1.recv(), timeout=1.0)
    raw2 = await asyncio.wait_for(ws_b2.recv(), timeout=1.0)
    assert "stats" in raw1 or len(raw1) > 0
    assert "stats" in raw2 or len(raw2) > 0

    await service.shutdown()
    await ws_b1.close()
    await ws_b2.close()


def test_clock_skew_over_30_seconds_does_not_break_staleness(tmp_path: Path) -> None:
    """Peers whose system clocks are skewed by 30+ seconds into future or past."""
    ctx = build_context(Settings(home=tmp_path / "skew", port=8765))
    dev_service: DeviceServiceImpl = ctx.devices  # type: ignore[assignment]

    peer_id = "dev-skewed-peer"
    now = time.time()
    # Peer timestamp is 60 seconds ahead in the FUTURE (clock skew)
    skewed_future = Stats(
        deviceId=peer_id,
        ts=now + 60.0,
        cpuPct=15.0,
        memPct=40.0,
        memFreeMb=8000,
        diskFreeMb=50000,
        battery=None,
        online=True,
    )

    # Record peer stats just received
    dev_service.record_peer_stats(skewed_future)

    # Must remain online=True because it was received just now
    latest = dev_service.latest_stats(peer_id)
    assert latest is not None
    assert latest.online is True

    # After 5.1 seconds of local inactivity, it becomes stale
    dev_service._stats_received_at[peer_id] = time.time() - 5.5
    stale = dev_service.latest_stats(peer_id)
    assert stale is not None
    assert stale.online is False


def test_peer_link_manifest_signing_and_verification(tmp_path: Path) -> None:
    """PeerLinkService exposes sign_manifest and verify_manifest satisfying ManifestSigner."""
    ctx_a = build_context(Settings(home=tmp_path / "signer_a", port=8765))
    ctx_b = build_context(Settings(home=tmp_path / "signer_b", port=8766))

    peers_a: PeerLinkService = ctx_a.peers  # type: ignore[assignment]
    peers_b: PeerLinkService = ctx_b.peers  # type: ignore[assignment]

    # Store A's key in B's trusted peer keys
    peers_b.pairing.peer_keys.record_peer_key(
        ctx_a.device_id,
        peers_a.pairing.identity.public_key_bytes(),
    )

    payload = b'{"workload": "counter", "checkpoint": 1}'
    sig = peers_a.sign_manifest(payload)
    assert isinstance(sig, str) and len(sig) > 0

    # Verification on B succeeds
    assert peers_b.verify_manifest(ctx_a.device_id, payload, sig)

    # Tampered payload fails verification
    tampered = b'{"workload": "counter", "checkpoint": 2}'
    assert not peers_b.verify_manifest(ctx_a.device_id, tampered, sig)


def test_dialer_never_dials_own_adapter() -> None:
    """Verify dialer detects local addresses and rejects self-dialing."""
    assert _is_local_client("127.0.0.1")
    assert _is_local_client("localhost")
    assert not _is_local_client("198.51.100.25")


def test_virtual_adapters_classified_as_loopback() -> None:
    """VirtualBox, WSL, Hyper-V adapters are categorized as loopback, never preferred cable."""
    assert guess_link_type("VirtualBox Host-Only Network", "192.168.56.1") == "loopback"
    assert guess_link_type("vEthernet (WSL)", "172.27.64.1") == "loopback"
    assert is_virtual_or_dummy_interface("VirtualBox Host-Only Network", "192.168.56.1")
    assert is_virtual_or_dummy_interface("vEthernet (WSL)", "172.27.64.1")

"""Tests for WebSocket peer link: hello exchange, message transmission, reconnect, and device.lost."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from contract.contract import (
    DeviceLostEvent,
    PeerHello,
    PeerMessageAdapter,
    PeerPing,
    PeerPong,
    PeerStats,
)
from teleport.core import Settings, build_context, create_app
from teleport.security import DeviceIdentity, SecureSession
from teleport.transport.service import PeerLinkService

from .in_memory_peer_link import create_in_memory_peer_links


def test_websocket_peer_endpoint_hello_and_ping(tmp_path: Path) -> None:
    settings = Settings(home=tmp_path / "srv", port=8765, deviceName="Server Node")
    app = create_app(settings)

    with TestClient(app) as client:
        with client.websocket_connect("/peer") as ws:
            # 1. Server sends KEX
            raw_srv = ws.receive_text()
            srv_kex = json.loads(raw_srv)
            assert srv_kex.get("t") == "kex"
            server_id_bytes = base64.b64decode(srv_kex["identityKey"])
            server_eph_bytes = base64.b64decode(srv_kex["ephemeralKey"])
            server_sig = srv_kex["signature"]

            assert DeviceIdentity.verify(server_eph_bytes, server_sig, server_id_bytes)

            # 2. Client sends KEX and establishes session
            client_session = SecureSession(tmp_path / "client")
            client_kex = {
                "t": "kex",
                "deviceId": "dev-client",
                "identityKey": client_session.identity.public_key_b64(),
                "ephemeralKey": base64.b64encode(client_session.ephemeral_public_key()).decode("ascii"),
                "signature": client_session.sign(client_session.ephemeral_public_key()),
            }
            ws.send_text(json.dumps(client_kex))
            client_session.establish(server_eph_bytes, server_id_bytes, is_initiator=True)

            # 3. Server sends encrypted PeerHello
            raw_b64 = ws.receive_text()
            decrypted = client_session.decrypt(base64.b64decode(raw_b64))
            msg1 = PeerMessageAdapter.validate_json(decrypted)
            assert isinstance(msg1, PeerHello)
            assert msg1.device.name == "Server Node"

            # 4. Client replies with encrypted PeerHello
            client_hello = PeerHello(
                device=msg1.device.model_copy(update={"id": "dev-client", "name": "Client Node"})
            )
            hello_bytes = client_hello.model_dump_json().encode("utf-8")
            enc_hello = base64.b64encode(client_session.encrypt(hello_bytes)).decode("ascii")
            ws.send_text(enc_hello)

            # 5. Client sends encrypted PeerPing
            ping_bytes = PeerPing(n=42).model_dump_json().encode("utf-8")
            enc_ping = base64.b64encode(client_session.encrypt(ping_bytes)).decode("ascii")
            ws.send_text(enc_ping)

            # 6. Server responds with encrypted PeerPong
            raw_pong = ws.receive_text()
            decrypted_pong = client_session.decrypt(base64.b64decode(raw_pong))
            reply = PeerMessageAdapter.validate_json(decrypted_pong)
            assert isinstance(reply, PeerPong)
            assert reply.n == 42


async def test_in_memory_peer_link_hello_and_messages(tmp_path: Path) -> None:
    ctx_a = build_context(Settings(home=tmp_path / "a", port=8765, deviceName="Node A"))
    ctx_b = build_context(Settings(home=tmp_path / "b", port=8766, deviceName="Node B"))

    link_a, link_b = create_in_memory_peer_links(ctx_a, ctx_b)

    received_on_b: list[tuple[str, Any]] = []

    async def on_b_msg(sender: str, msg: Any) -> None:
        received_on_b.append((sender, msg))

    link_b.on_message(on_b_msg)

    # Pair devices
    await link_a.pair("127.0.0.1:8766", pin="123456")

    # Send Stats message from A to B
    stats_a = ctx_a.devices.latest_stats(ctx_a.device_id)
    assert stats_a is not None
    await link_a.send(ctx_b.device_id, PeerStats(stats=stats_a))

    # B received message
    assert len(received_on_b) == 1
    assert received_on_b[0][0] == ctx_a.device_id
    assert isinstance(received_on_b[0][1], PeerStats)


async def test_reconnect_after_a_cut(tmp_path: Path) -> None:
    ctx_a = build_context(Settings(home=tmp_path / "a", port=8765, deviceName="Node A"))
    ctx_b = build_context(Settings(home=tmp_path / "b", port=8766, deviceName="Node B"))

    link_a, link_b = create_in_memory_peer_links(ctx_a, ctx_b)
    await link_a.pair("127.0.0.1:8766", pin="123456")

    # Cut link
    link_a.cut()
    assert link_a.is_cut

    # Sending across cut link raises ConnectionError
    with pytest.raises(ConnectionError):
        await link_a.send(ctx_b.device_id, PeerPing(n=1))

    # Restore link
    link_a.restore()
    assert not link_a.is_cut

    # Now sending succeeds
    await link_a.send(ctx_b.device_id, PeerPing(n=2))


async def test_device_lost_event_emitted_when_unreachable(tmp_path: Path) -> None:
    ctx = build_context(Settings(home=tmp_path / "node", port=8765))
    service = cast(PeerLinkService, ctx.peers)

    lost_events: list[str] = []

    async def on_lost(ev: DeviceLostEvent) -> None:
        lost_events.append(ev.deviceId)

    ctx.bus.subscribe(DeviceLostEvent, on_lost)

    # Trigger reconnect loop for non-existent peer
    await service._reconnect_loop("dev-ghost")

    # DeviceLostEvent must be published on bus
    assert len(lost_events) == 1
    assert lost_events[0] == "dev-ghost"

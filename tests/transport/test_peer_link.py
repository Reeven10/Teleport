"""Tests for WebSocket peer link: hello exchange, message transmission, reconnect, and device.lost."""

from __future__ import annotations

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
from teleport.transport.service import PeerLinkService

from .in_memory_peer_link import create_in_memory_peer_links


def test_websocket_peer_endpoint_hello_and_ping(tmp_path: Path) -> None:
    settings = Settings(home=tmp_path / "srv", port=8765, deviceName="Server Node")
    app = create_app(settings)

    with TestClient(app) as client:
        with client.websocket_connect("/peer") as ws:
            # 1. Server sends its PeerHello first
            msg1 = PeerMessageAdapter.validate_json(ws.receive_text())
            assert isinstance(msg1, PeerHello)
            assert msg1.device.name == "Server Node"

            # 2. Client replies with its PeerHello
            client_hello = PeerHello(
                device=msg1.device.model_copy(update={"id": "dev-client", "name": "Client Node"})
            )
            ws.send_text(client_hello.model_dump_json())

            # 3. Client sends PeerPing
            ws.send_text(PeerPing(n=42).model_dump_json())

            # 4. Server responds with PeerPong
            reply = PeerMessageAdapter.validate_json(ws.receive_text())
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

"""Matrix row S1: no plaintext state in captured peer-link frames.

Two real agents run in this process (uvicorn, real P2 transport and security, real runner with
counter_job), so every frame either side writes to the peer WebSocket can be recorded exactly as
sent. A frame is base64-decoded before searching, so a session that only base64-wraps JSON fails too.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import os
import socket
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn

import teleport.transport
from teleport.core import Context, Settings, create_app
from tests.migration.e2e.harness import COUNTER_JOB, WID

pytestmark = pytest.mark.skipif(
    hasattr(teleport.transport, "StubPeerLink"), reason="needs the real P2 transport from main"
)

# Anything that would reveal migration state or workload data if it showed up on the wire.
SECRETS = [b"mig.prepare", b"mig.chunk", b"dataB64", b"peer.stats", b"counter-job", b'"count"', b"cpuPct"]


def frame_leaks(frame: str | bytes) -> list[bytes]:
    raw = frame.encode() if isinstance(frame, str) else frame
    views = [raw]
    try:
        views.append(base64.b64decode(raw, validate=True))
    except (binascii.Error, ValueError):
        pass
    return [s for s in SECRETS for v in views if s in v]


def test_detector_catches_plaintext_and_base64_plaintext() -> None:
    plain = json.dumps({"t": "mig.chunk", "dataB64": "AAAA"}).encode()
    assert frame_leaks(plain) and frame_leaks(base64.b64encode(plain))
    assert frame_leaks(base64.b64encode(os.urandom(64))) == []


@pytest.fixture
async def recorded_agents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[tuple[list[str], list[tuple[Context, str]]]]:
    from teleport.transport import connection

    frames: list[str] = []
    for cls in (connection.ClientWSAdapter, connection.StarletteWSAdapter):
        original = cls.send

        async def recording(self: Any, data: str, _original: Any = original) -> None:
            frames.append(data)
            await _original(self, data)

        monkeypatch.setattr(cls, "send", recording)
    monkeypatch.setenv("COUNTER_STEP_S", "0.05")
    monkeypatch.setenv("COUNTER_TARGET", "100000")
    monkeypatch.delenv("TELEPORT_INSECURE_DEV_SESSION", raising=False)

    agents: list[tuple[Context, str]] = []
    servers: list[uvicorn.Server] = []
    for name, profile in (("a", "default"), ("b", "arm64-lowspec")):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        app = create_app(Settings(home=tmp_path / name, port=port, simProfile=profile, uiDist=tmp_path / "x"))
        servers.append(uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")))
        agents.append((app.state.ctx, f"http://127.0.0.1:{port}"))
    tasks = [asyncio.create_task(srv.serve()) for srv in servers]
    while not all(srv.started for srv in servers):  # noqa: ASYNC110 - uvicorn exposes a flag only
        await asyncio.sleep(0.02)
    try:
        yield frames, agents
    finally:
        for srv in servers:
            srv.should_exit = True
        await asyncio.gather(*tasks)


async def test_s1_peer_traffic_is_encrypted_during_a_migration(
    recorded_agents: tuple[list[str], list[tuple[Context, str]]],
) -> None:
    frames, [(a, url_a), (b, url_b)] = recorded_agents
    async with httpx.AsyncClient(timeout=30) as http:
        pin = (await http.get(f"{url_b}/api/pair")).json()["pin"]
        res = await http.post(f"{url_a}/api/pair", json={"addr": url_b.removeprefix("http://"), "pin": pin})
        assert res.status_code == 200, res.text
        res = await http.post(f"{url_a}/api/workloads/start", json={"manifestPath": str(COUNTER_JOB)})
        assert res.status_code == 200, res.text
        await asyncio.sleep(1.5)
        res = await http.post(f"{url_a}/api/migrations", json={"workloadId": WID, "targetId": b.device_id})
        mid = res.json()["id"]
        deadline = time.monotonic() + 30
        while (st := a.migration.status(mid)) is None or st.phase not in (
            "COMPLETED",
            "ROLLED_BACK",
            "FAILED",
        ):
            assert time.monotonic() < deadline, "migration did not finish"
            await asyncio.sleep(0.1)
    assert st.phase == "COMPLETED", st.error
    await b.workloads.terminate(WID)

    assert len(frames) > 20, "nothing was captured"
    handshake = [f for f in frames if f.lstrip().startswith("{")]
    for f in handshake:  # only the key exchange travels as JSON: public keys, no state
        assert json.loads(f).get("t") in ("kex", "kex_ack", "hello", "auth"), f[:200]
    leaks = {i: found for i, f in enumerate(frames) if (found := frame_leaks(f))}
    assert leaks == {}, f"{len(leaks)} of {len(frames)} frames leak plaintext, e.g. {list(leaks.items())[:3]}"

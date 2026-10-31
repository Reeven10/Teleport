from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from contract.contract import (
    AuthorityService,
    BusEventAdapter,
    DeviceService,
    FeasibilityEngine,
    HistoryStore,
    MigrationManager,
    Orchestrator,
    PeerLink,
    RemoteService,
    SecureSession,
    StatsUpdateEvent,
)
from teleport.core import Context, Settings, build_context
from teleport.security import SecureSession as SecureSessionImpl


def test_health(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["ok"] is True
    assert body["deviceId"].startswith("dev-")


def test_stubs_satisfy_protocols(ctx: Context) -> None:
    assert isinstance(ctx.devices, DeviceService)
    assert isinstance(ctx.peers, PeerLink)
    assert isinstance(ctx.feasibility, FeasibilityEngine)
    assert isinstance(ctx.orchestrator, Orchestrator)
    assert isinstance(ctx.history, HistoryStore)
    assert isinstance(ctx.migration, MigrationManager)
    assert isinstance(ctx.authority, AuthorityService)
    assert isinstance(ctx.remote, RemoteService)
    assert isinstance(SecureSessionImpl(), SecureSession)


def test_ws_events_streams_stats(client: TestClient) -> None:
    with client.websocket_connect("/ws/events") as ws:
        event = BusEventAdapter.validate_json(ws.receive_text())
    assert isinstance(event, StatsUpdateEvent)


def test_sim_profile_is_labeled(tmp_path: Path) -> None:
    ctx = build_context(Settings(home=tmp_path, simProfile="arm64-lowspec"))
    info = ctx.devices.local_info()
    assert info.arch == "arm64" and info.simulated is True


def test_rest_routes(client: TestClient, tmp_path: Path) -> None:
    assert client.get("/api/devices").status_code == 200
    assert client.get("/api/history/decisions").json() == []
    assert client.put("/api/settings", json={"mode": "auto"}).json()["mode"] == "auto"
    assert client.post("/api/pair", json={"addr": "x", "pin": "1"}).status_code == 501

    manifest = {
        "id": "w1",
        "name": "demo",
        "command": "python app.py",
        "runtime": {"name": "python", "minVersion": "3.11"},
        "arch": ["x86_64"],
        "os": ["linux"],
        "minRamMb": 100,
        "minCpuCores": 1,
        "minDiskMb": 10,
        "needsGpu": False,
        "libs": [],
        "checkpoints": [{"id": "c1", "name": "config", "paths": ["config.json"]}],
        "remoteCapable": True,
    }
    path = tmp_path / "w1.json"
    path.write_text(json.dumps(manifest))
    assert client.post("/api/workloads/start", json={"manifestPath": str(path)}).json()["id"] == "w1"
    assert [w["id"] for w in client.get("/api/workloads").json()] == ["w1"]

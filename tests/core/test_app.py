from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from contract.contract import (
    AuthorityService,
    BusEventAdapter,
    DevicePairedEvent,
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
from teleport.core import Context, Settings, build_context, create_app
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
    # 501 with the P1 transport stub, 502 (unreachable) with P2's real peer link.
    assert client.post("/api/pair", json={"addr": "127.0.0.1:1", "pin": "1"}).status_code in (501, 502)

    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "teleport.yaml").write_text("name: x\n")
    res = client.post("/api/workloads/start", json={"manifestPath": str(bad)})
    assert res.status_code == 400 and "command: Field required" in res.json()["problems"]
    assert client.post("/api/workloads/start", json={"manifestPath": "nope/"}).status_code == 404
    assert client.get("/api/workloads").json() == []


def test_dashboard_settings_persist_and_apply(tmp_path: Path) -> None:
    settings = Settings(home=tmp_path / "home", uiDist=tmp_path / "no-ui")
    payload = {
        "mode": "auto",
        "batteryLowPct": 25,
        "cpuHighPct": 85,
        "memHighPct": 80,
        "predictionWindowSec": 120,
        "preferredLink": "cable",
        "checkpointChunkKb": 1024,  # the dashboard's name and default: clamped to the 512 KB limit
        "remoteConsent": "deny_all",
    }
    app = create_app(settings)
    with TestClient(app) as client:
        saved = client.put("/api/settings", json=payload).json()
        assert {k: saved[k] for k in ("predictionWindowSec", "preferredLink", "remoteConsent")} == {
            "predictionWindowSec": 120,
            "preferredLink": "cable",
            "remoteConsent": "deny_all",
        }
        assert saved["chunkSizeKb"] == saved["checkpointChunkKb"] == 512
        assert getattr(app.state.ctx.peers, "_forced_link", "cable") == "cable"  # applied to the link
        assert client.put("/api/settings", json={"preferedLink": "wifi"}).status_code == 422  # typo
        assert client.put("/api/settings", json={"remoteConsent": "always"}).status_code == 422

    with TestClient(create_app(settings)) as client:  # survives a restart
        again = client.get("/api/settings").json()
        assert (again["mode"], again["preferredLink"], again["chunkSizeKb"]) == ("auto", "cable", 512)
        assert client.put("/api/settings", json={"preferredLink": "auto"}).json()["preferredLink"] == "auto"


def test_history_module_router_is_mounted(client: TestClient) -> None:
    import teleport.history

    if not hasattr(teleport.history, "build_history_router"):
        return  # P1 stub: core's minimal contract routes serve /api/history
    assert client.get("/api/history/export").status_code == 200  # only P3's router has these
    assert client.get("/api/history/devices/unknown").status_code == 404
    assert client.get("/api/history/migrations?limit=5").json() == []
    ctx: Context = client.app.state.ctx  # type: ignore[attr-defined]
    peer = ctx.devices.local_info().model_copy(update={"id": "dev-peer", "name": "Peer"})
    client.portal.call(ctx.bus.publish, DevicePairedEvent(device=peer))  # type: ignore[union-attr]
    devices = client.get("/api/history/devices").json()
    # P3's summaries, not core's DeviceInfo list: core's copy of the route must not shadow it
    assert [d["id"] for d in devices] == ["dev-peer"] and "firstSeen" in devices[0]
    assert client.get("/api/settings").json()["predictionWindowSec"] == 600

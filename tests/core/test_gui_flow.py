"""The no-terminal demo flow: dashboard served for every page path, LAN discovery, one-click apps,
a VS Code workload folder, and stopping a workload from the dashboard."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from teleport.apps import create_vscode_workload, gallery
from teleport.core import Settings, build_context, create_app
from teleport.core.discovery import Discovery, broadcast_addresses

COUNTER_JOB = Path(__file__).resolve().parents[1] / "fixtures" / "counter_job"


def test_dashboard_page_paths_serve_index(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>teleport</html>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    with TestClient(create_app(Settings(home=tmp_path / "home", uiDist=dist))) as client:
        for page in ("/", "/migration", "/workloads", "/history"):
            res = client.get(page)
            assert res.status_code == 200 and "teleport" in res.text, page  # a refresh works on any tab
        assert client.get("/assets/app.js").text == "console.log(1)"
        assert client.get("/api/nope").status_code == 404  # API paths are not swallowed
        assert client.get("/api/health").json()["ok"] is True


def test_discovery_records_beacons_from_others_only(tmp_path: Path) -> None:
    ctx = build_context(Settings(home=tmp_path, host="0.0.0.0", port=8765))
    disco = Discovery(ctx)
    assert disco.enabled
    other = {
        "t": "teleport.beacon",
        "v": 1,
        "deviceId": "dev-b",
        "name": "Laptop B",
        "os": "macos",
        "port": 8765,
    }
    disco.on_beacon(json.dumps(other).encode(), "192.168.1.35")
    disco.on_beacon(json.dumps({**other, "deviceId": ctx.device_id}).encode(), "192.168.1.20")  # our own echo
    disco.on_beacon(b"not json", "192.168.1.99")
    nearby = disco.nearby()
    assert [(d["deviceId"], d["addr"], d["paired"]) for d in nearby] == [
        ("dev-b", "192.168.1.35:8765", False)
    ]
    assert "255.255.255.255" in broadcast_addresses()


def test_discovery_is_off_on_loopback(tmp_path: Path) -> None:
    assert not Discovery(build_context(Settings(home=tmp_path, host="127.0.0.1"))).enabled


def test_vscode_workload_folder(tmp_path: Path) -> None:
    project = tmp_path / "my project"
    (project / "src").mkdir(parents=True)
    (project / "src" / "main.py").write_text("print('hi')\n")
    folder = create_vscode_workload(tmp_path / "home", str(project))
    manifest = yaml.safe_load((folder / "teleport.yaml").read_text())
    assert manifest["id"] == "vscode-my-project" and "vscode" in manifest["libs"]
    assert [c["id"] for c in manifest["checkpoints"]] == ["project", "session"]
    assert manifest["checkpoints"][0]["paths"] == ["project"]
    assert (folder / "vscode_job.py").is_file() and (folder / "extension" / "extension.js").is_file()
    assert json.loads((folder / "app.json").read_text())["projectPath"] == str(project.resolve())
    with pytest.raises(FileNotFoundError):
        create_vscode_workload(tmp_path / "home", str(tmp_path / "missing"))


def test_apps_gallery_and_stop_from_the_dashboard(tmp_path: Path) -> None:
    assert {a["id"] for a in gallery()} == {"counter", "vscode"}
    with TestClient(create_app(Settings(home=tmp_path / "home", uiDist=tmp_path / "x"))) as client:
        assert {a["id"] for a in client.get("/api/apps").json()} == {"counter", "vscode"}
        assert (
            client.post("/api/apps/vscode", json={"projectPath": str(tmp_path / "nope")}).status_code == 404
        )
        assert client.get("/api/discovery").json() == []  # loopback agent: discovery off
        assert client.post("/api/workloads/nope/stop").status_code == 404

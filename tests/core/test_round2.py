"""Mentor round 2: start fresh, server projects with dependencies, per-migration authority, folder picker."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from teleport_sdk.unit import unpack_unit

from contract.contract import DeviceInfo
from teleport.apps import create_server_workload, create_vscode_workload
from teleport.apps.server import detect_project
from teleport.authority import AuthorityError, AuthorityStore
from teleport.core import Settings, build_context, create_app
from teleport.migration.store import CheckpointStore


def _write(folder: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(text, "utf-8")
    return folder


# ---------------------------------------------------------------- server projects


def test_detects_node_server_with_lockfile_and_port(tmp_path: Path) -> None:
    pkg = {
        "scripts": {"start": "node server.js"},
        "dependencies": {"express": "^4"},
        "engines": {"node": ">=18"},
    }
    _write(
        tmp_path,
        {"package.json": json.dumps(pkg), "package-lock.json": "{}", "server.js": "app.listen(4000)"},
    )
    found = detect_project(tmp_path)
    assert found["kind"] == "node" and found["command"] == "npm start"
    assert found["install"] == "npm ci" and found["port"] == 4000
    assert found["runtime"] == {"name": "node", "minVersion": "18"}


def test_detects_python_servers(tmp_path: Path) -> None:
    flask = _write(
        tmp_path / "f",
        {"app.py": "from flask import Flask\napp = Flask(__name__)\n", "requirements.txt": "flask\n"},
    )
    found = detect_project(flask)
    assert found["kind"] == "python" and "flask --app app run" in found["command"] and found["port"] == 5000
    assert found["dependencies"] == ["flask"]
    plain = _write(tmp_path / "p", {"server.py": "PORT = 8080\nif __name__ == '__main__':\n    pass\n"})
    assert detect_project(plain)["command"] == "python server.py" and detect_project(plain)["port"] == 8080
    django = _write(tmp_path / "d", {"manage.py": "", "requirements.txt": "django\n"})
    assert "runserver" in detect_project(django)["command"]
    with pytest.raises(ValueError):
        detect_project(_write(tmp_path / "x", {"notes.txt": "hi"}))


def test_server_workload_folder(tmp_path: Path) -> None:
    project = _write(tmp_path / "shop", {"package.json": json.dumps({"main": "index.js"}), "index.js": ""})
    folder = create_server_workload(tmp_path / "home", str(project), origin="dev-a", port=3100)
    manifest = yaml.safe_load((folder / "teleport.yaml").read_text())
    assert manifest["id"].startswith("server-shop-") and manifest["runtime"]["name"] == "node"
    assert manifest["checkpoints"] == [
        {"id": "project", "name": "Project files and data (dependencies reinstalled)", "paths": ["project"]}
    ]
    app = json.loads((folder / "app.json").read_text())
    assert app["command"] == "node index.js" and app["port"] == 3100 and app["kind"] == "node"
    assert (folder / "server_job.py").is_file()


def test_same_folder_name_on_two_devices_gets_two_workloads(tmp_path: Path) -> None:
    a = _write(tmp_path / "a" / "demo", {"server.py": "if __name__ == '__main__': pass"})
    b = _write(tmp_path / "b" / "demo", {"server.py": "if __name__ == '__main__': pass"})
    ids = {
        create_server_workload(tmp_path / "h1", str(a), origin="dev-a").name,
        create_server_workload(tmp_path / "h2", str(b), origin="dev-b").name,
        create_vscode_workload(tmp_path / "h3", str(a), origin="dev-a").name,
        create_vscode_workload(tmp_path / "h4", str(a), origin="dev-b").name,
    }
    assert len(ids) == 4  # never one shared lease for two different projects


def test_dependencies_never_travel_in_a_checkpoint(tmp_path: Path) -> None:
    work = _write(
        tmp_path / "work",
        {
            "project/server.js": "x",
            "project/node_modules/express/index.js": "big",
            "project/.venv/lib/site.py": "big",
            "project/data/db.json": "{}",
        },
    )
    store = CheckpointStore(tmp_path / "home")
    store.pack_paths("wl", "project", work, ["project"])
    out = tmp_path / "out"
    unpack_unit(store.read("wl", "project") or b"", out)
    names = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}
    assert any(n.endswith("project/server.js") for n in names)
    assert any(n.endswith("project/data/db.json") for n in names)
    assert not any("node_modules" in n or ".venv" in n for n in names)


def test_server_routes(tmp_path: Path) -> None:
    project = _write(tmp_path / "api", {"main.py": "if __name__ == '__main__': pass"})
    with TestClient(create_app(Settings(home=tmp_path / "home", uiDist=tmp_path / "x"))) as client:
        res = client.post("/api/apps/server/detect", json={"projectPath": str(project)})
        assert res.status_code == 200 and res.json()["command"] == "python main.py"
        assert (
            client.post("/api/apps/server/detect", json={"projectPath": str(tmp_path / "nope")}).status_code
            == 404
        )
        assert (
            client.post("/api/apps/server", json={"projectPath": str(project), "port": 70000}).status_code
            == 400
        )


# ---------------------------------------------------------------- authority per migration


async def test_each_migration_stamps_and_owns_its_lease(tmp_path: Path) -> None:
    ctx = build_context(Settings(home=tmp_path))
    auth = AuthorityStore(ctx)
    await auth.claim("web", ctx.device_id)
    await auth.claim("api", ctx.device_id)
    fenced = await auth.fence("web", "mig-1")
    assert fenced.migrationId == "mig-1" and auth.owned_by("web", "mig-1")
    assert auth.get("api").migrationId is None  # another workload's lease is untouched
    with pytest.raises(AuthorityError):
        await auth.rollback("web", "mig-2")  # only the migration that fenced may undo it
    granted = await auth.grant("web", "dev-b", fenced.epoch, "mig-1")
    assert granted.migrationId == "mig-1" and granted.state == "TARGET"
    with pytest.raises(AuthorityError):
        await auth.grant("web", "dev-c", fenced.epoch, "mig-9")  # same epoch, different migration
    assert [lease.workloadId for lease in auth.leases()] == ["web", "api"]


def test_authority_route_lists_leases(tmp_path: Path) -> None:
    with TestClient(create_app(Settings(home=tmp_path / "home", uiDist=tmp_path / "x"))) as client:
        assert client.get("/api/authority").json() == []


# ---------------------------------------------------------------- start fresh


def test_forget_all_devices_keeps_history_working(tmp_path: Path) -> None:
    app = create_app(Settings(home=tmp_path / "home", uiDist=tmp_path / "x"))
    with TestClient(app) as client:
        ctx = app.state.ctx
        me = ctx.devices.local_info()
        peer = me.model_copy(update={"id": "dev-peer", "name": "Old laptop"})
        ctx.devices.record_peer_device(DeviceInfo.model_validate(peer.model_dump()))
        assert any(d["id"] == "dev-peer" for d in client.get("/api/devices").json())
        res = client.post("/api/reset/devices")
        assert res.status_code == 200 and res.json()["devices"] == 1
        assert [d["id"] for d in client.get("/api/devices").json()] == [me.id]
        assert client.get("/api/history/devices").status_code == 200  # the feature is still there
        forgotten = json.loads((tmp_path / "home" / "forgotten_peers.json").read_text())
        assert forgotten == ["dev-peer"]  # it cannot just reconnect: it must pair again


def test_folder_picker_is_local_only(tmp_path: Path) -> None:
    app = create_app(Settings(home=tmp_path / "home", uiDist=tmp_path / "x"))
    with TestClient(app, client=("192.0.2.50", 5000)) as client:
        assert client.post("/api/pick-folder", json={}).status_code == 403
        assert client.post("/api/reset/devices").status_code == 403

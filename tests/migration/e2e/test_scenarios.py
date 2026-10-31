"""Integration scenarios 1 to 4 with real agents, real modules and the real peer link."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

import psutil
import pytest
import yaml

import teleport.transport
from tests.migration.e2e.conftest import AgentFactory
from tests.migration.e2e.harness import (
    COUNTER_JOB,
    WID,
    Agent,
    EventStream,
    last_count,
    launch,
    migrate,
    pair,
    wait_until,
)

pytestmark = pytest.mark.skipif(
    hasattr(teleport.transport, "StubPeerLink"),
    reason="needs the real P2/P3/P4 modules from main (this branch still has the P1 stubs)",
)

USER_CHECKPOINTS = {"config", "counter", "history", "stats", "journal", "meta"}


# ---------------------------------------------------------------- scenario 1


def test_1_pair_and_see_both_devices_with_live_stats(dev_two: tuple[Agent, Agent]) -> None:
    a, b = dev_two
    events = EventStream(a)
    try:
        paired = pair(a, b)
        assert paired["id"] == b.device_id and paired["name"] == "Device B"

        for agent in (a, b):
            names = {d["name"] for d in agent.get("/api/devices")}
            assert names == {"Device A", "Device B"}, f"{agent.name} sees {names}"
        devices = {d["id"]: d for d in a.get("/api/devices")}
        assert devices[b.device_id]["arch"] == "arm64" and devices[b.device_id]["simulated"] is True

        def live_from_both() -> bool:
            ids = {e["stats"]["deviceId"] for e in events.of("stats.update")}
            return {a.device_id, b.device_id} <= ids

        wait_until(live_from_both, timeout=15, what="stats.update from both devices on A's /ws/events")
        b_stats = [e["stats"] for e in events.of("stats.update") if e["stats"]["deviceId"] == b.device_id]
        assert all(s["simulated"] for s in b_stats)  # simulated data stays labeled
        assert {s["deviceId"] for s in a.get("/api/stats")} == {a.device_id, b.device_id}
        assert any(e["device"]["id"] == b.device_id for e in events.of("device.paired"))
        assert b.device_id in {d["id"] for d in a.get("/api/history/devices")}
    finally:
        events.close()


# ---------------------------------------------------------------- scenario 2


def test_2_migrate_counter_job_to_b(dev_two: tuple[Agent, Agent]) -> None:
    a, b = dev_two
    pair(a, b)
    events = EventStream(a)
    try:
        launch(a, COUNTER_JOB)
        pid_a = a.run(WID)["pid"]  # type: ignore[index]
        before = last_count(a)

        mid = migrate(a, b)
        st = a.wait_migration(mid)

        assert st["phase"] == "COMPLETED", st.get("error")
        assert st["decision"] == "MIGRATE"
        assert {r["code"] for r in st["reasons"]} >= {
            "arch.match",
            "os.match",
            "runtime.ok",
            "ram.sufficient",
        }
        ids = {c["id"] for c in st["checkpoints"]}
        assert USER_CHECKPOINTS <= ids
        assert all(c["sent"] and c["validated"] for c in st["checkpoints"])
        assert st["interruptionMs"] > 0
        assert st["bytesDone"] == st["bytesTotal"] > 0
        assert (st["authority"]["holder"], st["authority"]["state"]) == (b.device_id, "TARGET")
        phases = [e["status"]["phase"] for e in events.of("migration.status") if e["status"]["id"] == mid]
        for phase in ("CONNECTING", "EVALUATING", "TRANSFERRING", "VALIDATING", "FENCING", "STARTING_TARGET"):
            assert phase in phases
        assert any(e["authority"]["holder"] == b.device_id for e in events.of("authority.change"))

        # A's copy is gone, B resumed from the last state and keeps counting.
        assert a.run(WID)["state"] == "stopped"  # type: ignore[index]
        assert not psutil.pid_exists(pid_a)
        resumed = wait_until(
            lambda: next((ln for ln in b.run(WID)["logTail"] if "resumed count=" in ln), None),  # type: ignore[index]
            what="resume line on B",
        )
        match = re.search(r"resumed count=(\d+) runs=2", resumed)
        assert match is not None and int(match[1]) >= before
        wait_until(lambda: last_count(b) > int(match[1]) + 3, what="B counting")

        target_view = b.migration(mid)
        assert target_view is not None and target_view["phase"] == "COMPLETED"
        assert mid in {m["id"] for m in a.get("/api/history/migrations")}
    finally:
        events.close()


# ---------------------------------------------------------------- scenario 3


def x86_only_job(tmp: Path) -> Path:
    job = tmp / "x86_job"
    shutil.copytree(COUNTER_JOB, job)
    manifest: dict[str, Any] = yaml.safe_load((job / "teleport.yaml").read_text())
    manifest.update(id="x86-job", name="x86 counter", arch=["x86_64"])
    (job / "teleport.yaml").write_text(yaml.safe_dump(manifest))
    return job


def test_3_incompatible_target_means_remote_access(dev_two: tuple[Agent, Agent], tmp_path: Path) -> None:
    a, b = dev_two  # B is the arm64 low-spec simulated profile
    pair(a, b)
    events = EventStream(a)
    try:
        launch(a, x86_only_job(tmp_path), "x86-job")
        st = a.wait_migration(migrate(a, b, "x86-job"))

        assert st["phase"] == "REMOTE_ACCESS" and st["decision"] == "REMOTE_ACCESS"
        blocks = [r for r in st["reasons"] if r["severity"] == "block"]
        assert any(r["code"].startswith("arch") for r in blocks), st["reasons"]
        assert all(r["text"] for r in st["reasons"])

        # The job keeps running on A, with A's authority.
        assert a.run("x86-job")["state"] == "running"  # type: ignore[index]
        count = last_count(a, "x86-job")
        wait_until(lambda: last_count(a, "x86-job") > count, what="A still counting")
        assert st["authority"]["holder"] == a.device_id
        assert b.run("x86-job") is None

        # What the dashboard needs to offer the remote view: a pending session for B, on the bus too.
        sessions = a.get("/api/remote/sessions")
        assert [(s["workloadId"], s["viewerId"]) for s in sessions] == [("x86-job", b.device_id)]
        assert sessions[0]["consent"] is False  # host consent is still required
        wait_until(lambda: events.of("remote.session"), what="remote.session event")
        assert a.http.get("/api/remote/viewer").status_code == 200
    finally:
        events.close()


# ---------------------------------------------------------------- scenario 4


def test_4_target_killed_mid_transfer_rolls_back(start_agent: AgentFactory) -> None:
    a = start_agent("Device A", "default", TELEPORT_DEV_SLOW_TRANSFER_MS="400")
    b = start_agent("Device B", "arm64-lowspec")
    pair(a, b)
    launch(a, COUNTER_JOB)

    mid = migrate(a, b)

    def transferring() -> bool:
        m = a.migration(mid)
        return bool(m and m["phase"] == "TRANSFERRING" and m["bytesDone"] > 0)

    wait_until(transferring, timeout=20, what="transfer under way")
    b.kill()
    st = a.wait_migration(mid, timeout=60)

    assert st["phase"] == "ROLLED_BACK"
    assert st["error"]
    rollback = [r for r in st["reasons"] if r["code"] == "rollback"]
    assert rollback and rollback[0]["severity"] == "block" and rollback[0]["text"].startswith("Rolled back")
    assert not any(c["validated"] for c in st["checkpoints"])
    assert (st["authority"]["holder"], st["authority"]["state"]) == (a.device_id, "SOURCE")

    # A never stopped: same process, still counting.
    run = a.run(WID)
    assert run is not None and run["state"] == "running"
    count = last_count(a)
    wait_until(lambda: last_count(a) > count + 2, what="A still counting after rollback")

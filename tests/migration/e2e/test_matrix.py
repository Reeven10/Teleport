"""docs/TEST_MATRIX.md rows that need real agents: STAY, triggers, history, reasons, restart.

Each test names its matrix row. Real P2/P3/P4 modules, agents as subprocesses (`dev:two` style).
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any

import pytest
import yaml

import teleport.transport
from tests.migration.e2e.conftest import AgentFactory
from tests.migration.e2e.harness import (
    COUNTER_JOB,
    WID,
    Agent,
    EventStream,
    launch,
    migrate,
    pair,
    wait_until,
)

pytestmark = pytest.mark.skipif(
    hasattr(teleport.transport, "StubPeerLink"),
    reason="needs the real P2/P3/P4 modules from main",
)
SEVERITIES = {"pass", "warn", "block"}


def variant(tmp: Path, name: str, **changes: Any) -> Path:
    """A copy of counter_job with manifest changes (another id, so it can run next to the original)."""
    job = tmp / name
    shutil.copytree(COUNTER_JOB, job)
    manifest: dict[str, Any] = yaml.safe_load((job / "teleport.yaml").read_text())
    manifest.update(id=name, name=name, **changes)
    (job / "teleport.yaml").write_text(yaml.safe_dump(manifest))
    return job


def assert_reasons(reasons: list[dict[str, Any]]) -> None:
    """Matrix row R1: every decision carries reasons, each with a severity and a sentence."""
    assert reasons, "decision without reasons"
    for r in reasons:
        assert r["severity"] in SEVERITIES and r["code"] and len(r["text"]) > 10, r


def set_mode(agent: Agent, mode: str) -> None:
    res = agent.http.put("/api/settings", json={"mode": mode})
    assert res.status_code == 200 and res.json()["mode"] == mode, res.text


def override(agent: Agent, stats: dict[str, Any], device_id: str | None = None) -> None:
    agent.post("/api/dev/stats-override", {"deviceId": device_id or agent.device_id, "stats": stats})


def recommendations(events: EventStream, trigger: str) -> list[dict[str, Any]]:
    return [e["rec"] for e in events.of("recommendation") if e["rec"]["trigger"] == trigger]


# ---------------------------------------------------------------- F3: STAY


def test_f3_stay_when_neither_migration_nor_remote_works(
    dev_two: tuple[Agent, Agent], tmp_path: Path
) -> None:
    a, b = dev_two
    pair(a, b)
    job = variant(tmp_path, "gpu-job", needsGpu=True, remoteCapable=False)
    launch(a, job, "gpu-job")
    st = a.wait_migration(migrate(a, b, "gpu-job"))
    assert st["phase"] == "FAILED" and st["decision"] == "STAY"
    assert any(r["code"].startswith("gpu") and r["severity"] == "block" for r in st["reasons"]), st["reasons"]
    assert_reasons(st["reasons"])
    assert a.run("gpu-job")["state"] == "running"  # type: ignore[index]


# ---------------------------------------------------------------- T1-T4: triggers


def test_t1_low_battery_auto_mode_migrates(dev_two: tuple[Agent, Agent]) -> None:
    a, b = dev_two
    pair(a, b)
    launch(a, COUNTER_JOB)
    set_mode(a, "auto")
    events = EventStream(a)
    try:
        override(a, {"battery": {"pct": 5, "charging": False}})
        rec = wait_until(lambda: recommendations(events, "low_battery"), 20, "low_battery recommendation")[0]
        assert rec["auto"] is True and rec["targetId"] == b.device_id and rec["decision"] == "MIGRATE"
        assert_reasons(rec["reasons"])

        def auto_migration() -> dict[str, Any] | None:
            return next((m for m in a.get("/api/migrations") if m["trigger"] == "low_battery"), None)

        mig = wait_until(auto_migration, 20, "the auto migration")
        st = a.wait_migration(mig["id"])
        assert st["phase"] == "COMPLETED" and st["targetId"] == b.device_id, st.get("error")
        wait_until(lambda: (b.run(WID) or {}).get("state") == "running", 20, "job running on B")
    finally:
        events.close()


def test_t1b_low_battery_recommend_mode_only_recommends(dev_two: tuple[Agent, Agent]) -> None:
    a, b = dev_two
    pair(a, b)
    launch(a, COUNTER_JOB)
    events = EventStream(a)
    try:
        override(a, {"battery": {"pct": 5, "charging": False}})
        rec = wait_until(lambda: recommendations(events, "low_battery"), 20, "low_battery recommendation")[0]
        assert rec["auto"] is False and rec["decision"] == "MIGRATE"
        assert_reasons(rec["reasons"])
        time.sleep(2)
        assert a.get("/api/migrations") == []  # recommend mode never migrates on its own
    finally:
        events.close()


def test_t1c_peer_low_battery_does_not_move_local_workloads(dev_two: tuple[Agent, Agent]) -> None:
    a, b = dev_two
    pair(a, b)
    launch(a, COUNTER_JOB)
    set_mode(a, "auto")
    events = EventStream(a)
    try:
        override(b, {"battery": {"pct": 5, "charging": False}})  # B is low, A is fine
        wait_until(
            lambda: any(
                e["stats"]["deviceId"] == b.device_id and (e["stats"].get("battery") or {}).get("pct") == 5
                for e in events.of("stats.update")
            ),
            15,
            "B's low battery to reach A",
        )
        time.sleep(4)
        assert recommendations(events, "low_battery") == [], "A reacted to B's battery"
        assert a.get("/api/migrations") == []
    finally:
        events.close()


def test_t2_cpu_pressure_recommends_after_sustained_load(dev_two: tuple[Agent, Agent]) -> None:
    a, b = dev_two
    pair(a, b)
    launch(a, COUNTER_JOB)
    events = EventStream(a)
    try:
        override(a, {"cpuPct": 97})
        rec = wait_until(lambda: recommendations(events, "cpu_pressure"), 40, "cpu_pressure recommendation")[
            0
        ]
        assert rec["targetId"] == b.device_id
        assert_reasons(rec["reasons"])
    finally:
        events.close()


@pytest.mark.xfail(
    strict=True,
    reason="P2-8: the link flaps (reconnects report 0% loss); P3-7: connectivity_lost ignores device.lost",
)
def test_t3_lost_connectivity_is_detected_and_recommended(dev_two: tuple[Agent, Agent]) -> None:
    a, b = dev_two
    pair(a, b)
    launch(a, COUNTER_JOB)
    events = EventStream(a)
    try:
        a.post("/api/dev/fault-inject", {"peerId": b.device_id, "dropRate": 1.0})
        rec = wait_until(
            lambda: recommendations(events, "connectivity_lost"), 40, "connectivity_lost recommendation"
        )
        assert_reasons(rec[0]["reasons"])
    finally:
        a.post("/api/dev/fault-inject/clear", {"peerId": b.device_id})
        events.close()


# ---------------------------------------------------------------- H1, R1: history and reasons


def test_h1_history_is_saved_and_survives_restart(start_agent: AgentFactory) -> None:
    a = start_agent("Device A", "default")
    b = start_agent("Device B", "arm64-lowspec")
    pair(a, b)
    launch(a, COUNTER_JOB)
    st = a.wait_migration(migrate(a, b))
    assert st["phase"] == "COMPLETED", st.get("error")

    def saved(agent: Agent) -> bool:
        migrations = {m["id"]: m for m in agent.get("/api/history/migrations")}
        decisions = agent.get("/api/history/decisions")
        devices = {d["id"] for d in agent.get("/api/history/devices")}
        return (
            migrations.get(st["id"], {}).get("phase") == "COMPLETED"
            and any(d.get("migrationId") == st["id"] for d in decisions)
            and b.device_id in devices
        )

    wait_until(lambda: saved(a), 15, "migration, decision and device in A's history")
    for d in a.get("/api/history/decisions"):
        assert_reasons(d["reasons"])

    a.kill()  # restart A on the same TELEPORT_HOME: history comes back from SQLite
    again = Agent("Device A", a.port, a.home, "default", {})
    try:
        assert saved(again)
        assert again.migration(st["id"])["phase"] == "COMPLETED"  # type: ignore[index]  # migration journal
    finally:
        again.close()

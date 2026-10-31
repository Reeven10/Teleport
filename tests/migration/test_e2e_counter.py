"""Real end to end: two live agents (real runner, store, subprocesses) migrate counter_job over the
in-memory peer link, driven through the REST API."""

from __future__ import annotations

import asyncio
import re
import socket
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast

import httpx
import psutil
import pytest
import uvicorn
from fastapi import FastAPI
from teleport_sdk.unit import decode_state, unpack_unit

from teleport.core import Context, Settings, create_app
from teleport.migration import MigrationManager
from tests.migration.conftest import FAST
from tests.migration.mocks import MockFeasibility, link_pair

COUNTER_JOB = Path(__file__).resolve().parents[1] / "fixtures" / "counter_job"
WID = "counter-job"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


@pytest.fixture
async def agents(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[list[tuple[Context, str]]]:
    monkeypatch.setenv("COUNTER_STEP_S", "0.05")
    monkeypatch.setenv("COUNTER_TARGET", "100000")
    apps: list[FastAPI] = []
    for name in ("a", "b"):
        port = free_port()
        apps.append(create_app(Settings(home=tmp_path / name, port=port, uiDist=tmp_path / "no-ui")))
    ctxs: list[Context] = [app.state.ctx for app in apps]
    la, lb = link_pair(ctxs[0], ctxs[1])
    for ctx, link in zip(ctxs, (la, lb), strict=True):
        ctx.register("peers", link)
        ctx.register("feasibility", MockFeasibility())
        cast(MigrationManager, ctx.migration).timeouts = FAST
    servers = [
        uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=ctx.settings.port, log_level="warning"))
        for app, ctx in zip(apps, ctxs, strict=True)
    ]
    tasks = [asyncio.create_task(s.serve()) for s in servers]
    while not all(s.started for s in servers):  # noqa: ASYNC110 - uvicorn exposes a flag, not an event
        await asyncio.sleep(0.02)
    try:
        yield [(ctx, f"http://127.0.0.1:{ctx.settings.port}") for ctx in ctxs]
    finally:
        for s in servers:
            s.should_exit = True
        await asyncio.gather(*tasks)


def saved_count(ctx: Context) -> int:
    data = ctx.checkpoints.read(WID, "counter")
    if data is None:
        return -1
    state = decode_state(*unpack_unit(data))
    assert isinstance(state, dict)
    return int(state["count"])


async def until(cond: Any, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < deadline, "timed out"
        await asyncio.sleep(0.05)


async def test_counter_job_migrates_and_keeps_counting(agents: list[tuple[Context, str]]) -> None:
    (a, url_a), (b, url_b) = agents
    async with httpx.AsyncClient(base_url=url_a, timeout=30) as api:
        res = await api.post("/api/workloads/start", json={"manifestPath": str(COUNTER_JOB)})
        assert res.status_code == 200, res.text
        await until(lambda: saved_count(a) >= 5)
        pid_a = a.workloads.status(WID).pid
        assert pid_a is not None

        res = await api.post("/api/migrations", json={"workloadId": WID, "targetId": b.device_id})
        assert res.status_code == 200, res.text
        mid = res.json()["id"]
        status: dict[str, Any] = {}

        def finished() -> bool:
            nonlocal status
            status = next(m for m in a.migration.list() if m.id == mid).model_dump()
            return status["phase"] in ("COMPLETED", "ROLLED_BACK", "FAILED")

        await until(finished)
        assert status["phase"] == "COMPLETED", status.get("error")
        listed = (await api.get("/api/migrations")).json()
        assert [m["id"] for m in listed] == [mid] and listed[0]["interruptionMs"] > 0
        assert (await api.post("/api/migrations/nope/abort")).status_code == 404

    # A's copy is gone, B's runs from the restored count and keeps going.
    assert a.workloads.status(WID).state == "stopped" and not psutil.pid_exists(pid_a)
    assert b.workloads.status(WID).state == "running"
    handed_over = saved_count(b)
    await until(lambda: any("resumed count=" in line for line in b.workloads.status(WID).logTail))
    line = next(x for x in b.workloads.status(WID).logTail if "resumed count=" in x)
    match = re.search(r"resumed count=(\d+) runs=2", line)
    assert match is not None and int(match[1]) >= 5
    await until(lambda: saved_count(b) > handed_over + 3)
    assert b.authority.may_run(WID) and not a.authority.may_run(WID)
    await b.workloads.terminate(WID)

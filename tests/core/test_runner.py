"""Workload runner against a live agent (uvicorn in the test loop) running tests/fixtures/counter_job."""

from __future__ import annotations

import asyncio
import os
import re
import socket
import subprocess
import sys
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import httpx
import psutil
import pytest
import uvicorn
from teleport_sdk.unit import decode_state, unpack_unit

from teleport.core import Context, Settings, build_context, create_app

REPO = Path(__file__).resolve().parents[2]
COUNTER_JOB = REPO / "tests" / "fixtures" / "counter_job"
WID = "counter-job"
CKPTS = {"config", "counter", "history", "stats", "journal", "meta"}


class Live:
    def __init__(self, ctx: Context, url: str) -> None:
        self.ctx = ctx
        self.url = url


@pytest.fixture
async def live(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Live]:
    monkeypatch.setenv("COUNTER_STEP_S", "0.05")
    monkeypatch.setenv("COUNTER_TARGET", "100000")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    app = create_app(Settings(home=tmp_path / "home", port=port, uiDist=tmp_path / "no-ui"))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    task = asyncio.create_task(server.serve())
    while not server.started:  # noqa: ASYNC110 - uvicorn exposes a flag, not an event
        await asyncio.sleep(0.02)
    try:
        yield Live(app.state.ctx, f"http://127.0.0.1:{port}")
    finally:
        server.should_exit = True
        await task


async def wait_for(cond: Callable[[], bool], timeout: float = 20.0, what: str = "condition") -> None:
    deadline = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out waiting for {what}")
        await asyncio.sleep(0.05)


def saved_count(ctx: Context) -> int:
    data = ctx.checkpoints.read(WID, "counter")
    if data is None:
        return -1
    state = decode_state(*unpack_unit(data))
    assert isinstance(state, dict)
    return int(state["count"])


async def launch(live: Live) -> None:
    async with httpx.AsyncClient(base_url=live.url) as http:
        res = await http.post("/api/workloads/start", json={"manifestPath": str(COUNTER_JOB)})
        assert res.status_code == 200, res.text
        assert [w["id"] for w in (await http.get("/api/workloads")).json()] == [WID]
        runs = (await http.get("/api/workloads/runs")).json()
        assert runs[0]["state"] == "running"


async def test_start_pause_resume_checkpoint_terminate(live: Live) -> None:
    ctx = live.ctx
    await launch(live)
    await wait_for(lambda: saved_count(ctx) >= 3, what="first counts")

    assert ctx.workloads.pause(WID).state == "paused"
    await asyncio.sleep(0.3)
    frozen = saved_count(ctx)
    await asyncio.sleep(0.6)
    assert saved_count(ctx) == frozen, "count advanced while paused"

    assert ctx.workloads.resume(WID).state == "running"
    await wait_for(lambda: saved_count(ctx) > frozen + 2, what="counting after resume")

    records = await ctx.workloads.request_checkpoint(WID)
    assert {r.id for r in records} == CKPTS
    assert all(ctx.checkpoints.verify(WID, r.id) for r in records)

    final = await ctx.workloads.terminate(WID, grace=5)
    assert final.state == "stopped" and final.exitCode == 0  # cooperative stop via should_stop()
    assert any(line.startswith("done count=") for line in final.logTail)


async def test_killed_job_resumes_from_checkpoint(live: Live) -> None:
    ctx = live.ctx
    await launch(live)
    await wait_for(lambda: saved_count(ctx) >= 8, what="counts before kill")
    await ctx.workloads.request_checkpoint(WID)
    saved = saved_count(ctx)

    pid = ctx.workloads.status(WID).pid
    assert pid is not None
    psutil.Process(pid).kill()  # crash: no chance to save anything else
    await wait_for(lambda: ctx.workloads.status(WID).state == "exited", what="exit after kill")

    run = await ctx.workloads.start(WID)
    assert set(run.restored) == CKPTS
    await wait_for(
        lambda: any("resumed count=" in line for line in ctx.workloads.status(WID).logTail),
        what="resume line",
    )
    line = next(x for x in ctx.workloads.status(WID).logTail if "resumed count=" in x)
    match = re.search(r"resumed count=(\d+) runs=(\d+)", line)
    assert match is not None
    resumed, runs = int(match[1]), int(match[2])
    assert resumed >= saved and runs == 2
    journal = (ctx.workloads.workdir(WID) / "out" / "journal.txt").read_text().split()
    assert int(journal[-1]) >= saved - 1  # journal file restored in place

    await wait_for(lambda: saved_count(ctx) > resumed, what="counting after resume")
    assert (await ctx.workloads.terminate(WID)).state == "stopped"


async def test_sdk_api_requires_run_token(live: Live) -> None:
    await launch(live)
    async with httpx.AsyncClient(base_url=live.url) as http:
        base = f"/api/sdk/workloads/{WID}"
        assert (await http.get(f"{base}/control")).status_code == 401
        bad = {"Authorization": "Bearer nope"}
        assert (await http.post(f"{base}/checkpoints/counter", content=b"x", headers=bad)).status_code == 401
    await live.ctx.workloads.terminate(WID)


def test_counter_job_runs_standalone(tmp_path: Path) -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("TELEPORT_")}
    env.update(COUNTER_TARGET="3", COUNTER_STEP_S="0", PYTHONPATH=str(REPO / "sdk"))
    cmd = [sys.executable, str(COUNTER_JOB / "job.py")]
    first = subprocess.run(cmd, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    assert first.returncode == 0, first.stderr
    assert "fresh start" in first.stdout and "done count=3" in first.stdout
    assert (tmp_path / ".teleport-local" / "checkpoints" / "counter.tar.gz").exists()

    env["COUNTER_TARGET"] = "999"  # ignored: config comes back from the checkpoint
    second = subprocess.run(cmd, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    assert "resumed count=3 runs=2" in second.stdout and "done count=3" in second.stdout


async def test_restarted_agent_knows_its_workloads_and_kills_orphans(live: Live) -> None:
    ctx = live.ctx
    await launch(live)
    await wait_for(lambda: saved_count(ctx) >= 2, what="first counts")
    pid = ctx.workloads.status(WID).pid
    assert pid is not None

    # A second agent on the same TELEPORT_HOME, as after a crash of the first one.
    restarted = build_context(ctx.settings)
    assert [m.id for m in restarted.workloads.list()] == [WID]  # registry survived
    await restarted.workloads.startup()
    assert restarted.workloads.interrupted() == {WID}
    await wait_for(lambda: not psutil.pid_exists(pid), what="the orphaned job to be killed")

"""Transfer benchmark over the real peer link (P2 transport + AES-GCM session), two agents in one
process on loopback, a fake workload with one large checkpoint.

    node scripts/py.mjs scripts/bench_transfer.py --mb 20 --chunks 64,128,256,512 --windows 4,8,16

Prints throughput and the initial transfer time per setting. Loopback has no RTT, so on a real
link larger windows matter more; see docs/MIGRATION.md for the chosen defaults.
"""

from __future__ import annotations

import argparse
import asyncio
import socket
import sys
import tempfile
from pathlib import Path
from typing import cast

import httpx
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "agent"), str(ROOT / "sdk")]

from teleport.core import Context, Settings, create_app  # noqa: E402
from teleport.migration import MigrationManager  # noqa: E402
from tests.migration.conftest import make_manifest  # noqa: E402
from tests.migration.mocks import FakeWorkloadHost, MockFeasibility, World  # noqa: E402


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


async def run_once(tmp: Path, blob_mb: float, chunk_kb: int, window: int) -> tuple[float, float, float, str]:
    world = World()
    servers: list[uvicorn.Server] = []
    ctxs: list[Context] = []
    for name in ("a", "b"):
        port = free_port()
        app = create_app(Settings(home=tmp / name, port=port, uiDist=tmp / "x"))
        ctx: Context = app.state.ctx
        ctx.register("workloads", FakeWorkloadHost(ctx, world))
        ctx.register("feasibility", MockFeasibility())
        manager = cast(MigrationManager, ctx.migration)
        manager.timeouts.window = window
        ctx.prefs = ctx.prefs.model_copy(update={"chunkSizeKb": chunk_kb})
        servers.append(uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")))
        ctxs.append(ctx)
    tasks = [asyncio.create_task(srv.serve()) for srv in servers]
    while not all(srv.started for srv in servers):  # noqa: ASYNC110
        await asyncio.sleep(0.02)
    a, b = ctxs
    try:
        async with httpx.AsyncClient(timeout=30) as http:
            url_b = f"127.0.0.1:{b.settings.port}"
            pin = (await http.get(f"http://{url_b}/api/pair")).json()["pin"]
            res = await http.post(
                f"http://127.0.0.1:{a.settings.port}/api/pair", json={"addr": url_b, "pin": pin}
            )
            res.raise_for_status()
        host = cast(FakeWorkloadHost, a.workloads)
        manifest = make_manifest(6)
        src = tmp / "src"
        src.mkdir(exist_ok=True)
        (src / "job.py").write_text("print('bench')\n")
        host.register(manifest, src)
        host.blobs = {"c1": int(blob_mb * 2**20)}
        await a.authority.claim(manifest.id, a.device_id)
        await host.start(manifest.id, restore=False)
        await host.request_checkpoint(manifest.id)
        manager = cast(MigrationManager, a.migration)
        started = await manager.start(manifest.id, b.device_id, "user_command")
        st = await manager.wait(started.id, timeout=300)
        assert st.phase == "COMPLETED", st.error
        m = st.metrics
        assert m is not None
        initial = sum(c.transferMs for c in m.checkpoints if c.stage == "initial")
        c = m.cutover
        split = (
            f"fence {c.fenceMs:.0f} + delta {c.deltaMs:.0f} ({c.deltaBytes} B) + start {c.startMs:.0f}"
            if c
            else ""
        )
        return m.throughputMbps, initial, m.interruptionMs or 0.0, split
    finally:
        for srv in servers:
            srv.should_exit = True
        await asyncio.gather(*tasks)


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--mb", type=float, default=20)
    p.add_argument("--chunks", default="64,128,256,512")
    p.add_argument("--windows", default="4,8,16")
    args = p.parse_args()
    print(f"{'chunk KB':>8} {'window':>6} {'Mbps':>8} {'transfer ms':>12} {'interruption ms':>16}")
    for chunk in [int(x) for x in args.chunks.split(",")]:
        for window in [int(x) for x in args.windows.split(",")]:
            with tempfile.TemporaryDirectory() as tmp:
                mbps, ms, interruption, split = await run_once(Path(tmp), args.mb, chunk, window)
            print(
                f"{chunk:>8} {window:>6} {mbps:>8.1f} {ms:>12.0f} {interruption:>16.0f}   {split}", flush=True
            )


if __name__ == "__main__":
    asyncio.run(main())

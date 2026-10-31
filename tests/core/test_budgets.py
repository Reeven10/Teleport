"""Brief budgets that do not need two agents: feasibility result < 500 ms (matrix row F5)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

import teleport.feasibility
from contract.contract import LinkQuality
from teleport.core import Settings, build_context
from teleport.core.manifest import load_manifest

COUNTER_JOB = Path(__file__).resolve().parents[1] / "fixtures" / "counter_job"


@pytest.mark.skipif(not hasattr(teleport.feasibility, "FeasibilityEngineImpl"), reason="needs P3's engine")
async def test_f5_feasibility_result_within_500ms(tmp_path: Path) -> None:
    source_ctx = build_context(Settings(home=tmp_path / "a", simProfile="default"))
    target = build_context(Settings(home=tmp_path / "b", simProfile="arm64-lowspec")).devices.local_info()
    manifest, _ = load_manifest(COUNTER_JOB)
    source = source_ctx.devices.local_info()
    link = LinkQuality(peerId=target.id, link="wifi", rttMs=8, mbps=150, lossPct=0.1, ts=time.time())

    timings = []
    for _ in range(5):
        started = time.perf_counter()
        result = await source_ctx.feasibility.evaluate(manifest, source, target, link)
        timings.append(time.perf_counter() - started)
    assert result.decision == "MIGRATE" and result.reasons
    assert max(timings) < 0.5, f"slowest evaluate took {max(timings) * 1000:.0f} ms"

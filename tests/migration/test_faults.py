"""Failure injection: every fault ends in COMPLETED or ROLLED_BACK, with a short human-readable
reason, and never with two running copies (tests/migration/mocks.py: World.max_running)."""

from __future__ import annotations

import asyncio
import errno
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from contract.contract import MigrationStatus, MigrationStatusEvent
from teleport.migration.manager import TERMINAL
from tests.migration.conftest import Pair, PairFactory, Side

PHASES = ["CONNECTING", "EVALUATING", "TRANSFERRING", "VALIDATING", "FENCING", "STARTING_TARGET"]


async def until(cond: Callable[[], Any], timeout: float = 10, what: str = "condition") -> Any:
    deadline = time.monotonic() + timeout
    while not (value := cond()):
        assert time.monotonic() < deadline, f"timed out waiting for {what}"
        await asyncio.sleep(0.02)
    return value


async def settled(side: Side, mid: str, timeout: float = 15) -> MigrationStatus:
    def done() -> MigrationStatus | None:
        st = side.manager.status(mid)
        return st if st and st.phase in TERMINAL else None

    result: MigrationStatus = await until(done, timeout, f"{mid} to settle")
    return result


def assert_clear_outcome(p: Pair, st: MigrationStatus) -> None:
    """COMPLETED, or ROLLED_BACK with a short sentence for the dashboard; one copy at most."""
    assert st.phase in ("COMPLETED", "ROLLED_BACK"), (st.phase, st.error)
    if st.phase == "ROLLED_BACK":
        msg = st.error or ""
        assert 10 < len(msg) <= 160, msg
        assert msg[0].isupper() and msg.rstrip().endswith((".", ")")), msg
        for noise in ("Traceback", "Errno", "Exception", "None", "dev-"):
            assert noise not in msg, msg
        assert any(r.code == "rollback" and r.text for r in st.reasons)
    assert all(n <= 1 for n in p.world.max_running.values()), p.world.max_running


def on_phase(side: Side, phase: str, action: Callable[[], Any]) -> asyncio.Event:
    fired = asyncio.Event()

    async def hook(e: MigrationStatusEvent) -> None:
        if not fired.is_set() and e.status.phase == phase and e.status.sourceId == side.id:
            fired.set()
            result = action()
            if asyncio.iscoroutine(result):
                await result

    side.ctx.bus.subscribe(MigrationStatusEvent, hook)
    return fired


# ---------------------------------------------------------------- link killed in every phase


@pytest.mark.parametrize("phase", PHASES)
async def test_link_killed_in_every_phase(make_pair: PairFactory, phase: str) -> None:
    p = await make_pair(6)
    await p.a.host.request_checkpoint(p.wid)
    on_phase(p.a, phase, p.a.link.cut)
    mid = (await p.a.manager.start(p.wid, p.b.id, "user_command")).id
    if phase == "STARTING_TARGET":
        # mig.start may be out: the source waits for the target's lease instead of guessing.
        await until(lambda: any(r.code == "recovery.wait" for r in p.a.manager.status(mid).reasons),  # type: ignore[union-attr]
                    what="source waiting")  # fmt: skip
        assert p.world.running.get(p.wid, set()) == set()  # A fenced, B never started
        p.a.link.heal()
    st = await settled(p.a, mid)
    assert st.phase == "ROLLED_BACK"
    assert "link" in (st.error or "").lower() or "never took authority" in (st.error or "")
    await until(lambda: p.world.running.get(p.wid) == {p.a.id}, what="A running again")
    assert_clear_outcome(p, st)


async def test_link_killed_right_after_target_started(make_pair: PairFactory) -> None:
    p = await make_pair(6)

    async def cut_when_target_done(e: MigrationStatusEvent) -> None:
        if e.status.phase == "COMPLETED" and e.status.targetId == p.b.id and not p.a.link.is_cut:
            p.a.link.cut()  # mig.started ok is lost on the way back

    p.b.ctx.bus.subscribe(MigrationStatusEvent, cut_when_target_done)
    mid = (await p.a.manager.start(p.wid, p.b.id, "user_command")).id
    await until(lambda: p.a.link.is_cut, what="the cut")
    await asyncio.sleep(0.3)
    assert p.world.running.get(p.wid) == {p.b.id}  # A stays fenced: no second copy
    p.a.link.heal()
    st = await settled(p.a, mid)
    assert st.phase == "COMPLETED"  # the target's lease proves it took over
    assert_clear_outcome(p, st)


# ---------------------------------------------------------------- data faults


async def test_corrupt_chunk_once_is_detected_and_resent(make_pair: PairFactory) -> None:
    p = await make_pair(6)
    corrupted: list[str] = []

    def once(m: Any) -> bool:
        if m.checkpointId == "c2" and not corrupted:
            corrupted.append(m.checkpointId)
            return True
        return False

    p.a.link.faults.corrupt = once
    st = await p.migrate()
    assert st.phase == "COMPLETED" and st.metrics and any(m.retries for m in st.metrics.checkpoints)
    assert_clear_outcome(p, st)


async def test_persistently_corrupt_chunk_rolls_back(make_pair: PairFactory) -> None:
    p = await make_pair(6)
    p.a.link.faults.corrupt = lambda m: m.checkpointId == "c3"
    st = await p.migrate()
    assert st.phase == "ROLLED_BACK" and "Checkpoint c3 could not be sent intact" in (st.error or "")
    assert_clear_outcome(p, st)


async def test_slow_link_completes_and_reports_a_small_freeze(make_pair: PairFactory) -> None:
    p = await make_pair(6)
    p.a.host.blobs = {"c4": 300_000}
    p.a.ctx.prefs = p.a.ctx.prefs.model_copy(update={"chunkSizeKb": 32})
    p.a.link.faults.delay = 0.005  # every message waits 5 ms
    await p.a.host.request_checkpoint(p.wid)
    st = await p.migrate()
    assert st.phase == "COMPLETED", st.error
    m = st.metrics
    assert m is not None and m.cutover is not None and m.interruptionMs is not None
    assert m.cutover.deltaBytes < 2_000  # only the counter changed in the freeze window
    assert m.interruptionMs < m.durationMs / 2
    assert_clear_outcome(p, st)


# ---------------------------------------------------------------- target faults


async def test_target_disk_too_small_is_refused_up_front(
    make_pair: PairFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    p = await make_pair(6)
    monkeypatch.setattr(p.b.manager, "_disk_free", lambda path: 1024)
    st = await p.migrate()
    assert st.phase == "ROLLED_BACK" and "Not enough disk space on the target" in (st.error or "")
    assert p.world.started_on == [(p.a.id, p.wid)]
    assert_clear_outcome(p, st)


async def test_target_disk_full_mid_transfer_aborts(
    make_pair: PairFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    p = await make_pair(6)

    def full_disk(part: Any, path: Path) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(p.b.manager, "_finalize_unit", full_disk)
    st = await p.migrate()
    assert st.phase == "ROLLED_BACK" and "ran out of disk space" in (st.error or "")
    target_view = await settled(p.b, st.id)
    assert target_view.phase == "ROLLED_BACK"
    assert not (p.b.host.store.workload_dir(p.wid) / "staging" / st.id).exists()
    assert_clear_outcome(p, st)


async def test_target_killed_while_starting(make_pair: PairFactory) -> None:
    p = await make_pair(6)

    async def crash_target(e: MigrationStatusEvent) -> None:
        if e.status.phase == "STARTING_TARGET" and e.status.targetId == p.b.id and not p.b.host.dead:
            p.crash(p.b)

    p.b.ctx.bus.subscribe(MigrationStatusEvent, crash_target)
    mid = (await p.a.manager.start(p.wid, p.b.id, "user_command")).id
    await until(lambda: p.b.host.dead, what="target crash")
    b = await p.restart(p.b)  # the target comes back; both sides compare leases
    st = await settled(p.a, mid)
    assert st.phase in ("COMPLETED", "ROLLED_BACK")
    holder = p.a.ctx.authority.get(p.wid).holder
    expected = {b.id} if st.phase == "COMPLETED" else {p.a.id}
    await until(lambda: p.world.running.get(p.wid) == expected, what=f"exactly one copy on {expected}")
    assert holder in expected or st.phase == "COMPLETED"
    assert_clear_outcome(p, st)


# ---------------------------------------------------------------- source faults


async def test_source_killed_during_fence(make_pair: PairFactory) -> None:
    p = await make_pair(6)
    await p.a.host.request_checkpoint(p.wid)
    fired = on_phase(p.a, "FENCING", lambda: None)

    async def crash_after_fence(e: Any) -> None:
        if fired.is_set() and getattr(e, "t", "") == "authority.change" and not p.a.host.dead:
            p.crash(p.a)

    p.a.ctx.bus.subscribe_all(crash_after_fence)
    mid = (await p.a.manager.start(p.wid, p.b.id, "user_command")).id
    await until(lambda: p.a.host.dead, what="source crash during fence")
    a = await p.restart(p.a)
    st = await settled(a, mid)
    assert st.phase == "ROLLED_BACK" and "Agent restarted during FENCING" in " ".join(
        [st.error or "", *(r.text for r in st.reasons)]
    )
    await until(lambda: p.world.running.get(p.wid) == {a.id}, what="A resumed")
    assert_clear_outcome(p, st)


async def test_workload_exits_during_transfer(make_pair: PairFactory) -> None:
    p = await make_pair(6)
    p.a.link.faults.delay = 0.02
    on_phase(p.a, "TRANSFERRING", lambda: p.a.host.exit(p.wid, 3))
    st = await p.migrate()
    assert st.phase == "ROLLED_BACK"
    assert st.error == "The workload stopped during the transfer (exit code 3); nothing to hand over."
    assert p.world.started_on == [(p.a.id, p.wid)]  # never started on B, not restarted on A
    assert p.world.running.get(p.wid, set()) == set()
    assert_clear_outcome(p, st)


async def test_unreachable_target_is_a_clear_rollback(make_pair: PairFactory) -> None:
    p = await make_pair(6)
    p.a.link.cut()
    st = await p.migrate()
    assert st.phase == "ROLLED_BACK" and (st.error or "").startswith("Lost the link to the target")
    assert p.world.running.get(p.wid) == {p.a.id}
    assert_clear_outcome(p, st)

"""Continuity: restart mid-migration, split-brain guard, delta re-send, pre-copy, repeated
migrations and metrics. Every test ends with at most one running copy; only the split-brain test
deliberately starts with two (that is the fault it injects) and checks the guard leaves one."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from contract.contract import (
    AuthorityChangeEvent,
    AuthorityConflict,
    AuthorityConflictEvent,
    MigrationStatus,
    MigrationStatusEvent,
    MigStart,
)
from teleport.authority import resolve
from teleport.core import Settings, create_app
from teleport.migration.manager import TERMINAL
from tests.migration.conftest import Pair, PairFactory, Side

PRE_START_PHASES = ["CONNECTING", "EVALUATING", "TRANSFERRING", "VALIDATING", "FENCING", "STARTING_TARGET"]


async def until(cond: Callable[[], Any], timeout: float = 10, what: str = "condition") -> Any:
    deadline = time.monotonic() + timeout
    while not (value := cond()):
        assert time.monotonic() < deadline, f"timed out waiting for {what}"
        await asyncio.sleep(0.02)
    return value


def single_copy(p: Pair) -> None:
    assert all(n <= 1 for n in p.world.max_running.values()), p.world.max_running


def running_on(p: Pair) -> set[str]:
    return set(p.world.running.get(p.wid, set()))


def status_event(
    phase: str, *, source: str | None = None, target: str | None = None
) -> Callable[[Any], bool]:
    def match(e: Any) -> bool:
        if not isinstance(e, MigrationStatusEvent) or e.status.phase != phase:
            return False
        return (source is None or e.status.sourceId == source) and (
            target is None or e.status.targetId == target
        )

    return match


def granted_to(device_id: str) -> Callable[[Any], bool]:
    return lambda e: (
        isinstance(e, AuthorityChangeEvent)
        and (e.authority.holder, e.authority.state)
        == (
            device_id,
            "TARGET",
        )
    )


def waiting(side: Side, mid: str) -> Callable[[], bool]:
    def check() -> bool:
        st = side.manager.status(mid)
        return st is not None and any(r.code == "recovery.wait" for r in st.reasons)

    return check


def crash_when(p: Pair, bus_side: Side, victim: Side, match: Callable[[Any], bool]) -> asyncio.Event:
    """Crash `victim` the moment `bus_side` publishes an event matching `match`."""
    fired = asyncio.Event()

    async def hook(event: Any) -> None:
        if not fired.is_set() and match(event):
            fired.set()
            p.crash(victim)

    bus_side.ctx.bus.subscribe_all(hook)
    return fired


async def finished(side: Side, mid: str, timeout: float = 10) -> MigrationStatus:
    def done() -> MigrationStatus | None:
        st = side.manager.status(mid)
        return st if st and st.phase in TERMINAL else None

    result: MigrationStatus = await until(done, timeout, f"{mid} to settle on {side.id}")
    return result


# ---------------------------------------------------------------- restart mid-migration


@pytest.mark.parametrize("phase", PRE_START_PHASES)
async def test_source_restart_before_target_has_authority_resumes_source(
    make_pair: PairFactory, phase: str
) -> None:
    p = await make_pair(6)
    await p.a.host.request_checkpoint(p.wid)  # the job's own periodic checkpoint
    fired = crash_when(p, p.a, p.a, status_event(phase, source=p.a.id))
    st = await p.a.manager.start(p.wid, p.b.id, "user_command")
    await asyncio.wait_for(fired.wait(), 10)
    await asyncio.sleep(0.2)  # the target notices the lost link
    assert (p.b.host.store.workload_dir(p.wid) / "staging" / st.id).exists() is False

    a = await p.restart(p.a)
    result = await finished(a, st.id)

    assert result.phase == "ROLLED_BACK", result.reasons
    restart_noted = [result.error or "", *(r.text for r in result.reasons)]
    assert any(f"Agent restarted during {phase}" in text for text in restart_noted), restart_noted
    lease = a.ctx.authority.get(p.wid)
    assert (lease.holder, lease.state) == (a.id, "SOURCE")
    await until(lambda: running_on(p) == {a.id}, what="A running again")
    assert a.host.restored_count[p.wid] == 41  # resumed from its checkpoints
    assert not p.b.ctx.authority.may_run(p.wid)
    single_copy(p)


async def test_source_restart_right_after_fence_unfences(make_pair: PairFactory) -> None:
    p = await make_pair(6)
    fired = crash_when(
        p, p.a, p.a, lambda e: isinstance(e, AuthorityChangeEvent) and e.authority.state == "FENCED"
    )
    st = await p.a.manager.start(p.wid, p.b.id, "user_command")
    await asyncio.wait_for(fired.wait(), 10)

    a = await p.restart(p.a)
    result = await finished(a, st.id)
    assert result.phase == "ROLLED_BACK"
    lease = a.ctx.authority.get(p.wid)
    assert (lease.holder, lease.state, lease.epoch) == (a.id, "SOURCE", 2)  # fenced 1, rolled back 2
    await until(lambda: running_on(p) == {a.id}, what="A running again")
    single_copy(p)


async def test_source_restart_after_target_started_stays_stopped(make_pair: PairFactory) -> None:
    p = await make_pair(6)
    # The target starts and replies, but the source dies before it hears mig.started ok.
    fired = crash_when(p, p.b, p.a, status_event("COMPLETED", target=p.b.id))
    st = await p.a.manager.start(p.wid, p.b.id, "user_command")
    await asyncio.wait_for(fired.wait(), 10)
    assert running_on(p) == {p.b.id}

    a = await p.restart(p.a)
    result = await finished(a, st.id)
    assert result.phase == "COMPLETED", result.reasons
    assert any(r.code == "recovery.moved" for r in result.reasons)
    lease = a.ctx.authority.get(p.wid)
    assert (lease.holder, lease.state, lease.epoch) == (p.b.id, "TARGET", 1)
    await asyncio.sleep(0.3)
    assert running_on(p) == {p.b.id} and a.host.states[p.wid] != "running"
    single_copy(p)


async def test_source_restart_after_completion_does_not_relaunch(make_pair: PairFactory) -> None:
    p = await make_pair(6)
    st = await p.migrate()
    assert st.phase == "COMPLETED"
    p.crash(p.a)
    a = await p.restart(p.a)
    await asyncio.sleep(0.3)
    assert a.manager.status(st.id).phase == "COMPLETED"  # type: ignore[union-attr]  # from the journal
    assert running_on(p) == {p.b.id}
    single_copy(p)


async def test_target_restart_mid_transfer_discards_staging(make_pair: PairFactory) -> None:
    p = await make_pair(6)
    p.a.link.faults.delay = 0.05
    fired = crash_when(
        p, p.b, p.b, lambda e: isinstance(e, MigrationStatusEvent) and e.status.phase == "TRANSFERRING"
    )
    mid = (await p.a.manager.start(p.wid, p.b.id, "user_command")).id
    await asyncio.wait_for(fired.wait(), 10)
    st = await p.a.manager.wait(mid, timeout=10)
    assert st.phase == "ROLLED_BACK"

    b = await p.restart(p.b)
    result = await finished(b, mid)
    assert result.phase == "ROLLED_BACK" and "Agent restarted" in (result.error or "")
    assert not (b.host.store.workload_dir(p.wid) / "staging" / mid).exists()
    assert running_on(p) == {p.a.id}
    single_copy(p)


async def test_target_restart_after_grant_waits_for_source_then_starts(make_pair: PairFactory) -> None:
    p = await make_pair(6)
    # The target dies right after taking authority, before starting or answering mig.start.
    fired = crash_when(p, p.b, p.b, granted_to(p.b.id))
    mid = (await p.a.manager.start(p.wid, p.b.id, "user_command")).id
    await asyncio.wait_for(fired.wait(), 10)
    await until(waiting(p.a, mid), what="source waiting instead of resuming")
    assert p.a.ctx.authority.get(p.wid).state == "FENCED" and running_on(p) == set()

    b = await p.restart(p.b)
    st = await finished(p.a, mid)
    assert st.phase == "COMPLETED"
    await until(lambda: running_on(p) == {b.id}, what="B started from the committed checkpoints")
    assert b.host.restored_count[p.wid] == 41
    target_view = await finished(b, mid)
    assert target_view.phase == "COMPLETED"
    single_copy(p)


async def test_target_restart_after_starting_keeps_running(make_pair: PairFactory) -> None:
    p = await make_pair(6)
    fired = crash_when(p, p.b, p.b, status_event("COMPLETED", target=p.b.id))
    mid = (await p.a.manager.start(p.wid, p.b.id, "user_command")).id
    await asyncio.wait_for(fired.wait(), 10)

    b = await p.restart(p.b)
    st = await finished(p.a, mid)
    assert st.phase == "COMPLETED"
    await until(lambda: running_on(p) == {b.id}, what="B relaunched after its restart")
    assert p.a.host.states[p.wid] != "running"
    single_copy(p)


async def test_link_lost_after_start_waits_instead_of_rolling_back(make_pair: PairFactory) -> None:
    p = await make_pair(6)
    p.b.host.start_delay = 0.3
    # Cut the link (no restart) once mig.start is out: the source cannot know if the target started.
    p.a.link.cut_after(1, kind=MigStart)
    mid = (await p.a.manager.start(p.wid, p.b.id, "user_command")).id
    await until(waiting(p.a, mid), what="source waiting")
    assert p.a.manager.status(mid).phase == "STARTING_TARGET"  # type: ignore[union-attr]
    assert running_on(p) == set()  # A fenced, B never got mig.start
    p.a.link.heal()  # same agents, link back
    st = await finished(p.a, mid)
    assert st.phase == "ROLLED_BACK" and "never took authority" in (st.error or "")
    await until(lambda: running_on(p) == {p.a.id}, what="A resumed")
    single_copy(p)


# ---------------------------------------------------------------- split-brain guard


def test_resolve_rules_are_symmetric() -> None:
    from contract.contract import Authority

    def lease(holder: str, epoch: int, state: str = "SOURCE") -> Authority:
        return Authority(workloadId="w", holder=holder, epoch=epoch, state=state)  # type: ignore[arg-type]

    assert resolve(lease("a", 3), lease("b", 2), "a", "b") == "stop_remote"
    assert resolve(lease("b", 2), lease("a", 3), "b", "a") == "stop_local"
    # equal epochs: TARGET wins, then the smaller device id
    assert resolve(lease("a", 2), lease("b", 2, "TARGET"), "a", "b") == "stop_local"
    assert resolve(lease("a", 2), lease("b", 2), "a", "b") == "stop_remote"
    assert resolve(lease("b", 2), lease("a", 2), "b", "a") == "stop_local"
    # not a conflict: we do not run and the peer knows newer state
    assert resolve(lease("b", 1, "TARGET"), lease("c", 2, "TARGET"), "a", "b") == "learn"
    assert resolve(lease("a", 2, "FENCED"), lease("b", 2, "TARGET"), "a", "b") == "none"


async def test_split_brain_lower_epoch_stops_and_conflict_is_reported(make_pair: PairFactory) -> None:
    p = await make_pair(6, run_source=False)
    src = p.a.host.store.workload_dir("x").parent  # any folder works as source for the fake
    for side in (p.a, p.b):
        side.host.register(p.manifest, src)
    # Injected fault: during a partition both devices ended up holding the workload.
    p.a.link.cut()
    await p.a.ctx.authority.grant(p.wid, p.a.id, 3)
    await p.b.ctx.authority.grant(p.wid, p.b.id, 2)
    await p.a.host.start(p.wid, restore=False)
    await p.b.host.start(p.wid, restore=False)
    assert running_on(p) == {p.a.id, p.b.id}

    seen: dict[str, list[AuthorityConflict]] = {p.a.id: [], p.b.id: []}
    for side in (p.a, p.b):

        async def on_conflict(
            e: AuthorityConflictEvent, sink: list[AuthorityConflict] = seen[side.id]
        ) -> None:
            sink.append(e.conflict)

        side.ctx.bus.subscribe(AuthorityConflictEvent, on_conflict)

    p.a.link.heal()  # the partition ends: the next lease exchange finds the conflict
    await until(lambda: running_on(p) == {p.a.id}, what="the lower epoch to stop")
    await until(lambda: seen[p.a.id] and seen[p.b.id], what="conflict reported on both sides")
    for conflicts in seen.values():
        c = conflicts[0]
        assert (c.winner, c.stopped) == (p.a.id, p.b.id) and "stopped" in c.reason
    assert p.b.ctx.authority.get(p.wid).holder == p.a.id and not p.b.ctx.authority.may_run(p.wid)
    await asyncio.sleep(0.3)
    assert len(seen[p.a.id]) == 1  # reported once, not on every sync


# ---------------------------------------------------------------- delta, pre-copy, there and back


def transferred(st: MigrationStatus, stage: str = "initial") -> set[str]:
    assert st.metrics is not None
    return {m.id for m in st.metrics.checkpoints if m.stage == stage and not m.skipped}


def skipped(st: MigrationStatus) -> set[str]:
    assert st.metrics is not None
    return {m.id for m in st.metrics.checkpoints if m.skipped}


async def migrate(p: Pair, src: Side, dst: Side) -> MigrationStatus:
    started = await src.manager.start(p.wid, dst.id, "user_command")
    return await src.manager.wait(started.id, timeout=20)


async def test_migrate_there_and_back_twice_resends_only_changes(make_pair: PairFactory) -> None:
    p = await make_pair(6)
    first = await migrate(p, p.a, p.b)
    assert first.phase == "COMPLETED" and skipped(first) == set()
    epochs = [first.authority.epoch]
    expected = 41
    hops = [(p.b, p.a), (p.a, p.b), (p.b, p.a)]
    for src, dst in hops:
        src.host.tick(p.wid, 5)
        expected += 5
        st = await migrate(p, src, dst)
        assert st.phase == "COMPLETED", st.error
        # Only the counter changed since the last transfer; code and static units are reused.
        assert transferred(st) == {"counter"}, st.metrics
        assert skipped(st) == {"teleport.code", "c1", "c2", "c3", "c4", "c5"}
        assert st.metrics and st.metrics.bytesSkipped > 0 and st.bytesDone == st.bytesTotal
        assert dst.host.restored_count[p.wid] == expected
        epochs.append(st.authority.epoch)
        assert (st.authority.holder, dst.ctx.authority.get(p.wid).holder) == (dst.id, dst.id)
    assert epochs == [1, 2, 3, 4]  # the epoch only goes up
    assert running_on(p) == {p.a.id}
    single_copy(p)


async def test_precopy_leaves_only_a_small_final_delta(make_pair: PairFactory) -> None:
    p = await make_pair(6)
    p.a.host.blobs = {"c2": 200_000}
    await p.a.host.request_checkpoint(p.wid)
    pre = await p.a.manager.precopy(p.wid, p.b.id)
    assert {m.id for m in pre.checkpoints if not m.skipped} >= {"c2", "counter", "teleport.code"}
    assert p.a.ctx.authority.may_run(p.wid) and running_on(p) == {p.a.id}  # no authority change

    again = await p.a.manager.precopy(p.wid, p.b.id)
    assert {m.id for m in again.checkpoints if not m.skipped} == set() and again.bytesDone == 0

    p.a.host.tick(p.wid, 3)
    st = await p.migrate()
    assert st.phase == "COMPLETED"
    assert transferred(st) == {"counter"}  # the 200 KB unit was already there
    assert "c2" in skipped(st)
    assert st.bytesTotal < 2_000 and p.b.host.restored_count[p.wid] == 44
    assert p.a.manager.list()[-1].id == st.id  # pre-copies are not listed as migrations
    single_copy(p)


async def test_chunk_size_setting_and_metrics_fields(make_pair: PairFactory) -> None:
    p = await make_pair(6)
    p.a.host.blobs = {"c3": 100_000}
    p.a.ctx.prefs = p.a.ctx.prefs.model_copy(update={"chunkSizeKb": 16})
    st = await p.migrate()
    assert st.phase == "COMPLETED"

    m = p.a.manager.metrics(st.id)
    assert m is not None and m == st.metrics or m is not None
    assert m.migrationId == st.id and m.link == "cable" and m.chunkSize == 16 * 1024
    assert m.durationMs > 0 and m.interruptionMs is not None and m.interruptionMs > 0
    assert m.bytesDone == st.bytesDone > 100_000 and m.throughputMbps > 0
    big = next(c for c in m.checkpoints if c.id == "c3" and c.stage == "initial")
    assert big.chunks == 7 and big.transferMs > 0 and big.mbps > 0 and big.retries == 0  # 100 KB / 16 KB
    assert {c.id for c in m.checkpoints if c.stage == "initial"} >= {"teleport.code", "counter", "c1"}

    p.crash(p.a)
    a = await p.restart(p.a)
    persisted = a.manager.metrics(st.id)
    assert persisted is not None and persisted.checkpoints == m.checkpoints  # survives a restart
    single_copy(p)


def test_metrics_endpoint_and_settings_validation(tmp_path: Any) -> None:
    with TestClient(create_app(Settings(home=tmp_path, uiDist=tmp_path / "none"))) as client:
        assert client.get("/api/migrations/nope/metrics").status_code == 404
        assert client.put("/api/settings", json={"chunkSizeKb": 64}).json()["chunkSizeKb"] == 64
        assert client.put("/api/settings", json={"chunkSizeKb": 4096}).status_code == 422
        assert client.put("/api/settings", json={"precopyIntervalS": 30}).json()["precopyIntervalS"] == 30
        assert client.post("/api/workloads/nope/precopy", json={"targetId": "x"}).status_code == 404

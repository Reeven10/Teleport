"""Migration manager end to end over the in-memory peer link pair (tests/migration/mocks.py)."""

from __future__ import annotations

import asyncio

from contract.contract import MigChunk, MigFence, MigStart
from tests.migration.conftest import PairFactory

HAPPY = ["CONNECTING", "EVALUATING", "TRANSFERRING", "VALIDATING", "FENCING", "STARTING_TARGET", "COMPLETED"]


def assert_single_copy(p: object) -> None:
    world = p.world  # type: ignore[attr-defined]
    assert all(n <= 1 for n in world.max_running.values()), world.max_running


async def test_happy_path_six_checkpoints(make_pair: PairFactory) -> None:
    p = await make_pair(6)
    st = await p.migrate()

    assert st.phase == "COMPLETED", st.error
    assert p.a.phases == HAPPY
    user = [c for c in st.checkpoints if not c.id.startswith("teleport.")]
    assert len(user) == 6 and all(c.sent and c.validated for c in st.checkpoints)
    assert st.bytesDone == st.bytesTotal > 0
    assert st.interruptionMs is not None and st.interruptionMs < 3000
    assert st.decision == "MIGRATE" and p.a.feasibility.calls == 1

    # B runs from the restored state, A is gone, both agree B holds epoch 1.
    assert p.b.host.states[p.wid] == "running" and p.a.host.states[p.wid] == "stopped"
    assert p.b.host.restored_count[p.wid] == 41
    for side in (p.a, p.b):
        lease = side.ctx.authority.get(p.wid)
        assert (lease.holder, lease.epoch, lease.state) == (p.b.id, 1, "TARGET")
    assert p.b.ctx.authority.may_run(p.wid) and not p.a.ctx.authority.may_run(p.wid)
    a_hashes = {r.id: r.sha256 for r in p.a.host.store.records(p.wid)}
    assert {r.id: r.sha256 for r in p.b.host.store.records(p.wid)} == a_hashes
    assert (p.b.host.store.workload_dir(p.wid) / "code" / "job.py").exists()
    assert p.b.manager.status(st.id) is not None and p.b.phases[-1] == "COMPLETED"
    assert_single_copy(p)


async def test_five_of_ten_checkpoints_never_moves_authority(make_pair: PairFactory) -> None:
    p = await make_pair(10)
    late = {f"c{i}" for i in range(5, 10)}
    p.a.link.faults.drop = lambda m: isinstance(m, MigChunk) and m.checkpointId in late
    st = await p.migrate()

    assert st.phase == "ROLLED_BACK" and "failed after" in (st.error or "")
    sent_user = [c.id for c in st.checkpoints if c.sent and not c.id.startswith("teleport.")]
    assert len(sent_user) == 5
    assert not any(c.validated for c in st.checkpoints)
    assert p.world.started_on == [(p.a.id, p.wid)]  # B never started
    lease = p.a.ctx.authority.get(p.wid)
    assert (lease.holder, lease.state, lease.epoch) == (p.a.id, "SOURCE", 0)
    assert p.a.host.states[p.wid] == "running"
    assert not p.b.ctx.authority.may_run(p.wid)
    await asyncio.sleep(0.1)
    assert not (p.b.host.store.workload_dir(p.wid) / "staging" / st.id).exists()
    assert_single_copy(p)


async def test_corrupted_chunk_is_detected_and_resent(make_pair: PairFactory) -> None:
    p = await make_pair(6)
    corrupted: list[str] = []

    def once(m: MigChunk) -> bool:
        if m.checkpointId == "c2" and not corrupted:
            corrupted.append(m.checkpointId)
            return True
        return False

    p.a.link.faults.corrupt = once
    st = await p.migrate()
    assert st.phase == "COMPLETED", st.error
    resent = [m for m in p.a.link.sent if isinstance(m, MigChunk) and m.checkpointId == "c2"]
    assert len(resent) == 2  # rejected once by the target's SHA-256 check, then resent


async def test_persistently_corrupted_chunk_rolls_back(make_pair: PairFactory) -> None:
    p = await make_pair(6)
    p.a.link.faults.corrupt = lambda m: m.checkpointId == "c3"
    st = await p.migrate()
    assert st.phase == "ROLLED_BACK" and "c3" in (st.error or "")
    assert p.a.host.states[p.wid] == "running" and p.world.started_on == [(p.a.id, p.wid)]


async def test_target_start_failure_rolls_back_and_source_resumes(make_pair: PairFactory) -> None:
    p = await make_pair(6)
    p.b.host.fail_start = True
    st = await p.migrate()

    assert st.phase == "ROLLED_BACK" and "simulated start failure" in (st.error or "")
    assert "FENCING" in p.a.phases and p.a.phases[-2:] == ["ROLLING_BACK", "ROLLED_BACK"]
    assert p.a.host.states[p.wid] == "running"
    p.a.host.tick(p.wid)  # the source is live again
    lease = p.a.ctx.authority.get(p.wid)
    assert (lease.holder, lease.state, lease.epoch) == (p.a.id, "SOURCE", 2)  # fenced 1, rolled back 2
    b_lease = p.b.ctx.authority.get(p.wid)
    assert b_lease.holder is None and not p.b.ctx.authority.may_run(p.wid)
    assert_single_copy(p)


async def test_link_cut_mid_transfer(make_pair: PairFactory) -> None:
    p = await make_pair(6)
    p.a.link.cut_after(3)
    st = await p.migrate()

    assert st.phase == "ROLLED_BACK" and "link" in (st.error or "")
    assert p.a.host.states[p.wid] == "running"
    assert p.a.ctx.authority.get(p.wid).state == "SOURCE"
    await asyncio.sleep(0.1)
    b_status = p.b.manager.status(st.id)
    assert b_status is not None and b_status.phase == "ROLLED_BACK"
    assert not (p.b.host.store.workload_dir(p.wid) / "staging" / st.id).exists()
    assert_single_copy(p)


async def test_link_cut_after_fence_unfences_source(make_pair: PairFactory) -> None:
    p = await make_pair(6)
    p.a.link.cut_after(1, kind=MigFence)
    st = await p.migrate()
    assert st.phase == "ROLLED_BACK"
    lease = p.a.ctx.authority.get(p.wid)
    assert (lease.state, lease.epoch) == ("SOURCE", 2) and p.a.host.states[p.wid] == "running"
    assert_single_copy(p)


async def test_abort_during_transfer(make_pair: PairFactory) -> None:
    p = await make_pair(6)
    p.a.link.faults.delay = 0.1
    started = await p.a.manager.start(p.wid, p.b.id, "user_command")
    while (p.a.manager.status(started.id) or started).phase != "TRANSFERRING":
        await asyncio.sleep(0.01)
    st = await p.a.manager.abort(started.id)

    assert st.phase == "ROLLED_BACK" and st.error == "aborted by user"
    assert p.a.host.states[p.wid] == "running"
    assert p.a.ctx.authority.get(p.wid).state == "SOURCE"
    await asyncio.sleep(0.5)
    b_status = p.b.manager.status(started.id)
    assert b_status is not None and b_status.phase == "ROLLED_BACK"
    assert p.world.started_on == [(p.a.id, p.wid)]


async def test_abort_too_late_keeps_one_copy(make_pair: PairFactory) -> None:
    p = await make_pair(6)
    p.b.host.start_delay = 0.5
    started = await p.a.manager.start(p.wid, p.b.id, "user_command")
    while (p.a.manager.status(started.id) or started).phase != "STARTING_TARGET":
        await asyncio.sleep(0.01)
    st = await p.a.manager.abort(started.id)
    st = await p.a.manager.wait(started.id, timeout=10)

    assert st.phase == "COMPLETED"
    assert any(r.code == "abort.late" for r in st.reasons)
    assert p.b.host.states[p.wid] == "running" and p.a.host.states[p.wid] == "stopped"
    assert_single_copy(p)


async def test_stale_epoch_start_is_rejected(make_pair: PairFactory) -> None:
    p = await make_pair(6)
    real_send = p.a.link.send

    async def send_stale_start(device_id: str, msg: object) -> None:
        if isinstance(msg, MigStart):
            msg = msg.model_copy(update={"epoch": msg.epoch - 1})
        await real_send(device_id, msg)  # type: ignore[arg-type]

    p.a.link.send = send_stale_start  # type: ignore[method-assign]
    st = await p.migrate()
    assert st.phase == "ROLLED_BACK" and "stale epoch" in (st.error or "")
    assert p.world.started_on == [(p.a.id, p.wid)]
    assert p.a.host.states[p.wid] == "running"


async def test_target_refuses_start_before_fence(make_pair: PairFactory) -> None:
    p = await make_pair(6)
    p.a.link.faults.drop = lambda m: isinstance(m, MigFence)
    st = await p.migrate()
    assert st.phase == "ROLLED_BACK" and "not fenced" in (st.error or "")
    assert p.world.started_on == [(p.a.id, p.wid)]


async def test_remote_access_decision(make_pair: PairFactory) -> None:
    p = await make_pair(6)
    p.a.feasibility.decision = "REMOTE_ACCESS"
    st = await p.migrate()
    assert st.phase == "REMOTE_ACCESS" and st.decision == "REMOTE_ACCESS"
    assert [s.viewerId for s in p.a.remote.sessions()] == [p.b.id]
    assert p.a.host.states[p.wid] == "running" and p.a.ctx.authority.may_run(p.wid)


async def test_stay_decision_ends_with_reasons(make_pair: PairFactory) -> None:
    p = await make_pair(6)
    p.a.feasibility.decision = "STAY"
    st = await p.migrate()
    assert st.phase == "FAILED" and st.decision == "STAY" and st.reasons
    assert "Mock decided STAY" in (st.error or "")
    assert not [m for m in p.a.link.sent if m.t.startswith("mig.")]
    assert (await p.a.ctx.history.list_decisions())[0].decision == "STAY"


async def test_migrate_back_and_forth(make_pair: PairFactory) -> None:
    p = await make_pair(6)
    assert (await p.migrate()).phase == "COMPLETED"
    p.b.host.tick(p.wid, 5)
    back = await p.b.manager.start(p.wid, p.a.id, "user_command")
    st = await p.b.manager.wait(back.id, timeout=20)
    assert st.phase == "COMPLETED", st.error
    assert p.a.host.restored_count[p.wid] == 46
    lease = p.a.ctx.authority.get(p.wid)
    assert (lease.holder, lease.epoch) == (p.a.id, 2)
    assert_single_copy(p)

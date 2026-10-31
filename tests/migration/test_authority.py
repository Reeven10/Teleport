from __future__ import annotations

from pathlib import Path

import pytest

from contract.contract import Authority, AuthorityChangeEvent
from teleport.authority import AuthorityError, AuthorityStore
from teleport.core import Context, Settings, build_context


async def test_handover_rollback_and_epochs(ctx: Context) -> None:
    auth, me = ctx.authority, ctx.device_id
    await auth.claim("w", me)
    assert auth.may_run("w")
    fenced = await auth.fence("w")
    assert (fenced.state, fenced.epoch) == ("FENCED", 1) and not auth.may_run("w")
    assert not auth.check_epoch("w", 0) and auth.check_epoch("w", 1)

    back = await auth.rollback("w")
    assert (back.state, back.epoch) == ("SOURCE", 2) and auth.may_run("w")  # a target at epoch 1 is stale

    await auth.fence("w")
    granted = await auth.grant("w", "other", 3)
    assert (granted.state, granted.holder, granted.epoch) == ("TARGET", "other", 3)
    assert not auth.may_run("w")
    with pytest.raises(AuthorityError):
        await auth.grant("w", "other", 2)
    with pytest.raises(AuthorityError):
        await auth.fence("w")  # not the holder
    with pytest.raises(AuthorityError):
        await auth.claim("w", me)  # another device holds it as TARGET


async def test_release_and_rollback_guards(ctx: Context) -> None:
    auth, me = ctx.authority, ctx.device_id
    await auth.grant("w", me, 4)
    assert auth.may_run("w")
    released = await auth.release("w")
    assert (released.holder, released.epoch) == (None, 4) and not auth.may_run("w")
    with pytest.raises(AuthorityError):
        await auth.rollback("w")  # not fenced


async def test_publishes_and_persists(tmp_path: Path) -> None:
    settings = Settings(home=tmp_path)
    ctx = build_context(settings)
    events: list[Authority] = []

    async def on_change(e: AuthorityChangeEvent) -> None:
        events.append(e.authority)

    ctx.bus.subscribe(AuthorityChangeEvent, on_change)
    await ctx.authority.claim("w", ctx.device_id)
    await ctx.authority.fence("w")
    assert [e.state for e in events] == ["SOURCE", "FENCED"]
    assert (tmp_path / "authority.json").exists()

    reloaded = AuthorityStore(build_context(settings))
    lease = reloaded.get("w")
    assert (lease.holder, lease.state, lease.epoch) == (ctx.device_id, "FENCED", 1)


async def test_lower_epoch_stops_after_reconnect(ctx: Context) -> None:
    auth = ctx.authority
    await auth.claim("w", ctx.device_id)
    remote = Authority(workloadId="w", holder="peer", epoch=3, state="TARGET")
    assert await auth.reconcile(remote) is True
    assert auth.get("w").holder == "peer"
    assert await auth.reconcile(remote) is False  # no longer ours

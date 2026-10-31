from __future__ import annotations

import pytest

from contract.contract import Authority
from teleport.authority import AuthorityError
from teleport.core import Context


async def test_handover_and_rollback(ctx: Context) -> None:
    auth = ctx.authority
    await auth.claim("w", ctx.device_id)
    fenced = await auth.fence("w")
    assert (fenced.state, fenced.epoch) == ("FENCED", 1)
    assert not auth.check_epoch("w", 0)
    assert (await auth.rollback("w")).state == "SOURCE"
    await auth.fence("w")
    granted = await auth.grant("w", "other", 2)
    assert (granted.state, granted.holder) == ("TARGET", "other")
    with pytest.raises(AuthorityError):
        await auth.grant("w", "other", 1)


async def test_lower_epoch_stops_after_reconnect(ctx: Context) -> None:
    auth = ctx.authority
    await auth.claim("w", ctx.device_id)
    remote = Authority(workloadId="w", holder="peer", epoch=3, state="TARGET")
    assert await auth.reconcile(remote) is True
    assert auth.get("w").holder == "peer"

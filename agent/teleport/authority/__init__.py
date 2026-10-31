"""Authority (P1): single active instance per workload via an epoch-numbered lease.

SOURCE -> FENCED (epoch + 1) -> TARGET; rollback FENCED -> SOURCE. Epochs never decrease.
"""

from __future__ import annotations

from contract.contract import Authority, AuthorityChangeEvent

from ..core.context import Context


class AuthorityError(ValueError):
    pass


class InMemoryAuthorityService:
    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self._leases: dict[str, Authority] = {}

    def get(self, workload_id: str) -> Authority:
        return self._leases.get(workload_id) or Authority(
            workloadId=workload_id, holder=None, epoch=0, state="SOURCE"
        )

    async def _set(self, lease: Authority) -> Authority:
        self._leases[lease.workloadId] = lease
        await self.ctx.bus.publish(AuthorityChangeEvent(authority=lease))
        return lease

    async def claim(self, workload_id: str, holder: str) -> Authority:
        cur = self.get(workload_id)
        return await self._set(cur.model_copy(update={"holder": holder, "state": "SOURCE"}))

    async def fence(self, workload_id: str) -> Authority:
        cur = self.get(workload_id)
        if cur.state != "SOURCE":
            raise AuthorityError(f"cannot fence {workload_id} in state {cur.state}")
        return await self._set(cur.model_copy(update={"state": "FENCED", "epoch": cur.epoch + 1}))

    async def grant(self, workload_id: str, holder: str, epoch: int) -> Authority:
        cur = self.get(workload_id)
        if epoch < cur.epoch:
            raise AuthorityError(f"stale epoch {epoch} < {cur.epoch} for {workload_id}")
        lease = Authority(workloadId=workload_id, holder=holder, epoch=epoch, state="TARGET")
        return await self._set(lease)

    async def rollback(self, workload_id: str) -> Authority:
        cur = self.get(workload_id)
        if cur.state != "FENCED":
            raise AuthorityError(f"cannot roll back {workload_id} in state {cur.state}")
        return await self._set(cur.model_copy(update={"state": "SOURCE"}))

    def check_epoch(self, workload_id: str, epoch: int) -> bool:
        return epoch >= self.get(workload_id).epoch

    async def reconcile(self, remote: Authority) -> bool:
        local = self.get(remote.workloadId)
        me = self.ctx.device_id
        if local.holder != me:
            return False
        newer = remote.epoch > local.epoch
        handed_over = remote.epoch == local.epoch and local.state == "FENCED" and remote.state == "TARGET"
        if newer or handed_over:
            await self._set(remote)
            return True
        return False

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass


def create_authority_service(ctx: Context) -> InMemoryAuthorityService:
    return InMemoryAuthorityService(ctx)

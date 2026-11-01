"""Authority (P1): single active instance per workload via an epoch-numbered lease.

Each workload has its own lease, and every transition a migration makes is stamped with that
migration's id: two migrations of different workloads never share or touch a lease, and a message
from an older migration of the same workload is refused (its epoch is behind, or its id does not match).

Handover SOURCE -> FENCED (epoch + 1) -> TARGET; rollback FENCED -> SOURCE (epoch + 1).
Epochs never decrease, so anything carrying an older epoch is stale and rejected.
Each device keeps its own view in TELEPORT_HOME/authority.json.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Literal

from contract.contract import Authority, AuthorityChangeEvent

from ..core.context import Context


class AuthorityError(ValueError):
    pass


Verdict = Literal["none", "learn", "stop_local", "stop_remote"]


def _runs(lease: Authority, device_id: str) -> bool:
    return lease.holder == device_id and lease.state in ("SOURCE", "TARGET")


def resolve(local: Authority, remote: Authority, me: str, peer: str) -> Verdict:
    """Compare this device's lease with a peer's for the same workload. Both sides compute the same
    answer: when both think they may run, the higher epoch wins; on equal epochs TARGET beats
    SOURCE, then the smaller device id wins. "learn": the peer knows a newer state, take it."""
    if _runs(local, me) and _runs(remote, peer):
        mine = (local.epoch, local.state == "TARGET", me < peer)
        theirs = (remote.epoch, remote.state == "TARGET", peer < me)
        return "stop_remote" if mine > theirs else "stop_local"
    if not _runs(local, me) and remote.epoch > local.epoch:
        return "learn"
    return "none"


class AuthorityStore:
    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self.path: Path = ctx.settings.home / "authority.json"
        self._lock = threading.Lock()
        self._leases: dict[str, Authority] = {}
        if self.path.exists():
            raw = json.loads(self.path.read_text("utf-8"))
            self._leases = {k: Authority.model_validate(v) for k, v in raw.items()}

    # ------------------------------------------------------------------ queries

    def get(self, workload_id: str) -> Authority:
        return self._leases.get(workload_id) or Authority(
            workloadId=workload_id, holder=None, epoch=0, state="SOURCE"
        )

    def leases(self) -> list[Authority]:
        return list(self._leases.values())

    async def adopt(self, lease: Authority) -> Authority:
        cur = self.get(lease.workloadId)
        if lease.epoch < cur.epoch:
            raise AuthorityError(f"refusing older lease {lease.epoch} < {cur.epoch} for {lease.workloadId}")
        return await self._set(lease)

    def may_run(self, workload_id: str) -> bool:
        lease = self.get(workload_id)
        return lease.holder == self.ctx.device_id and lease.state in ("SOURCE", "TARGET")

    def check_epoch(self, workload_id: str, epoch: int) -> bool:
        return epoch >= self.get(workload_id).epoch

    # ------------------------------------------------------------------ transitions

    async def _set(self, lease: Authority) -> Authority:
        with self._lock:
            self._leases[lease.workloadId] = lease
            data = {k: v.model_dump() for k, v in self._leases.items()}
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2), "utf-8")
            tmp.replace(self.path)
        await self.ctx.bus.publish(AuthorityChangeEvent(authority=lease))
        return lease

    def owned_by(self, workload_id: str, migration_id: str) -> bool:
        """True while `migration_id` is the migration that last set this workload's lease."""
        return self.get(workload_id).migrationId == migration_id

    async def claim(self, workload_id: str, holder: str) -> Authority:
        cur = self.get(workload_id)
        if cur.holder not in (None, holder) and cur.state != "SOURCE":
            raise AuthorityError(f"{workload_id} is held by {cur.holder} ({cur.state})")
        return await self._set(cur.model_copy(update={"holder": holder, "state": "SOURCE"}))

    async def fence(self, workload_id: str, migration_id: str | None = None) -> Authority:
        cur = self.get(workload_id)
        if cur.state != "SOURCE" or cur.holder != self.ctx.device_id:
            raise AuthorityError(f"cannot fence {workload_id}: {cur.state} held by {cur.holder}")
        update = {"state": "FENCED", "epoch": cur.epoch + 1, "migrationId": migration_id}
        return await self._set(cur.model_copy(update=update))

    async def grant(
        self, workload_id: str, holder: str, epoch: int, migration_id: str | None = None
    ) -> Authority:
        cur = self.get(workload_id)
        if epoch < cur.epoch:
            raise AuthorityError(f"stale epoch {epoch} < {cur.epoch} for {workload_id}")
        if (
            epoch == cur.epoch
            and migration_id
            and cur.migrationId
            and cur.migrationId != migration_id
            and cur.state != "FENCED"
        ):
            raise AuthorityError(
                f"epoch {epoch} of {workload_id} belongs to migration {cur.migrationId}, not {migration_id}"
            )
        lease = Authority(
            workloadId=workload_id,
            holder=holder,
            epoch=epoch,
            state="TARGET",
            migrationId=migration_id or cur.migrationId,
        )
        return await self._set(lease)

    async def release(self, workload_id: str) -> Authority:
        cur = self.get(workload_id)
        if cur.holder != self.ctx.device_id:
            return cur
        return await self._set(cur.model_copy(update={"holder": None, "state": "SOURCE"}))

    async def rollback(self, workload_id: str, migration_id: str | None = None) -> Authority:
        cur = self.get(workload_id)
        if cur.state != "FENCED":
            raise AuthorityError(f"cannot roll back {workload_id} in state {cur.state}")
        if migration_id and cur.migrationId and cur.migrationId != migration_id:
            raise AuthorityError(f"{workload_id} was fenced by {cur.migrationId}, not {migration_id}")
        return await self._set(cur.model_copy(update={"state": "SOURCE", "epoch": cur.epoch + 1}))

    async def reconcile(self, remote: Authority) -> bool:
        local = self.get(remote.workloadId)
        if local.holder != self.ctx.device_id:
            return False
        newer = remote.epoch > local.epoch
        handed_over = remote.epoch == local.epoch and local.state == "FENCED" and remote.state == "TARGET"
        if newer or handed_over:
            await self._set(remote)
            return True
        return False

    async def forget_foreign(self) -> int:
        """Start fresh: drop leases this device does not hold (they name forgotten devices)."""
        with self._lock:
            mine = {k: v for k, v in self._leases.items() if v.holder == self.ctx.device_id}
            dropped = len(self._leases) - len(mine)
            self._leases = mine
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({k: v.model_dump() for k, v in mine.items()}, indent=2), "utf-8")
            tmp.replace(self.path)
        return dropped

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass


def create_authority_service(ctx: Context) -> AuthorityStore:
    return AuthorityStore(ctx)

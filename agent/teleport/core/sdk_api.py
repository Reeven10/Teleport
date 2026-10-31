"""Agent-local API used by teleport_sdk inside a running workload (Bearer per-run token)."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from contract.contract import CheckpointRecord

from .context import Context

MAX_UNIT_BYTES = 1024 * 1024 * 1024


class FencedRequest(BaseModel):
    fenceSeq: int


def build_sdk_router(ctx: Context) -> APIRouter:
    r = APIRouter(prefix="/api/sdk/workloads/{workload_id}", include_in_schema=False)

    def auth(workload_id: str, authorization: str | None) -> None:
        token = (authorization or "").removeprefix("Bearer ").strip()
        if not ctx.workloads.check_token(workload_id, token):
            raise HTTPException(401, "invalid workload token")

    @r.post("/checkpoints/{checkpoint_id}")
    async def put_checkpoint(
        workload_id: str,
        checkpoint_id: str,
        request: Request,
        authorization: str | None = Header(None),
    ) -> CheckpointRecord:
        auth(workload_id, authorization)
        known = {c.id for c in ctx.workloads.manifest(workload_id).checkpoints}
        if checkpoint_id not in known:
            raise HTTPException(400, f"checkpoint {checkpoint_id!r} is not in the manifest ({sorted(known)})")
        data = await request.body()
        if len(data) > MAX_UNIT_BYTES:
            raise HTTPException(413, "checkpoint unit too large")
        try:
            # Hashing and validating a unit can take a while: keep the event loop free.
            return await asyncio.to_thread(ctx.checkpoints.put, workload_id, checkpoint_id, data)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None

    @r.get("/control")
    async def control(workload_id: str, authorization: str | None = Header(None)) -> dict[str, int | bool]:
        auth(workload_id, authorization)
        return ctx.workloads.control(workload_id)

    @r.post("/fenced")
    async def fenced(
        workload_id: str, req: FencedRequest, authorization: str | None = Header(None)
    ) -> dict[str, bool]:
        auth(workload_id, authorization)
        ctx.workloads.ack_fence(workload_id, req.fenceSeq)
        return {"ok": True}

    return r

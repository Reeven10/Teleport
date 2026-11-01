"""Viewing another device's screen from this dashboard.

The remote service (P4) runs on the device that hosts the workload: it captures that screen and
injects input. A dashboard only talks to its own agent, so this agent relays: it asks a paired
peer's agent for a session, lists the sessions peers offer to this device, and pipes the host's
/ws/remote stream to the browser through /ws/remote-view. The host still decides (consent prompt
on its own dashboard) and still issues the one-time token.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

import httpx
import websockets
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from starlette.websockets import WebSocket, WebSocketDisconnect

from .context import Context

log = logging.getLogger(__name__)

MAX_FRAME = 16 * 1024 * 1024


class RemoteViewRequest(BaseModel):
    hostId: str
    workloadId: str


class RemoteViewStop(BaseModel):
    hostId: str
    sessionId: str


def peer_base(ctx: Context, host_id: str) -> str:
    """http://host:port of a paired peer's agent: the address that last worked, else its best one."""
    preferred: dict[str, str] = getattr(ctx.peers, "_preferred", {}) or {}
    addr = preferred.get(host_id)
    if not addr:
        device = next((d for d in ctx.devices.list_devices() if d.id == host_id), None)
        if device is None or device.id == ctx.device_id:
            raise HTTPException(404, f"{host_id} is not a paired device")
        order = {"cable": 0, "wifi": 1, "loopback": 2}
        addrs = sorted(device.addrs, key=lambda a: order.get(a.link, 9))
        if not addrs:
            raise HTTPException(409, f"{device.name} has no known address")
        addr = addrs[0].addr
    addr = addr.strip().removeprefix("http://").removeprefix("ws://").split("/")[0]
    return f"http://{addr}"


def _peers(ctx: Context) -> list[Any]:
    return [d for d in ctx.devices.list_devices() if d.id != ctx.device_id]


async def _get(client: httpx.AsyncClient, url: str) -> Any:
    res = await client.get(url, timeout=2.5)
    res.raise_for_status()
    return res.json()


def _detail(res: httpx.Response) -> str:
    with contextlib.suppress(ValueError):
        body = res.json()
        if isinstance(body, dict) and body.get("detail"):
            return str(body["detail"])
    return f"HTTP {res.status_code}"


def build_remote_view_router(ctx: Context) -> APIRouter:
    r = APIRouter(prefix="/api/remote-view", tags=["remote-view"])

    @r.get("/hosts")
    async def hosts() -> list[dict[str, Any]]:
        """Paired devices and what runs there, with the sessions they offer to this device."""

        async def one(client: httpx.AsyncClient, d: Any) -> dict[str, Any]:
            entry: dict[str, Any] = {"id": d.id, "name": d.name, "reachable": False}
            try:
                base = peer_base(ctx, d.id)
                workloads, runs, sessions = await asyncio.gather(
                    _get(client, f"{base}/api/workloads"),
                    _get(client, f"{base}/api/workloads/runs"),
                    _get(client, f"{base}/api/remote/sessions"),
                )
            except Exception as e:  # unreachable peer: listed, but not viewable
                entry["error"] = str(e) or type(e).__name__
                return entry
            running = {w["workloadId"] for w in runs if w.get("state") in ("running", "paused")}
            entry.update(
                reachable=True,
                workloads=[
                    {"id": w["id"], "name": w["name"], "running": w["id"] in running} for w in workloads
                ],
                sessions=[s for s in sessions if s.get("viewerId") == ctx.device_id],
            )
            return entry

        async with httpx.AsyncClient() as client:
            return list(await asyncio.gather(*(one(client, d) for d in _peers(ctx))))

    @r.post("/request")
    async def request(req: RemoteViewRequest) -> Any:
        """Ask the host for a session; its dashboard then asks its user to allow it."""
        base = peer_base(ctx, req.hostId)
        body = {"workloadId": req.workloadId, "viewerId": ctx.device_id}
        try:
            async with httpx.AsyncClient() as client:
                res = await client.post(f"{base}/api/remote/start", json=body, timeout=5)
        except httpx.HTTPError as e:
            raise HTTPException(502, f"Could not reach the other device: {e}") from e
        if res.status_code >= 400:
            raise HTTPException(res.status_code, _detail(res))
        return res.json()

    @r.post("/stop")
    async def stop(req: RemoteViewStop) -> dict[str, bool]:
        base = peer_base(ctx, req.hostId)
        with contextlib.suppress(httpx.HTTPError):
            async with httpx.AsyncClient() as client:
                await client.post(f"{base}/api/remote/stop", json={"sessionId": req.sessionId}, timeout=5)
        return {"ok": True}

    return r


async def relay_viewer(ctx: Context, ws: WebSocket, host_id: str, session_id: str) -> None:
    """Browser <-> this agent <-> host agent: JPEG frames in, JSON input events out."""
    await ws.accept()
    try:
        base = peer_base(ctx, host_id)
        async with httpx.AsyncClient() as client:
            res = await client.get(f"{base}/api/remote/token/{session_id}", timeout=5)
        if res.status_code >= 400:
            await ws.close(code=4403, reason=_detail(res)[:120])
            return
        token = res.json()["token"]
    except (HTTPException, httpx.HTTPError, KeyError, ValueError) as e:
        await ws.close(code=4502, reason=f"host unreachable: {e}"[:120])
        return

    url = f"ws{base[4:]}/ws/remote/{session_id}?token={token}"
    try:
        async with websockets.connect(url, max_size=MAX_FRAME, open_timeout=5) as host:

            async def down() -> None:
                async for frame in host:
                    if isinstance(frame, bytes):
                        await ws.send_bytes(frame)
                    else:
                        await ws.send_text(frame)

            async def up() -> None:
                while True:
                    msg = await ws.receive()
                    if msg["type"] == "websocket.disconnect":
                        return
                    if msg.get("text") is not None:
                        await host.send(msg["text"])

            tasks = [asyncio.create_task(down()), asyncio.create_task(up())]
            _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
            reason = host.close_reason or "session ended"
    except (OSError, websockets.WebSocketException, WebSocketDisconnect) as e:
        log.info("remote view %s ended: %r", session_id, e)
        reason = "connection to the host was lost"
    with contextlib.suppress(Exception):
        await ws.close(code=1000, reason=reason[:120])

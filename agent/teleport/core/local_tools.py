"""Actions only the dashboard on this device may run: the native folder picker and "start fresh"."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

import psutil
from fastapi import HTTPException, Request

from .context import Context

log = logging.getLogger(__name__)

# Runs in its own process: Tk needs a main thread, and a dialog must never block the agent.
_PICKER = r"""
import sys
try:
    import tkinter as tk
    from tkinter import filedialog
except Exception as e:
    print("ERR:" + str(e)); sys.exit(0)
root = tk.Tk()
root.withdraw()
root.attributes("-topmost", True)
root.update()
path = filedialog.askdirectory(title=sys.argv[1], mustexist=True, parent=root)
root.destroy()
print("OK:" + (path or ""))
"""


def is_local_request(request: Request) -> bool:
    host = request.client.host if request.client else ""
    if host in ("127.0.0.1", "::1", "localhost", "testclient"):
        return True
    with contextlib.suppress(Exception):
        return any(a.address == host for addrs in psutil.net_if_addrs().values() for a in addrs)
    return False


async def pick_folder(title: str) -> str | None:
    """Show the system folder dialog on this device. Returns the chosen folder, or None if cancelled."""

    def run() -> str:
        res = subprocess.run(
            [sys.executable, "-c", _PICKER, title],
            capture_output=True,
            text=True,
            timeout=900,
        )
        return (res.stdout or "").strip().splitlines()[-1] if res.stdout.strip() else "ERR:no answer"

    try:
        out = await asyncio.to_thread(run)
    except subprocess.TimeoutExpired:
        return None
    if out.startswith("ERR:"):
        raise RuntimeError(f"No folder dialog on this device ({out[4:]}); type the path instead.")
    chosen = out[3:].strip()
    return str(Path(chosen)) if chosen else None


async def reset_devices(ctx: Context) -> dict[str, Any]:
    """Forget every paired device and clear the history, keeping this device's own workloads.

    Paired devices, their trusted keys and addresses, recorded history, finished migrations and leases
    that name other devices all go. History keeps recording afterwards. A forgotten device has to pair
    again with a PIN before it can reconnect.
    """
    migration: Any = ctx.migration
    if getattr(migration, "busy", lambda: False)():
        raise HTTPException(409, "A migration is running; wait for it to finish, then start fresh.")
    devices: Any = ctx.devices
    gone: list[str] = devices.forget_peers() if hasattr(devices, "forget_peers") else []
    peers: Any = ctx.peers
    if hasattr(peers, "forget_all"):
        await peers.forget_all(set(gone))
    history: Any = ctx.history
    cleared = await history.clear_all() if hasattr(history, "clear_all") else {}
    authority: Any = ctx.authority
    leases = await authority.forget_foreign() if hasattr(authority, "forget_foreign") else 0
    migrations = migration.forget_finished() if hasattr(migration, "forget_finished") else 0
    log.info("Started fresh: forgot %d devices, %d migrations, %d leases", len(gone), migrations, leases)
    return {"devices": len(gone), "migrations": migrations, "leases": leases, "history": cleared}

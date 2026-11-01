"""One-click start for a demo laptop: `python -m teleport.launch` (run by Teleport.cmd / teleport.command).

Listens on every interface (so the other laptop can find and reach it), keeps its state in
~/.teleport, names the device after the computer, and opens this device's dashboard in the browser.
Everything else (finding the other laptop, pairing, starting and migrating workloads) is done there.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

TCP_PORTS = "8765-8770"
DISCOVERY_PORT = "8767"
RULE = "Teleport"


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def _healthy(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1) as res:
            return bool(res.status == 200)
    except OSError:
        return False


def _open_dashboard_when_ready(port: int) -> None:
    for _ in range(120):
        if _healthy(port):
            webbrowser.open(f"http://127.0.0.1:{port}/")
            return
        time.sleep(0.5)


def _windows_firewall() -> None:
    """Allow Teleport through the Windows firewall once (one admin prompt). Without it, Windows
    asks for python.exe itself; tick both Private and Public networks there."""
    if sys.platform != "win32":
        return
    try:
        out = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule", f"name={RULE}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if "Rule Name" in out.stdout or "Nom de la r" in out.stdout:
            return
        rules = (
            f'netsh advfirewall firewall add rule name="{RULE}" dir=in action=allow protocol=TCP '
            f"localport={TCP_PORTS} profile=any & "
            f'netsh advfirewall firewall add rule name="{RULE}" dir=in action=allow protocol=UDP '
            f"localport={DISCOVERY_PORT} profile=any"
        )
        import ctypes

        print("Asking Windows once to let Teleport through the firewall (click Yes)...", flush=True)
        shell32 = getattr(ctypes, "windll").shell32  # noqa: B009 - windll exists on Windows only
        shell32.ShellExecuteW(None, "runas", "cmd.exe", f"/c {rules}", None, 0)
    except Exception as e:  # not fatal: Windows will show its own firewall prompt instead
        print(f"(firewall rule not added automatically: {e})", flush=True)


def main() -> None:
    p = argparse.ArgumentParser(prog="teleport.launch", description="Start Teleport on this laptop")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--home", default=str(Path.home() / ".teleport"))
    p.add_argument("--name", default=os.environ.get("TELEPORT_NAME") or socket.gethostname())
    p.add_argument("--no-browser", action="store_true")
    p.add_argument("--no-firewall", action="store_true", help="do not offer to add the Windows firewall rule")
    args = p.parse_args()

    if not _port_free(args.port):
        if _healthy(args.port):
            print(f"Teleport is already running: opening http://127.0.0.1:{args.port}/", flush=True)
            if not args.no_browser:
                webbrowser.open(f"http://127.0.0.1:{args.port}/")
            return
        args.port = next(port for port in range(args.port + 1, args.port + 6) if _port_free(port))

    os.environ.update(
        TELEPORT_HOST="0.0.0.0",
        TELEPORT_PORT=str(args.port),
        TELEPORT_HOME=str(Path(args.home).expanduser()),
        TELEPORT_NAME=args.name,
    )
    if not args.no_firewall:
        _windows_firewall()
    print(
        f'\n  Teleport is starting as "{args.name}" on port {args.port}.\n'
        f"  The dashboard opens in your browser: http://127.0.0.1:{args.port}/\n"
        "  Keep this window open while you use Teleport. Close it to stop.\n",
        flush=True,
    )
    if not args.no_browser:
        threading.Thread(target=_open_dashboard_when_ready, args=(args.port,), daemon=True).start()

    import logging

    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    with contextlib.suppress(KeyboardInterrupt):
        uvicorn.run(
            "teleport.core.app:create_app", factory=True, host="0.0.0.0", port=args.port, log_level="warning"
        )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Teleport Demo Reset Script.

Kills stale agent/UI processes, wipes `.teleport-dev/` state directories,
and optionally starts clean Agent A and Agent B processes.

Usage:
    python demo/reset.py             # Reset state and kill stale processes
    python demo/reset.py --start     # Reset state and spawn fresh agents
    python demo/reset.py --clean-only
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

PORTS_TO_CLEAR = [8765, 8766, 5173]
REPO_ROOT = Path(__file__).resolve().parent.parent


def print_banner(msg: str) -> None:
    print(f"=== {msg} ===")


def print_ok(msg: str) -> None:
    print(f"[OK] {msg}")


def print_info(msg: str) -> None:
    print(f"[INFO] {msg}")


def print_warn(msg: str) -> None:
    print(f"[WARN] {msg}")


def kill_ports(ports: list[int]) -> None:
    """Kill processes listening on specific TCP ports."""
    is_windows = platform.system() == "Windows"

    for port in ports:
        if is_windows:
            try:
                out = subprocess.check_output(
                    f"netstat -ano -p tcp | findstr :{port}",
                    shell=True,
                    stderr=subprocess.DEVNULL,
                    text=True,
                )
                for line in out.strip().splitlines():
                    parts = line.strip().split()
                    if len(parts) >= 5 and "LISTENING" in parts:
                        pid = parts[-1]
                        if pid.isdigit() and int(pid) > 0 and int(pid) != os.getpid():
                            print_info(f"Terminating Windows process {pid} on port {port}")
                            subprocess.run(
                                f"taskkill /F /PID {pid}",
                                shell=True,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                            )
            except Exception:
                pass
        else:
            try:
                out = subprocess.check_output(["lsof", f"-ti:{port}"], stderr=subprocess.DEVNULL, text=True)
                for pid_str in out.strip().splitlines():
                    pid = int(pid_str.strip())
                    if pid != os.getpid():
                        print_info(f"Terminating Unix process {pid} on port {port}")
                        os.kill(pid, 9)
            except Exception:
                pass


def wipe_dev_state() -> None:
    """Clean and recreate .teleport-dev/ working directories."""
    dev_dir = REPO_ROOT / ".teleport-dev"
    if dev_dir.exists():
        print_info(f"Wiping existing state directory: {dev_dir}")
        shutil.rmtree(dev_dir, ignore_errors=True)

    # Recreate pristine directories
    (dev_dir / "a").mkdir(parents=True, exist_ok=True)
    (dev_dir / "b").mkdir(parents=True, exist_ok=True)
    print_ok("Created pristine .teleport-dev/a and .teleport-dev/b directories")


def start_agents() -> None:
    """Spawn Agent A, Agent B, and report connectivity."""
    print_banner("Spawning Fresh Demo Agents")

    cmd_a = [
        sys.executable,
        "-m",
        "teleport",
        "--port",
        "8765",
        "--home",
        str(REPO_ROOT / ".teleport-dev" / "a"),
        "--sim-profile",
        "default",
        "--name",
        "Device A",
    ]

    cmd_b = [
        sys.executable,
        "-m",
        "teleport",
        "--port",
        "8766",
        "--home",
        str(REPO_ROOT / ".teleport-dev" / "b"),
        "--sim-profile",
        "arm64-lowspec",
        "--name",
        "Device B",
    ]

    print_info("Starting Device A on port 8765...")
    subprocess.Popen(cmd_a, cwd=str(REPO_ROOT))

    print_info("Starting Device B on port 8766...")
    subprocess.Popen(cmd_b, cwd=str(REPO_ROOT))

    print_ok("Agents launched in background.")
    print_info("To run the full suite with UI, use: npm run dev:two")
    print_info("Device A: http://127.0.0.1:8765")
    print_info("Device B: http://127.0.0.1:8766")
    print_info("UI Dev:   http://localhost:5173")


def main() -> None:
    parser = argparse.ArgumentParser(description="Teleport Demo Reset Utility")
    parser.add_argument("--start", action="store_true", help="Launch fresh background agents after reset")
    parser.add_argument(
        "--clean-only",
        action="store_true",
        help="Only wipe directories without killing processes",
    )
    args = parser.parse_args()

    print_banner("Teleport Demo Environment Reset")

    if not args.clean_only:
        print_info("Killing stale agents and web servers on ports 8765, 8766, 5173...")
        kill_ports(PORTS_TO_CLEAR)
        time.sleep(0.5)

    wipe_dev_state()

    if args.start:
        start_agents()
    else:
        print_ok("State successfully reset. Ready for live demo or npm run dev:two.")


if __name__ == "__main__":
    main()

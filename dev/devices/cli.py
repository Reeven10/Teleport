"""Dev CLI for Device Agent: inspect DeviceInfo, stream live Stats table, and apply simulator overrides."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from teleport.core import Settings, build_context
from teleport.devices.service import DeviceServiceImpl


def _post_json(url: str, payload: dict[str, Any], timeout: float = 2.0) -> dict[str, Any] | None:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))  # type: ignore[no-any-return]
    except Exception:
        return None


def _get_json(url: str, timeout: float = 0.4) -> Any:
    req = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def format_device_info(info: dict[str, Any]) -> str:
    addr_strs = [f"{a.get('addr')} ({a.get('link')})" for a in info.get("addrs", [])]
    lines = [
        "===========================================================",
        "                     TELEPORT DEVICE INFO                  ",
        "===========================================================",
        f"  Device ID:    {info.get('id')}",
        f"  Name:         {info.get('name')}",
        f"  OS / Arch:    {info.get('os')} / {info.get('arch')}",
        f"  CPU Cores:    {info.get('cpuCores')}",
        f"  Total RAM:    {info.get('ramMb')} MB",
        f"  GPU:          {info.get('gpu') or 'None detected'}",
        f"  Free Disk:    {info.get('diskFreeMb')} MB",
        f"  Runtimes:     {json.dumps(info.get('runtimes', {}))}",
        f"  Libraries:    {len(info.get('libs', []))} pip packages detected",
        f"  Addresses:    {', '.join(addr_strs)}",
        f"  Version:      {info.get('agentVersion')}",
        f"  Simulated:    {bool(info.get('simulated'))}",
        "===========================================================",
    ]
    return "\n".join(lines)


def run_cli(args: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dev.devices",
        description="Teleport Device Agent CLI: DeviceInfo, live stats table, simulator overrides",
    )
    parser.add_argument(
        "--url", default="http://127.0.0.1:8765", help="Agent REST URL (default: http://127.0.0.1:8765)"
    )
    parser.add_argument(
        "--port", type=int, default=8765, help="Agent port if running locally (default: 8765)"
    )
    parser.add_argument("--home", type=str, default=None, help="State folder (default: ~/.teleport)")
    parser.add_argument(
        "--sim-profile", type=str, default=None, help="Simulation profile (default, arm64-lowspec, dev:two)"
    )
    parser.add_argument("--info", action="store_true", help="Print DeviceInfo and exit")
    parser.add_argument("--once", action="store_true", help="Print stats once and exit")
    parser.add_argument("--override-battery", type=float, help="Override battery percentage (0-100)")
    parser.add_argument(
        "--override-charging",
        type=lambda s: s.lower() in ("true", "1", "yes"),
        help="Override charging state (true/false)",
    )
    parser.add_argument("--override-cpu", type=float, help="Override CPU percentage (0-100)")
    parser.add_argument("--clear-override", action="store_true", help="Clear simulator override for device")

    opts = parser.parse_args(args)

    base_url = opts.url.rstrip("/")
    home_path = Path(opts.home).expanduser().resolve() if opts.home else None

    # Try connecting to live agent via REST first
    health = _get_json(f"{base_url}/api/health")
    is_live_agent = health is not None and isinstance(health, dict) and health.get("ok")

    if is_live_agent:
        device_id = str(health.get("deviceId", "local"))
    else:
        # Standalone in-process context
        settings = Settings(
            port=opts.port,
            home=home_path or (Path.home() / ".teleport"),
            simProfile=opts.sim_profile,
        )
        ctx = build_context(settings)
        service = DeviceServiceImpl(ctx)
        device_id = ctx.device_id

    # Handle Simulator Overrides
    if opts.clear_override:
        if is_live_agent:
            res = _post_json(f"{base_url}/api/dev/stats-override", {"deviceId": device_id, "stats": None})
            print(f"[SIMULATOR] Cleared override on {base_url} (result: {res})")
        else:
            service.set_override(device_id, None)
            print(f"[SIMULATOR] Cleared local override for {device_id}")

    elif (
        opts.override_battery is not None
        or opts.override_cpu is not None
        or opts.override_charging is not None
    ):
        fake_stats: dict[str, Any] = {}
        if opts.override_battery is not None or opts.override_charging is not None:
            pct = opts.override_battery if opts.override_battery is not None else 10.0
            charging = opts.override_charging if opts.override_charging is not None else False
            fake_stats["battery"] = {"pct": pct, "charging": charging}
        if opts.override_cpu is not None:
            fake_stats["cpuPct"] = opts.override_cpu

        if is_live_agent:
            res = _post_json(
                f"{base_url}/api/dev/stats-override", {"deviceId": device_id, "stats": fake_stats}
            )
            print(f"[SIMULATOR] Applied override on {base_url}: {fake_stats} (result: {res})")
        else:
            service.set_override(device_id, fake_stats)
            print(f"[SIMULATOR] Applied local override for {device_id}: {fake_stats}")

    # Print DeviceInfo
    if is_live_agent:
        devices = _get_json(f"{base_url}/api/devices")
        local_info = devices[0] if devices and isinstance(devices, list) else {"id": device_id}
    else:
        local_info = service.local_info().model_dump()

    print(format_device_info(local_info))

    if opts.info:
        return 0

    # Live Stats Table
    print("\nLive Stats:")
    hdr = (
        f"{'Time':<10} | {'Device ID':<16} | {'CPU %':<6} | {'Mem %':<6} | "
        f"{'Free RAM':<9} | {'Free Disk':<10} | {'Battery':<15} | {'Status':<7}"
    )
    print(hdr)
    print("-" * 92)

    def print_stat_row(s: dict[str, Any]) -> None:
        t_str = datetime.fromtimestamp(s.get("ts", time.time())).strftime("%H:%M:%S")
        dev_id = str(s.get("deviceId", ""))[:16]
        cpu = f"{s.get('cpuPct', 0.0):.1f}%"
        mem = f"{s.get('memPct', 0.0):.1f}%"
        free_ram = f"{s.get('memFreeMb', 0)} MB"
        free_disk = f"{s.get('diskFreeMb', 0)} MB"
        bat = s.get("battery")
        if bat:
            chg = "+" if bat.get("charging") else ""
            bat_str = f"{bat.get('pct', 0.0):.0f}%{chg}"
        else:
            bat_str = "None (AC)"
        sim_tag = " [SIM]" if s.get("simulated") else ""
        bat_disp = f"{bat_str:<10}{sim_tag}"
        online_str = "ONLINE" if s.get("online") else "OFFLINE"
        row = (
            f"{t_str:<10} | {dev_id:<16} | {cpu:<6} | {mem:<6} | "
            f"{free_ram:<9} | {free_disk:<10} | {bat_disp:<15} | {online_str:<7}"
        )
        print(row)

    try:
        while True:
            if is_live_agent:
                stats_list = _get_json(f"{base_url}/api/stats")
                if stats_list and isinstance(stats_list, list):
                    for st in stats_list:
                        print_stat_row(st)
                else:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Waiting for agent stats on {base_url}...")
            else:
                st_obj = service._sample_sync()
                print_stat_row(st_obj.model_dump())

            if opts.once:
                break
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    sys.exit(run_cli())

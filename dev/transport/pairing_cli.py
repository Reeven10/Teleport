"""CLI for Teleport PIN pairing and peer link inspection."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any


def _get_json(url: str, timeout: float = 3.0) -> Any:
    req = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"Error connecting to {url}: {e}", file=sys.stderr)
        return None


def _post_json(url: str, payload: dict[str, Any], timeout: float = 5.0) -> Any:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        print(f"HTTP Error {e.code}: {err_body}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Request failed: {e}", file=sys.stderr)
        return None


def run_pairing_cli(args: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dev.transport.pairing_cli",
        description="Inspect PIN pairing and link status across Teleport agents",
    )
    parser.add_argument(
        "--url", default="http://127.0.0.1:8765", help="Local agent base URL (default: http://127.0.0.1:8765)"
    )
    parser.add_argument("--show-pin", action="store_true", help="Display local agent pairing PIN")
    parser.add_argument("--rotate-pin", action="store_true", help="Rotate local agent pairing PIN")
    parser.add_argument("--pair", type=str, help="Target peer address to pair with (e.g. 127.0.0.1:8766)")
    parser.add_argument("--pin", type=str, help="6-digit PIN to pair with target peer")
    parser.add_argument("--list-peers", action="store_true", help="List all known and paired peers")

    opts = parser.parse_args(args)
    base_url = opts.url.rstrip("/")

    if opts.show_pin:
        res = _get_json(f"{base_url}/api/pair")
        if res:
            print(f"Pairing PIN for {res.get('name')} ({res.get('deviceId')}): {res.get('pin')}")
        return 0

    if opts.rotate_pin:
        res = _post_json(f"{base_url}/api/pair/pin", {})
        if res:
            print(f"New Pairing PIN: {res.get('pin')}")
        return 0

    if opts.pair:
        if not opts.pin:
            print("Error: --pin <6-digit-pin> is required when pairing with --pair <addr>", file=sys.stderr)
            return 1
        res = _post_json(f"{base_url}/api/pair", {"addr": opts.pair, "pin": opts.pin})
        if res:
            print(f"Successfully paired with {res.get('name')} ({res.get('id')})!")
            print(json.dumps(res, indent=2))
        return 0

    if opts.list_peers:
        res = _get_json(f"{base_url}/api/devices")
        if res and isinstance(res, list):
            print(f"Total known devices: {len(res)}")
            for d in res:
                info_line = (
                    f" - {d.get('name')} [{d.get('id')}]: OS={d.get('os')}, "
                    f"Arch={d.get('arch')}, Addrs={d.get('addrs')}"
                )
                print(info_line)
        return 0

    # Default: show PIN and peers
    res_pair = _get_json(f"{base_url}/api/pair")
    if res_pair:
        print(f"Agent: {res_pair.get('name')} ({res_pair.get('deviceId')})")
        print(f"Active PIN: {res_pair.get('pin')}")

    devices = _get_json(f"{base_url}/api/devices")
    if devices and isinstance(devices, list):
        print(f"\nKnown Devices ({len(devices)}):")
        for d in devices:
            print(f" * {d.get('name')} ({d.get('id')})")

    return 0


if __name__ == "__main__":
    sys.exit(run_pairing_cli())

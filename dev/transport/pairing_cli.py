"""CLI for Teleport PIN pairing, link quality monitoring, and fault injection."""

from __future__ import annotations

import argparse
import json
import sys
import time
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
        description="Inspect PIN pairing, monitor live link quality, and apply fault injection",
    )
    parser.add_argument(
        "--url", default="http://127.0.0.1:8765", help="Local agent base URL (default: http://127.0.0.1:8765)"
    )
    parser.add_argument("--show-pin", action="store_true", help="Display local agent pairing PIN")
    parser.add_argument("--rotate-pin", action="store_true", help="Rotate local agent pairing PIN")
    parser.add_argument("--pair", type=str, help="Target peer address to pair with (e.g. 127.0.0.1:8766)")
    parser.add_argument("--pin", type=str, help="6-digit PIN to pair with target peer")
    parser.add_argument("--list-peers", action="store_true", help="List all known and paired peers")
    parser.add_argument(
        "--monitor", action="store_true", help="Monitor live link quality for all active peer links"
    )
    parser.add_argument(
        "--force-link",
        type=str,
        choices=["cable", "wifi", "loopback", "none"],
        help="Force specific link type",
    )
    parser.add_argument("--fault-inject", action="store_true", help="Apply fault injector parameters")
    parser.add_argument("--clear-faults", action="store_true", help="Clear all fault injector parameters")
    parser.add_argument("--peer", type=str, help="Specific target peer ID for fault injection")
    parser.add_argument("--latency", type=float, default=0.0, help="Extra latency in milliseconds")
    parser.add_argument("--drop", type=float, default=0.0, help="Packet drop rate between 0.0 and 1.0")
    parser.add_argument("--bandwidth-cap", type=float, default=None, help="Bandwidth cap in Mbps")

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

    if opts.force_link:
        target_link = None if opts.force_link == "none" else opts.force_link
        res = _post_json(f"{base_url}/api/transport/force-link", {"link": target_link})
        if res:
            print(f"Forced link updated: {res.get('forcedLink')}")
        return 0

    if opts.clear_faults:
        res = _post_json(f"{base_url}/api/dev/fault-inject/clear", {"peerId": opts.peer})
        if res:
            print(f"Fault injection cleared for {'all peers' if not opts.peer else opts.peer}")
        return 0

    if opts.fault_inject:
        payload = {
            "peerId": opts.peer,
            "latencyMs": opts.latency,
            "dropRate": opts.drop,
            "bandwidthCapMbps": opts.bandwidth_cap,
        }
        res = _post_json(f"{base_url}/api/dev/fault-inject", payload)
        if res:
            print(f"Fault injector applied [SIMULATED]: {json.dumps(res.get('faults'), indent=2)}")
        return 0

    if opts.monitor:
        print(f"Monitoring live link quality on {base_url} (Ctrl+C to stop)...")
        print(f"{'Peer ID':<20} {'Link':<10} {'RTT (ms)':<10} {'Mbps':<10} {'Loss %':<10} {'Simulated?':<12}")
        print("-" * 75)
        try:
            while True:
                qualities = _get_json(f"{base_url}/api/transport/link-quality")
                if qualities and isinstance(qualities, list):
                    for q in qualities:
                        sim_label = "SIMULATED" if q.get("simulated") else "No"
                        print(
                            f"{q.get('peerId', 'unknown'):<20} "
                            f"{q.get('link', 'unknown'):<10} "
                            f"{q.get('rttMs', 0):<10.2f} "
                            f"{q.get('mbps', 0):<10.1f} "
                            f"{q.get('lossPct', 0):<10.2f} "
                            f"{sim_label:<12}"
                        )
                time.sleep(1.0)
        except KeyboardInterrupt:
            print("\nStopped link monitor.")
        return 0

    # Default: show PIN, peers, and link quality summary
    res_pair = _get_json(f"{base_url}/api/pair")
    if res_pair:
        print(f"Agent: {res_pair.get('name')} ({res_pair.get('deviceId')})")
        print(f"Active PIN: {res_pair.get('pin')}")

    devices = _get_json(f"{base_url}/api/devices")
    if devices and isinstance(devices, list):
        print(f"\nKnown Devices ({len(devices)}):")
        for d in devices:
            print(f" * {d.get('name')} ({d.get('id')})")

    qualities = _get_json(f"{base_url}/api/transport/link-quality")
    if qualities and isinstance(qualities, list) and qualities:
        print(f"\nActive Peer Links ({len(qualities)}):")
        for q in qualities:
            sim_str = " [SIMULATED]" if q.get("simulated") else ""
            p_id = q.get("peerId")
            l_type = q.get("link")
            rtt = q.get("rttMs")
            mbps = q.get("mbps")
            loss = q.get("lossPct")
            print(f" - {p_id}: {l_type} | RTT={rtt}ms | {mbps} Mbps | loss={loss}%{sim_str}")

    return 0


if __name__ == "__main__":
    sys.exit(run_pairing_cli())

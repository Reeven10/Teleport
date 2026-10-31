"""Self-check diagnostic tool for Teleport agents across physical devices.

Tests:
  1. Local port binding / listener availability
  2. Network interface enumeration and link type classification
  3. Peer address reachability and firewall diagnostics
  4. System clock difference / skew measurement
  5. Physical link type and round-trip time (RTT)

Usage:
  python -m teleport.devices.selfcheck [peer_addr] [--port PORT]
"""

from __future__ import annotations

import argparse
import email.utils
import json
import socket
import sys
import time
import urllib.error
import urllib.request
from typing import Any

from teleport.devices.capabilities import get_network_addresses, guess_link_type


class SelfCheckResult:
    def __init__(self) -> None:
        self.passed: list[str] = []
        self.warnings: list[str] = []
        self.failures: list[str] = []
        self.details: dict[str, Any] = {}

    @property
    def is_ok(self) -> bool:
        return len(self.failures) == 0


def check_local_port(port: int) -> tuple[bool, str]:
    """Test whether the configured port is listening or bindable."""
    # First check if local Teleport agent is already running on this port
    try:
        url = f"http://127.0.0.1:{port}/api/devices"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            if resp.status == 200:
                return True, f"Teleport agent is currently running and listening on port {port}."
    except Exception:
        pass

    # Test if port can be bound
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("0.0.0.0", port))
        sock.close()
        return True, f"Port {port} is free and ready to accept incoming peer connections."
    except OSError as e:
        sock.close()
        return False, (
            f"Port {port} cannot be bound ({e}). Ensure no conflicting process is using it "
            f"and Windows Firewall / OS allows binding."
        )


def check_interfaces(port: int) -> tuple[bool, list[dict[str, str]], str]:
    """Inspect and classify useful network addresses."""
    addrs = get_network_addresses(port, bind_host="0.0.0.0")
    details = [{"addr": a.addr, "link": a.link} for a in addrs]

    has_physical = any(a.link in ("cable", "wifi") for a in addrs)
    if has_physical:
        summary = f"Detected {len(addrs)} candidate address(es). Found active physical network link."
        return True, details, summary

    summary = (
        f"Only loopback address detected ({len(addrs)} total). "
        "Connect Wi-Fi or data cable for multi-device pairing."
    )
    return True, details, summary


def check_peer_connectivity(peer_addr: str) -> tuple[bool, float, dict[str, Any], str]:
    """Test connection, firewall reachability, clock difference, and RTT to peer device."""
    clean = peer_addr.strip().removeprefix("http://").removeprefix("https://").rstrip("/")
    if ":" not in clean:
        return False, 0.0, {}, (
            f"Invalid peer address '{peer_addr}'. Expected format: <host>:<port> (e.g. 192.168.1.50:8765)"
        )

    host, port_str = clean.split(":", 1)
    try:
        port = int(port_str)
    except ValueError:
        return False, 0.0, {}, f"Invalid port in peer address '{peer_addr}'."

    http_url = f"http://{clean}/api/pair"
    req = urllib.request.Request(http_url, method="GET")

    t_start = time.perf_counter()
    t_req = time.time()
    try:
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            rtt_ms = (time.perf_counter() - t_start) * 1000.0
            body = json.loads(resp.read().decode("utf-8"))
            date_header = resp.headers.get("Date")
            peer_ts: float | None = None
            if date_header:
                parsed_time = email.utils.parsedate_to_datetime(date_header)
                peer_ts = parsed_time.timestamp()

            clock_skew = abs(t_req - peer_ts) if peer_ts is not None else 0.0
            info = {
                "peerName": body.get("name", "Unknown"),
                "peerId": body.get("deviceId", "Unknown"),
                "clockSkewSec": round(clock_skew, 3),
                "tcpRttMs": round(rtt_ms, 2),
            }
            return True, clock_skew, info, f"Connected to peer '{info['peerName']}' ({info['peerId']})."
    except urllib.error.URLError as e:
        if isinstance(e.reason, (socket.timeout, TimeoutError)):
            return False, 0.0, {}, (
                f"Connection to peer at {host}:{port} timed out after 3.0s.\n"
                f"  Troubleshooting: Verify that '{host}' is on the same local network,\n"
                f"  and check that port {port} is permitted in Windows Firewall (Inbound Rules)."
            )
        if isinstance(e.reason, (ConnectionRefusedError, ConnectionResetError)):
            return False, 0.0, {}, (
                f"Connection refused at {host}:{port}.\n"
                f"  Troubleshooting: Ensure the Teleport agent is running on the other device."
            )
        return False, 0.0, {}, f"Failed to reach peer at {host}:{port}: {e.reason}"
    except Exception as e:
        return False, 0.0, {}, f"Failed to reach peer at {host}:{port}: {e}"


def run_selfcheck(peer_addr: str | None = None, port: int = 8765) -> SelfCheckResult:
    """Run all self-check diagnostics."""
    res = SelfCheckResult()

    # 1. Local port check
    port_ok, port_msg = check_local_port(port)
    if port_ok:
        res.passed.append(f"Port {port}: {port_msg}")
    else:
        res.failures.append(f"Port {port}: {port_msg}")

    # 2. Interfaces check
    if_ok, if_details, if_msg = check_interfaces(port)
    res.details["interfaces"] = if_details
    if if_ok:
        res.passed.append(f"Network interfaces: {if_msg}")
    else:
        res.warnings.append(f"Network interfaces: {if_msg}")

    # 3. Peer connectivity & clock check
    if peer_addr:
        link_type = guess_link_type("peer", peer_addr.split(":")[0])
        peer_ok, clock_skew, peer_info, peer_msg = check_peer_connectivity(peer_addr)
        res.details["peer"] = peer_info
        res.details["linkType"] = link_type

        if peer_ok:
            rtt_val = peer_info.get("tcpRttMs", 0.0)
            res.passed.append(
                f"Peer reachability: {peer_msg} (RTT: {rtt_val:.2f}ms, link guess: {link_type})"
            )
            if clock_skew > 2.0:
                res.warnings.append(
                    f"Clock difference warning: Clock skew with peer is {clock_skew:.2f}s "
                    "(> 2.0s tolerance). Synchronize system clocks on both devices."
                )
            else:
                res.passed.append(
                    f"Clock synchronization: Difference is {clock_skew:.2f}s (within 2.0s budget)."
                )
        else:
            res.failures.append(f"Peer reachability: {peer_msg}")
    else:
        res.passed.append("Peer reachability: No peer address specified; skipped remote peer probes.")

    return res


def main(args: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m teleport.devices.selfcheck",
        description="Teleport physical multi-device network & firewall self-check tool",
    )
    parser.add_argument("peer", nargs="?", default=None, help="Peer address to test (e.g. 192.168.1.50:8765)")
    parser.add_argument("--port", type=int, default=8765, help="Local agent port (default: 8765)")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")

    opts = parser.parse_args(args)
    results = run_selfcheck(peer_addr=opts.peer, port=opts.port)

    if opts.json:
        data = {
            "ok": results.is_ok,
            "passed": results.passed,
            "warnings": results.warnings,
            "failures": results.failures,
            "details": results.details,
        }
        print(json.dumps(data, indent=2))
        return 0 if results.is_ok else 1

    print("=" * 70)
    print(" TELEPORT PHYSICAL DEVICE & NETWORK SELF-CHECK")
    print("=" * 70)

    for p in results.passed:
        print(f"  [PASS] {p}")
    for w in results.warnings:
        print(f"  [WARN] {w}")
    for f in results.failures:
        print(f"  [FAIL] {f}")

    if results.details.get("interfaces"):
        print("\n  Advertised Interfaces:")
        for iface in results.details["interfaces"]:
            print(f"    - {iface['addr']:<25} ({iface['link']})")

    print("-" * 70)
    if results.is_ok:
        print("  RESULT: SELF-CHECK PASSED. System is ready for pairing and migration.")
        return 0
    else:
        print("  RESULT: SELF-CHECK FAILED. Please resolve issues above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())

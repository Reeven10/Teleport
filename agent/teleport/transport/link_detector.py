"""Link type detection and peer address selection.

Classifies network interfaces as 'cable', 'wifi', or 'loopback' across Windows,
macOS, and Linux using interface names, link speeds, and IP address ranges.
"""

from __future__ import annotations

import re

from contract.contract import DeviceAddr, LinkType

# Known point-to-point and tethering address prefixes (USB tethering, direct ethernet)
POINT_TO_POINT_PREFIXES = (
    "169.254.",  # IPv4 link-local (point-to-point autoconfig)
    "192.168.42.",  # Android USB tethering (RNDIS/CDC-NCM)
    "172.20.10.",  # iOS USB tethering
    "192.168.137.",  # Windows Internet Connection Sharing (direct cable)
)

WIFI_REGEX = re.compile(r"^(wl[a-z0-9]+|airport|wlan[0-9]+)", re.IGNORECASE)


def classify_interface(name: str, ip: str, speed_mbps: int = 0) -> LinkType:
    """Classify network interface as 'loopback', 'cable', or 'wifi'.

    Args:
        name: OS interface name (e.g. 'eth0', 'Wi-Fi', 'en0', 'rndis0')
        ip: IPv4 address
        speed_mbps: Negotiated link speed in Mbps from psutil
    """
    clean_name = name.strip().lower()
    clean_ip = ip.strip()

    # 1. Loopback check
    if (
        clean_ip.startswith("127.")
        or clean_ip == "::1"
        or clean_name in ("lo", "loopback")
        or clean_name.startswith("lo0")
        or "loopback" in clean_name
    ):
        return "loopback"

    # 2. Explicit Wi-Fi keywords (checked before cable to avoid 'wlan' matching 'lan')
    wifi_keywords = ("wi-fi", "wifi", "wlan", "wireless", "airport")
    has_wifi_keyword = any(k in clean_name for k in wifi_keywords) or bool(WIFI_REGEX.match(clean_name))
    if has_wifi_keyword:
        return "wifi"

    # 3. Point-to-point / Cable address ranges (e.g. 169.254 link-local or USB tethering)
    is_p2p_subnet = any(clean_ip.startswith(prefix) for prefix in POINT_TO_POINT_PREFIXES)

    # 4. macOS en0 heuristic: on MacBooks en0 is Wi-Fi unless high-speed gigabit cable or link-local
    if clean_name == "en0":
        if speed_mbps >= 1000 or is_p2p_subnet:
            return "cable"
        return "wifi"

    # 5. Explicit Cable keywords
    cable_keywords = (
        "eth",
        "enp",
        "ethernet",
        "usb",
        "rndis",
        "cdc",
        "thunderbolt",
        "cable",
        "local area connection",
        "bridge",
        "vethernet",
    )
    has_cable_keyword = any(k in clean_name for k in cable_keywords)

    # macOS en1, en2, etc. with Thunderbolt/USB/Ethernet hardware
    if clean_name.startswith("en") and clean_name != "en0":
        return "cable"

    if has_cable_keyword or is_p2p_subnet or speed_mbps >= 1000:
        return "cable"

    # Default fallback for active interfaces
    return "cable"


def select_best_address(
    addrs: list[DeviceAddr],
    forced_link: LinkType | None = None,
) -> DeviceAddr | None:
    """Select the best address to dial from a target device's advertised addresses.

    Preference policy:
      1. Forced link type if specified in settings/environment
      2. 'cable' (high bandwidth, low jitter, point-to-point USB/ethernet)
      3. 'wifi' (wireless local network)
      4. 'loopback' (local test)
    """
    if not addrs:
        return None

    if forced_link:
        matching = [a for a in addrs if a.link == forced_link]
        if matching:
            return matching[0]

    priority: dict[LinkType, int] = {
        "cable": 0,
        "wifi": 1,
        "loopback": 2,
    }

    sorted_addrs = sorted(addrs, key=lambda a: priority.get(a.link, 99))
    return sorted_addrs[0]

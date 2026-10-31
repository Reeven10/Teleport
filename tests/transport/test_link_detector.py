"""Tests for link type detection: Windows, macOS, Linux interface tables and address selection."""

from __future__ import annotations

from contract.contract import DeviceAddr
from teleport.transport.link_detector import classify_interface, select_best_address


def test_windows_interface_classification() -> None:
    cases = [
        # (name, ip, speed_mbps, expected)
        ("Loopback Pseudo-Interface 1", "127.0.0.1", 0, "loopback"),
        ("Wi-Fi", "192.168.1.100", 144, "wifi"),
        ("Wireless Network Connection", "10.0.0.25", 300, "wifi"),
        ("Ethernet", "192.168.1.50", 1000, "cable"),
        ("Ethernet 2", "169.254.50.1", 100, "cable"),
        ("Remote NDIS based Internet Sharing Device", "192.168.42.12", 425, "cable"),
        ("vEthernet (Default Switch)", "172.28.16.1", 10000, "cable"),
        ("Local Area Connection", "10.10.1.5", 100, "cable"),
    ]
    for name, ip, speed, expected in cases:
        assert classify_interface(name, ip, speed) == expected, f"Failed for Windows iface {name}"


def test_macos_interface_classification() -> None:
    cases = [
        ("lo0", "127.0.0.1", 0, "loopback"),
        ("en0", "192.168.1.15", 300, "wifi"),  # MacBook Wi-Fi
        ("en0", "192.168.1.15", 1000, "cable"),  # Mac Mini Gigabit Ethernet
        ("en1", "169.254.12.34", 100, "cable"),  # Thunderbolt Ethernet link-local
        ("en5", "192.168.2.1", 2500, "cable"),  # USB-C 2.5G LAN
        ("bridge0", "192.168.3.1", 1000, "cable"),  # Thunderbolt bridge
    ]
    for name, ip, speed, expected in cases:
        assert classify_interface(name, ip, speed) == expected, f"Failed for macOS iface {name}"


def test_linux_interface_classification() -> None:
    cases = [
        ("lo", "127.0.0.1", 0, "loopback"),
        ("wlan0", "192.168.1.20", 54, "wifi"),
        ("wlp3s0", "10.0.0.5", 866, "wifi"),
        ("eth0", "192.168.1.10", 1000, "cable"),
        ("enp4s0", "10.1.1.1", 10000, "cable"),
        ("usb0", "192.168.42.2", 480, "cable"),
        ("rndis0", "192.168.42.1", 100, "cable"),
    ]
    for name, ip, speed, expected in cases:
        assert classify_interface(name, ip, speed) == expected, f"Failed for Linux iface {name}"


def test_cable_preferred_over_wifi() -> None:
    addrs = [
        DeviceAddr(addr="127.0.0.1:8765", link="loopback"),
        DeviceAddr(addr="192.168.1.50:8765", link="wifi"),
        DeviceAddr(addr="169.254.1.2:8765", link="cable"),
    ]
    best = select_best_address(addrs)
    assert best is not None
    assert best.link == "cable"
    assert best.addr == "169.254.1.2:8765"


def test_forced_link_selection() -> None:
    addrs = [
        DeviceAddr(addr="169.254.1.2:8765", link="cable"),
        DeviceAddr(addr="192.168.1.50:8765", link="wifi"),
    ]
    # Forcing wifi should override natural cable preference
    chosen = select_best_address(addrs, forced_link="wifi")
    assert chosen is not None
    assert chosen.link == "wifi"
    assert chosen.addr == "192.168.1.50:8765"

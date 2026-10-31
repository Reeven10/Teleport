"""Capability probe for DeviceInfo: hardware, runtimes, libraries, and network links."""

from __future__ import annotations

import importlib.metadata
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
from typing import TYPE_CHECKING, Any

import psutil

from contract.contract import Arch, DeviceAddr, DeviceInfo, LinkType, OsName

from .. import __version__

if TYPE_CHECKING:
    from ..core.context import Context

_gpu_cache: str | None = None
_gpu_probed: bool = False
_runtimes_cache: dict[str, str] | None = None
_libs_cache: list[str] | None = None


def get_os() -> OsName:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def get_arch() -> Arch:
    machine = platform.machine().lower()
    return "arm64" if machine in ("arm64", "aarch64") else "x86_64"


def get_gpu() -> str | None:
    """Fast probe for GPU name with caching. Never blocks or crawls."""
    global _gpu_cache, _gpu_probed
    if _gpu_probed:
        return _gpu_cache
    _gpu_probed = True

    # 1. NVIDIA via nvidia-smi if available
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            res = subprocess.run(
                [smi, "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=1.0,
            )
            if res.returncode == 0 and res.stdout.strip():
                _gpu_cache = res.stdout.strip().splitlines()[0].strip()
                return _gpu_cache
        except Exception:
            pass

    # 2. Windows fast registry query
    if sys.platform == "win32":
        try:
            import winreg

            for subkey in ("0000", "0001", "0002"):
                try:
                    cls_id = "{4d36e968-e325-11ce-bfc1-08002be10318}"
                    path = rf"SYSTEM\CurrentControlSet\Control\Class\{cls_id}\{subkey}"
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as k:
                        desc, _ = winreg.QueryValueEx(k, "DriverDesc")
                        if desc and "Basic Render" not in desc and "Remote Display" not in desc:
                            _gpu_cache = str(desc).strip()
                            return _gpu_cache
                except OSError:
                    continue
        except Exception:
            pass

    # 3. macOS Apple Silicon or display query
    elif sys.platform == "darwin":
        try:
            res = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True,
                text=True,
                timeout=1.0,
            )
            if res.returncode == 0 and "Apple" in res.stdout:
                _gpu_cache = res.stdout.strip()
                return _gpu_cache
        except Exception:
            pass

    # 4. Linux lspci
    elif sys.platform.startswith("linux"):
        lspci = shutil.which("lspci")
        if lspci:
            try:
                res = subprocess.run(
                    [lspci],
                    capture_output=True,
                    text=True,
                    timeout=1.0,
                )
                if res.returncode == 0:
                    for line in res.stdout.splitlines():
                        if "VGA" in line or "3D controller" in line:
                            parts = line.split(":", 2)
                            if len(parts) >= 3:
                                _gpu_cache = parts[2].strip()
                                return _gpu_cache
            except Exception:
                pass

    _gpu_cache = None
    return None


def get_runtimes() -> dict[str, str]:
    """Detect Python, Node, and Java versions via quick subprocess with timeouts, cached."""
    global _runtimes_cache
    if _runtimes_cache is not None:
        return _runtimes_cache

    runtimes: dict[str, str] = {
        "python": platform.python_version(),
    }

    node = shutil.which("node")
    if node:
        try:
            res = subprocess.run([node, "-v"], capture_output=True, text=True, timeout=1.5)
            if res.returncode == 0 and res.stdout.strip():
                runtimes["node"] = res.stdout.strip().lstrip("v").strip()
        except Exception:
            pass

    java = shutil.which("java")
    if java:
        try:
            res = subprocess.run([java, "-version"], capture_output=True, text=True, timeout=1.5)
            out = (res.stderr or res.stdout or "").strip()
            match = re.search(r'version "([^"]+)"', out)
            if not match:
                match = re.search(r"(?:version|build)\s+([0-9._]+)", out)
            if match:
                runtimes["java"] = match.group(1).strip()
        except Exception:
            pass

    _runtimes_cache = runtimes
    return runtimes


def get_installed_libraries() -> list[str]:
    """Inspect pip packages via standard importlib metadata, fast and cached."""
    global _libs_cache
    if _libs_cache is not None:
        return _libs_cache

    try:
        pkgs: set[str] = set()
        for dist in importlib.metadata.distributions():
            name = getattr(dist, "name", None)
            if not name and dist.metadata and "Name" in dist.metadata:
                name = dist.metadata["Name"]
            if name:
                pkgs.add(str(name).lower())
        _libs_cache = sorted(pkgs)
    except Exception:
        _libs_cache = []
    return _libs_cache


def guess_link_type(iface_name: str, ip_str: str) -> LinkType:
    name = iface_name.lower().strip()
    if (
        ip_str.startswith("127.")
        or ip_str == "::1"
        or "loopback" in name
        or name == "lo"
        or name.startswith("lo0")
    ):
        return "loopback"
    if any(k in name for k in ("wi-fi", "wifi", "wlan", "wireless", "airport")) or name.startswith("wl"):
        return "wifi"
    if any(
        k in name
        for k in (
            "eth",
            "enp",
            "ethernet",
            "usb",
            "rndis",
            "cdc",
            "thunderbolt",
            "lan",
            "cable",
            "local area",
        )
    ):
        return "cable"
    if name.startswith("en"):
        return "cable"
    return "cable"


def get_network_addresses(port: int) -> list[DeviceAddr]:
    """Enumerate network addresses and guess link type (cable, wifi, loopback)."""
    addrs: list[DeviceAddr] = []
    seen: set[str] = set()

    try:
        if_addrs = psutil.net_if_addrs()
        if_stats = psutil.net_if_stats()

        for iface, addr_list in if_addrs.items():
            stats = if_stats.get(iface)
            is_up = stats.isup if stats else True
            for a in addr_list:
                if a.family == socket.AF_INET:
                    ip = a.address
                    if ip == "0.0.0.0":
                        continue
                    link = guess_link_type(iface, ip)
                    formatted = f"{ip}:{port}"
                    if formatted not in seen and (is_up or link == "loopback"):
                        seen.add(formatted)
                        addrs.append(DeviceAddr(addr=formatted, link=link))
    except Exception:
        pass

    loopback_addr = f"127.0.0.1:{port}"
    if loopback_addr not in seen:
        addrs.append(DeviceAddr(addr=loopback_addr, link="loopback"))

    link_priority: dict[LinkType, int] = {"cable": 0, "wifi": 1, "loopback": 2}
    addrs.sort(key=lambda a: link_priority.get(a.link, 3))
    return addrs


def probe_local_device(ctx: Context) -> DeviceInfo:
    """Build local DeviceInfo with hardware, runtimes, libraries, and addresses."""
    port = ctx.settings.port
    home = ctx.settings.home

    name = ctx.settings.deviceName or socket.gethostname()
    cores = psutil.cpu_count(logical=True) or os.cpu_count() or 1
    ram_mb = psutil.virtual_memory().total // (1024 * 1024)
    free_disk_mb = shutil.disk_usage(home).free // (1024 * 1024)

    info: dict[str, Any] = {
        "id": ctx.device_id,
        "name": name,
        "os": get_os(),
        "arch": get_arch(),
        "cpuCores": cores,
        "ramMb": ram_mb,
        "gpu": get_gpu(),
        "diskFreeMb": free_disk_mb,
        "runtimes": get_runtimes(),
        "libs": get_installed_libraries(),
        "addrs": [a.model_dump() for a in get_network_addresses(port)],
        "agentVersion": __version__,
        "simulated": None,
    }
    return DeviceInfo.model_validate(info)

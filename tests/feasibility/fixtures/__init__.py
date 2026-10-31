"""Test fixtures and loaders for feasibility engine checks (P3)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from contract.contract import DeviceInfo, LinkQuality, Stats, WorkloadManifest

FIXTURES_DIR = Path(__file__).parent


def get_fixture_path(filename: str) -> Path:
    """Return the absolute Path to a fixture file."""
    return FIXTURES_DIR / filename


def load_fixture_json(filename: str) -> dict[str, Any]:
    """Read a JSON fixture file and return parsed dict."""
    path = get_fixture_path(filename)
    with path.open("r", encoding="utf-8") as f:
        return cast(dict[str, Any], json.load(f))


def load_device(filename: str) -> DeviceInfo:
    """Load a DeviceInfo fixture model."""
    data = load_fixture_json(filename)
    return DeviceInfo.model_validate(data)


def load_stats(filename: str) -> Stats:
    """Load a Stats fixture model."""
    data = load_fixture_json(filename)
    return Stats.model_validate(data)


def load_manifest(filename: str) -> WorkloadManifest:
    """Load a WorkloadManifest fixture model."""
    data = load_fixture_json(filename)
    return WorkloadManifest.model_validate(data)


def load_link(filename: str) -> LinkQuality:
    """Load a LinkQuality fixture model."""
    data = load_fixture_json(filename)
    return LinkQuality.model_validate(data)


# Standard fixture filenames
ALL_DEVICE_FILES = [
    "device_windows_laptop.json",
    "device_macos_laptop.json",
    "device_low_spec_arm.json",
    "device_linux_gpu.json",
    "device_no_battery_desktop.json",
    "device_old_python.json",
    "device_low_battery_laptop.json",
    "device_offline_server.json",
]

ALL_STATS_FILES = [
    "stats_windows_laptop.json",
    "stats_macos_laptop.json",
    "stats_low_spec_arm.json",
    "stats_linux_gpu.json",
    "stats_no_battery_desktop.json",
    "stats_old_python.json",
    "stats_low_battery_laptop.json",
    "stats_offline_server.json",
]

ALL_MANIFEST_FILES = [
    "manifest_light_python.json",
    "manifest_heavy_ml.json",
    "manifest_x86_binary.json",
    "manifest_missing_library.json",
    "manifest_remote_only_gui.json",
]

ALL_LINK_FILES = [
    "link_cable.json",
    "link_good_wifi.json",
    "link_bad_wifi.json",
    "link_lossy.json",
]

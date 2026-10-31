"""Stats simulator and simulated profiles for demo / dev environments."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..core.context import Context

BUILTIN_PROFILES: dict[str, dict[str, Any]] = {
    "default": {
        "device": {
            "name": "Sim Laptop (x86_64)",
            "os": "linux",
            "arch": "x86_64",
            "cpuCores": 8,
            "ramMb": 16384,
            "gpu": None,
            "diskFreeMb": 200000,
            "runtimes": {"python": "3.11.9", "node": "22.14.0"},
            "libs": ["numpy", "sqlite3"],
        },
        "stats": {
            "cpuPct": 25.0,
            "memPct": 40.0,
            "memFreeMb": 9800,
            "diskFreeMb": 200000,
            "battery": {"pct": 85.0, "charging": False},
            "online": True,
        },
    },
    "arm64-lowspec": {
        "device": {
            "name": "Sim Board (arm64 low-spec)",
            "os": "linux",
            "arch": "arm64",
            "cpuCores": 4,
            "ramMb": 2048,
            "gpu": None,
            "diskFreeMb": 8000,
            "runtimes": {"python": "3.11.2"},
            "libs": ["sqlite3"],
        },
        "stats": {
            "cpuPct": 15.0,
            "memPct": 55.0,
            "memFreeMb": 900,
            "diskFreeMb": 8000,
            "battery": None,
            "online": True,
        },
    },
}


def resolve_sim_profile_name(name: str | None, port: int = 8765) -> str | None:
    """Resolve TELEPORT_SIM_PROFILE option, including dev:two alias."""
    if not name:
        return None
    name_clean = name.strip()
    if name_clean in ("dev:two", "dev_two"):
        # dev:two runs A on 8765 (default profile) and B on 8766 (arm64-lowspec profile)
        return "arm64-lowspec" if port == 8766 else "default"
    return name_clean


def get_active_profile(ctx: Context) -> dict[str, Any] | None:
    """Extract active simulation profile dict (device + stats) from Context or env."""
    if ctx.sim_profile is not None:
        return {
            "name": ctx.sim_profile.name,
            "device": dict(ctx.sim_profile.device),
            "stats": dict(ctx.sim_profile.stats),
        }

    profile_name = resolve_sim_profile_name(
        ctx.settings.simProfile or os.environ.get("TELEPORT_SIM_PROFILE"),
        port=ctx.settings.port,
    )
    if profile_name and profile_name in BUILTIN_PROFILES:
        return BUILTIN_PROFILES[profile_name]

    return None


class StatsSimulator:
    """Manages runtime partial Stats overrides per device, marking them simulated: True."""

    def __init__(self) -> None:
        self._overrides: dict[str, dict[str, Any]] = {}

    def set_override(self, device_id: str, partial_stats: dict[str, Any] | None) -> None:
        if partial_stats is None:
            self._overrides.pop(device_id, None)
        else:
            current = self._overrides.setdefault(device_id, {})
            current.update(partial_stats)

    def get_override(self, device_id: str) -> dict[str, Any] | None:
        return self._overrides.get(device_id)

    def clear(self, device_id: str | None = None) -> None:
        if device_id:
            self._overrides.pop(device_id, None)
        else:
            self._overrides.clear()

    def has_override(self, device_id: str) -> bool:
        return device_id in self._overrides

"""Agent settings. Static ones come from env (or CLI flags in __main__); prefs are editable via API."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

Mode = Literal["recommend", "auto"]

REPO_ROOT = Path(__file__).resolve().parents[3]
PROFILES_DIR = Path(__file__).resolve().parent / "sim_profiles"


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    host: str = "127.0.0.1"
    port: int = 8765
    home: Path = Path.home() / ".teleport"
    simProfile: str | None = None
    deviceName: str | None = None  # None: sim profile name, else hostname
    uiDist: Path = REPO_ROOT / "ui" / "dist"

    @classmethod
    def from_env(cls) -> Settings:
        env = os.environ
        values: dict[str, Any] = {}
        if v := env.get("TELEPORT_HOST"):
            values["host"] = v
        if v := env.get("TELEPORT_PORT"):
            values["port"] = int(v)
        if v := env.get("TELEPORT_HOME"):
            values["home"] = Path(v).expanduser().resolve()
        if v := env.get("TELEPORT_SIM_PROFILE"):
            values["simProfile"] = v
        if v := env.get("TELEPORT_NAME"):
            values["deviceName"] = v
        return cls(**values)


class Prefs(BaseModel):
    """User-editable settings served on GET/PUT /api/settings and saved in TELEPORT_HOME."""

    mode: Mode = "recommend"
    batteryLowPct: float = 20
    cpuHighPct: float = 90
    memHighPct: float = 90
    # Migration transfer. Chunks travel base64 in one peer frame, so keep them well under 1 MiB.
    chunkSizeKb: int = Field(256, ge=16, le=512)
    # Pre-copy: every N seconds send changed checkpoints of running workloads ahead (0 = off) to
    # precopyTargetId, or to the first connected peer when it is empty.
    precopyIntervalS: float = Field(0, ge=0)
    precopyTargetId: str = ""
    # How often leases are exchanged with connected peers (split-brain guard).
    leaseSyncS: float = Field(5, ge=0.1, le=300)

    @classmethod
    def load(cls, home: Path) -> Prefs:
        path = home / "prefs.json"
        return cls.model_validate_json(path.read_text("utf-8")) if path.exists() else cls()

    def save(self, home: Path) -> None:
        (home / "prefs.json").write_text(self.model_dump_json(indent=2), "utf-8")


class SimProfile(BaseModel):
    """Simulated device profile: partial DeviceInfo and Stats fields applied over real values."""

    name: str
    device: dict[str, Any] = {}
    stats: dict[str, Any] = {}


def load_sim_profile(name: str | None) -> SimProfile | None:
    if not name:
        return None
    path = PROFILES_DIR / f"{name}.yaml"
    if not path.exists():
        known = ", ".join(sorted(p.stem for p in PROFILES_DIR.glob("*.yaml")))
        raise ValueError(f"unknown TELEPORT_SIM_PROFILE {name!r} (known: {known})")
    data = yaml.safe_load(path.read_text("utf-8")) or {}
    return SimProfile(name=name, **data)


def load_device_id(home: Path) -> str:
    """Stable per-home device id, created on first run."""
    path = home / "device.json"
    if path.exists():
        return str(json.loads(path.read_text("utf-8"))["id"])
    import uuid

    device_id = f"dev-{uuid.uuid4().hex[:12]}"
    path.write_text(json.dumps({"id": device_id}), "utf-8")
    return device_id

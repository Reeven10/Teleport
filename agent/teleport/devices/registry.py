"""Persistent registry of known devices (local and peers) stored in TELEPORT_HOME/devices.json."""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from contract.contract import DeviceInfo

log = logging.getLogger("teleport.devices.registry")


class DeviceRegistry:
    """Manages DeviceInfo storage and timestamps, persisted to devices.json."""

    def __init__(self, home: Path) -> None:
        self.home = home
        self.file_path = home / "devices.json"
        self._devices: dict[str, DeviceInfo] = {}
        self._last_seen: dict[str, float] = {}
        self.load()

    def load(self) -> None:
        """Load registered devices from TELEPORT_HOME/devices.json if present."""
        if not self.file_path.exists():
            return
        try:
            raw = json.loads(self.file_path.read_text("utf-8"))
            entries: dict[str, Any] = {}
            if isinstance(raw, dict):
                if "devices" in raw and isinstance(raw["devices"], dict):
                    entries = raw["devices"]
                else:
                    entries = raw
            elif isinstance(raw, list):
                for item in raw:
                    if isinstance(item, dict) and "id" in item:
                        entries[item["id"]] = {"device": item, "lastSeen": time.time()}

            for dev_id, item in entries.items():
                if isinstance(item, dict):
                    dev_data = item.get("device", item)
                    last_seen = float(item.get("lastSeen", time.time()))
                    try:
                        dev = DeviceInfo.model_validate(dev_data)
                        self._devices[dev.id] = dev
                        self._last_seen[dev.id] = last_seen
                    except Exception as e:
                        log.debug("failed to deserialize registry item %s: %s", dev_id, e)
        except Exception as e:
            log.warning("failed to load %s: %s", self.file_path, e)

    def save(self) -> None:
        """Persist registered devices atomically to TELEPORT_HOME/devices.json."""
        self.home.mkdir(parents=True, exist_ok=True)
        data = {
            "devices": {
                dev_id: {
                    "device": self._devices[dev_id].model_dump(),
                    "lastSeen": self._last_seen.get(dev_id, time.time()),
                }
                for dev_id in self._devices
            }
        }
        temp_path = self.home / f"devices.json.tmp.{os.getpid()}"
        try:
            temp_path.write_text(json.dumps(data, indent=2), "utf-8")
            temp_path.replace(self.file_path)
        except Exception:
            # Fallback direct write on systems where replace might fail across mounts/locks
            self.file_path.write_text(json.dumps(data, indent=2), "utf-8")
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    def upsert(self, device: DeviceInfo, last_seen: float | None = None) -> None:
        """Add or update a device entry and flush to disk."""
        self._devices[device.id] = device
        self._last_seen[device.id] = last_seen if last_seen is not None else time.time()
        self.save()

    def get(self, device_id: str) -> DeviceInfo | None:
        return self._devices.get(device_id)

    def get_last_seen(self, device_id: str) -> float | None:
        return self._last_seen.get(device_id)

    def list_devices(self, local_id: str | None = None) -> list[DeviceInfo]:
        """Return local device first, followed by every known peer sorted by last seen descending."""
        result: list[DeviceInfo] = []
        if local_id and local_id in self._devices:
            result.append(self._devices[local_id])

        peers = [
            (dev, self._last_seen.get(dev.id, 0.0))
            for dev_id, dev in self._devices.items()
            if dev_id != local_id
        ]
        peers.sort(key=lambda item: item[1], reverse=True)
        result.extend(dev for dev, _ in peers)
        return result

    def remove(self, device_id: str) -> bool:
        """Remove a device from the registry."""
        if device_id in self._devices:
            del self._devices[device_id]
            self._last_seen.pop(device_id, None)
            self.save()
            return True
        return False

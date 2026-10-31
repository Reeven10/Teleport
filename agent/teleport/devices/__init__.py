"""Device service (P2).

Provides local DeviceInfo capability probe, background Stats sampler (1s, non-blocking),
simulator overrides and profiles, and persistent device registry (TELEPORT_HOME/devices.json).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from contract.contract import DeviceService

from .service import DeviceServiceImpl

if TYPE_CHECKING:
    from ..core.context import Context


def create_device_service(ctx: Context) -> DeviceService:
    """Entry point for P2 DeviceService satisfying contract/contract.py Protocol."""
    return DeviceServiceImpl(ctx)


__all__ = ["DeviceService", "DeviceServiceImpl", "create_device_service"]

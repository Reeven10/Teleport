"""Link quality models, extended metrics, and fault injection configuration."""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from typing import Any

from contract.contract import LinkQuality


class ExtendedLinkQuality(LinkQuality):
    """Extended LinkQuality supporting online state and simulation indicator."""

    online: bool = True
    simulated: bool | None = None


@dataclass
class FaultInjector:
    """Configurable fault injection for network simulations and dev testing."""

    extra_latency_ms: float = 0.0
    drop_rate: float = 0.0  # 0.0 to 1.0 packet drop probability
    bandwidth_cap_mbps: float | None = None

    @property
    def is_active(self) -> bool:
        """True if any simulated fault is actively configured."""
        return self.extra_latency_ms > 0.0 or self.drop_rate > 0.0 or self.bandwidth_cap_mbps is not None

    def should_drop(self) -> bool:
        """Determine whether the current packet should be dropped."""
        if self.drop_rate <= 0.0:
            return False
        return random.random() < self.drop_rate

    async def apply_delay(self) -> None:
        """Asynchronously inject configured network latency."""
        if self.extra_latency_ms > 0.0:
            await asyncio.sleep(self.extra_latency_ms / 1000.0)

    def apply_bandwidth_cap(self, measured_mbps: float) -> float:
        """Apply bandwidth cap if configured."""
        if self.bandwidth_cap_mbps is not None:
            return min(measured_mbps, self.bandwidth_cap_mbps)
        return measured_mbps

    def configure(
        self,
        latency_ms: float = 0.0,
        drop_rate: float = 0.0,
        bandwidth_cap_mbps: float | None = None,
    ) -> None:
        """Update fault injection parameters."""
        self.extra_latency_ms = max(0.0, latency_ms)
        self.drop_rate = max(0.0, min(1.0, drop_rate))
        self.bandwidth_cap_mbps = max(0.1, bandwidth_cap_mbps) if bandwidth_cap_mbps is not None else None

    def clear(self) -> None:
        """Reset all fault injection parameters to normal."""
        self.extra_latency_ms = 0.0
        self.drop_rate = 0.0
        self.bandwidth_cap_mbps = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "extraLatencyMs": self.extra_latency_ms,
            "dropRate": self.drop_rate,
            "bandwidthCapMbps": self.bandwidth_cap_mbps,
            "isActive": self.is_active,
        }

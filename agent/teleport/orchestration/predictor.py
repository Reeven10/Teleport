"""Battery drain prediction and time-to-empty estimation (P3).

Maintains a sliding window of battery telemetry, fits linear regression
over discharging periods, rejects noise, and projects time to empty (TTE).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class BatterySample:
    ts: float
    pct: float
    charging: bool


class BatteryPredictor:
    """Predicts battery exhaustion by fitting ordinary least squares over discharging history."""

    def __init__(self, window_sec: float = 600.0) -> None:
        # Retention window (default 10 minutes = 600 seconds)
        self.window_sec = window_sec
        self._history: dict[str, list[BatterySample]] = {}

    def add_reading(self, device_id: str, ts: float, pct: float, charging: bool) -> None:
        """Add a new battery telemetry sample and prune readings older than window_sec."""
        if device_id not in self._history:
            self._history[device_id] = []
        samples = self._history[device_id]
        samples.append(BatterySample(ts=ts, pct=pct, charging=charging))

        # Prune older than window_sec relative to current timestamp
        cutoff = ts - self.window_sec
        self._history[device_id] = [s for s in samples if s.ts >= cutoff]

    def clear(self, device_id: str | None = None) -> None:
        """Clear telemetry history for a specific device or all devices."""
        if device_id is not None:
            self._history.pop(device_id, None)
        else:
            self._history.clear()

    def predict_tte_seconds(self, device_id: str, current_ts: float) -> float | None:
        """Estimate seconds remaining until battery reaches 0%.

        Returns None if:
        - device is currently charging
        - fewer than 3 samples exist
        - observation duration is under 10 seconds
        - battery is flat/increasing (slope >= 0)
        - telemetry is overly noisy (low R^2 on large spread)
        """
        samples = self._history.get(device_id, [])
        if not samples:
            return None

        # If currently charging, device is not discharging
        latest = samples[-1]
        if latest.charging:
            return None

        # Filter strictly to discharging samples
        discharging = [s for s in samples if not s.charging]
        if len(discharging) < 3:
            return None

        time_span = discharging[-1].ts - discharging[0].ts
        if time_span < 10.0:
            return None

        # Ordinary Least Squares (OLS): pct(t) = a + b * t
        n = len(discharging)
        mean_t = sum(s.ts for s in discharging) / n
        mean_p = sum(s.pct for s in discharging) / n

        denom = sum((s.ts - mean_t) ** 2 for s in discharging)
        if denom <= 0.0:
            return None

        numer = sum((s.ts - mean_t) * (s.pct - mean_p) for s in discharging)
        slope = numer / denom  # % per second

        # If slope is non-negative, battery is steady or rising (not draining)
        if slope >= -1e-5:
            return None

        # Check noise / variance of residuals
        intercept = mean_p - slope * mean_t
        ss_res = sum((s.pct - (intercept + slope * s.ts)) ** 2 for s in discharging)
        ss_tot = sum((s.pct - mean_p) ** 2 for s in discharging)

        if ss_tot > 0.05:
            r_squared = 1.0 - (ss_res / ss_tot)
            if r_squared < 0.6:  # Reject erratic data
                return None

        drain_rate = -slope  # % per second
        current_pct = latest.pct

        if current_pct <= 0.0:
            return 0.0

        return current_pct / drain_rate

    def is_predicted_trigger(
        self,
        device_id: str,
        current_ts: float,
        threshold_sec: float = 900.0,
        est_transfer_sec: float = 0.0,
        margin_sec: float = 60.0,
    ) -> bool:
        """Determine if predicted trigger condition is met."""
        tte = self.predict_tte_seconds(device_id, current_ts)
        if tte is None:
            return False

        # Under threshold (default 15 min = 900s) OR shorter than transfer time + margin
        if tte < threshold_sec:
            return True
        if est_transfer_sec > 0.0 and tte < (est_transfer_sec + margin_sec):
            return True

        return False


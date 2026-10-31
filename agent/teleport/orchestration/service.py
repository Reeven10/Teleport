"""Orchestrator service implementation (P3).

Monitors live telemetry and link events, detects resource pressure and battery trends,
evaluates target feasibility, and generates recommendations or initiates auto-migration.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from typing import Any

from contract.contract import (
    Decision,
    DecisionLog,
    DecisionLoggedEvent,
    DeviceInfo,
    LinkQuality,
    LinkUpdateEvent,
    Recommendation,
    RecommendationEvent,
    Stats,
    StatsUpdateEvent,
    Trigger,
    WorkloadManifest,
)

from ..core.context import Context
from ..feasibility.engine import best_target
from .predictor import BatteryPredictor

log = logging.getLogger("teleport.orchestrator")


class OrchestratorService:
    """Watches telemetry and link events, publishes recommendations, and triggers auto-migration."""

    def __init__(
        self,
        ctx: Context,
        clock: Callable[[], float] | None = None,
        battery_predictor: BatteryPredictor | None = None,
    ) -> None:
        self.ctx = ctx
        self._clock = clock or time.time
        self.predictor = battery_predictor or BatteryPredictor(window_sec=600.0)

        # Trigger monitoring windows and timestamps
        self._cpu_pressure_start: dict[str, float] = {}
        self._mem_pressure_start: dict[str, float] = {}
        self._link_down_start: dict[str, float] = {}

        # Hysteresis: tracks currently active (device_id, trigger) pairs
        self._active_triggers: set[tuple[str, Trigger]] = set()

        # Cooldown per workload_id: workload_id -> timestamp when cooldown expires
        self._workload_cooldown: dict[str, float] = {}

        # Latest recommendations: workload_id -> Recommendation
        self._recommendations: dict[str, Recommendation] = {}

        self._unsub_callbacks: list[Callable[[], None]] = []

    def now(self) -> float:
        """Return the current timestamp from the clock (supports fake clock for deterministic testing)."""
        return self._clock()

    # ------------------------------------------------------------ Lifecycle

    async def startup(self) -> None:
        """Register event bus subscriptions for telemetry and link updates."""
        if hasattr(self.ctx, "bus"):
            self._unsub_callbacks.append(self.ctx.bus.subscribe(StatsUpdateEvent, self._handle_stats_update))
            self._unsub_callbacks.append(self.ctx.bus.subscribe(LinkUpdateEvent, self._handle_link_update))

    async def shutdown(self) -> None:
        """Unsubscribe handlers and clear tracking caches."""
        for unsub in self._unsub_callbacks:
            try:
                unsub()
            except Exception:
                pass
        self._unsub_callbacks.clear()

    # ------------------------------------------------------------ Protocol API

    def recommendations(self) -> list[Recommendation]:
        """Return the latest active recommendations per workload."""
        return list(self._recommendations.values())

    # ------------------------------------------------------------ Configuration Accessors

    @property
    def mode(self) -> str:
        if hasattr(self.ctx, "prefs") and hasattr(self.ctx.prefs, "mode"):
            return str(self.ctx.prefs.mode)
        return "recommend"

    @property
    def battery_low_pct(self) -> float:
        if hasattr(self.ctx, "prefs") and hasattr(self.ctx.prefs, "batteryLowPct"):
            return float(self.ctx.prefs.batteryLowPct)
        return 20.0

    @property
    def cpu_high_pct(self) -> float:
        if hasattr(self.ctx, "prefs") and hasattr(self.ctx.prefs, "cpuHighPct"):
            return float(self.ctx.prefs.cpuHighPct)
        return 90.0

    @property
    def mem_high_pct(self) -> float:
        if hasattr(self.ctx, "prefs") and hasattr(self.ctx.prefs, "memHighPct"):
            return float(self.ctx.prefs.memHighPct)
        return 90.0

    @property
    def cpu_window_sec(self) -> float:
        return 20.0

    @property
    def mem_window_sec(self) -> float:
        return 20.0

    @property
    def connectivity_window_sec(self) -> float:
        return 3.0

    @property
    def predicted_threshold_sec(self) -> float:
        return 900.0  # 15 minutes

    @property
    def cooldown_sec(self) -> float:
        return 120.0  # 2 minutes

    # ------------------------------------------------------------ Telemetry Ingestion

    async def _handle_stats_update(self, event: StatsUpdateEvent) -> None:
        stats = event.stats
        await self.process_stats(stats)

    async def process_stats(self, stats: Stats) -> None:
        """Process incoming device stats and evaluate battery, CPU, and memory triggers."""
        ts = stats.ts if getattr(stats, "ts", 0.0) > 0.0 else self.now()
        dev_id = stats.deviceId

        # 1. Update battery prediction history
        if stats.battery is not None:
            self.predictor.add_reading(
                device_id=dev_id,
                ts=ts,
                pct=stats.battery.pct,
                charging=stats.battery.charging,
            )

        # 2. Check PREDICTED trigger
        is_pred = self.predictor.is_predicted_trigger(
            device_id=dev_id,
            current_ts=ts,
            threshold_sec=self.predicted_threshold_sec,
        )
        if is_pred:
            if (dev_id, "predicted") not in self._active_triggers:
                self._active_triggers.add((dev_id, "predicted"))
                await self._trigger_fired("predicted", dev_id, ts)
        else:
            self._active_triggers.discard((dev_id, "predicted"))

        # 3. Check LOW_BATTERY trigger
        is_low_bat = (
            stats.battery is not None
            and not stats.battery.charging
            and stats.battery.pct < self.battery_low_pct
        )
        if is_low_bat:
            if (dev_id, "low_battery") not in self._active_triggers:
                self._active_triggers.add((dev_id, "low_battery"))
                await self._trigger_fired("low_battery", dev_id, ts)
        else:
            # Hysteresis clearing: charging or pct >= threshold
            if stats.battery is None or stats.battery.charging or stats.battery.pct >= self.battery_low_pct:
                self._active_triggers.discard((dev_id, "low_battery"))

        # 4. Check CPU_PRESSURE trigger (sustained >= 90% for 20s)
        if stats.cpuPct >= self.cpu_high_pct:
            if dev_id not in self._cpu_pressure_start:
                self._cpu_pressure_start[dev_id] = ts
            elif (ts - self._cpu_pressure_start[dev_id]) >= self.cpu_window_sec:
                if (dev_id, "cpu_pressure") not in self._active_triggers:
                    self._active_triggers.add((dev_id, "cpu_pressure"))
                    await self._trigger_fired("cpu_pressure", dev_id, ts)
        else:
            self._cpu_pressure_start.pop(dev_id, None)
            self._active_triggers.discard((dev_id, "cpu_pressure"))

        # 5. Check MEMORY_PRESSURE trigger (sustained >= 90% for 20s)
        if stats.memPct >= self.mem_high_pct:
            if dev_id not in self._mem_pressure_start:
                self._mem_pressure_start[dev_id] = ts
            elif (ts - self._mem_pressure_start[dev_id]) >= self.mem_window_sec:
                if (dev_id, "memory_pressure") not in self._active_triggers:
                    self._active_triggers.add((dev_id, "memory_pressure"))
                    await self._trigger_fired("memory_pressure", dev_id, ts)
        else:
            self._mem_pressure_start.pop(dev_id, None)
            self._active_triggers.discard((dev_id, "memory_pressure"))

    async def _handle_link_update(self, event: LinkUpdateEvent) -> None:
        link = event.link
        await self.process_link(link)

    async def process_link(self, link: LinkQuality) -> None:
        """Process link quality events and detect connectivity loss sustained for 3 seconds."""
        ts = link.ts if getattr(link, "ts", 0.0) > 0.0 else self.now()
        peer_id = link.peerId

        # Link is considered down if 100% loss or zero throughput
        is_down = getattr(link, "lossPct", 0.0) >= 100.0 or getattr(link, "mbps", 1.0) <= 0.0

        if is_down:
            if peer_id not in self._link_down_start:
                self._link_down_start[peer_id] = ts
            elif (ts - self._link_down_start[peer_id]) >= self.connectivity_window_sec:
                key = (peer_id, "connectivity_lost")
                if key not in self._active_triggers:
                    self._active_triggers.add(key)
                    # Trigger action for workloads on this device or local device
                    await self._trigger_fired("connectivity_lost", peer_id, ts)
        else:
            self._link_down_start.pop(peer_id, None)
            self._active_triggers.discard((peer_id, "connectivity_lost"))

    async def record_user_command(self, workload_id: str, target_id: str) -> None:
        """Log a manual user-commanded migration trigger."""
        ts = self.now()
        log_entry = DecisionLog(
            id=f"dec-{uuid.uuid4().hex[:12]}",
            ts=ts,
            workloadId=workload_id,
            trigger="user_command",
            decision="MIGRATE",
            reasons=[],
        )
        if hasattr(self.ctx, "bus"):
            await self.ctx.bus.publish(DecisionLoggedEvent(log=log_entry))

    # ------------------------------------------------------------ Trigger Firing Logic

    def _get_service(self, name: str) -> Any:
        """Safely retrieve a service from context without raising if not registered."""
        try:
            return getattr(self.ctx, name)
        except (RuntimeError, AttributeError):
            return None

    def _get_running_workloads(self, device_id: str) -> list[WorkloadManifest]:
        """Locate workloads actively executing on the specified device."""
        results: list[WorkloadManifest] = []

        # Check workloads runner if available
        workloads_svc = self._get_service("workloads")
        if workloads_svc is not None:
            try:
                runs = workloads_svc.runs()
                if runs:
                    running_ids = {r.workloadId for r in runs if r.state in ("running", "paused")}
                    for m in workloads_svc.list():
                        if m.id in running_ids:
                            results.append(m)
                    if results:
                        return results
                else:
                    results = workloads_svc.list()
                    if results:
                        return results
            except Exception:
                pass

        # Fallback to migration manager workload registry
        migration_svc = self._get_service("migration")
        if migration_svc is not None and hasattr(migration_svc, "workloads"):
            try:
                results = migration_svc.workloads()
            except Exception:
                pass

        return results

    def _is_migration_active(self, workload_id: str) -> bool:
        """Check if an active migration is currently running for this workload."""
        migration_svc = self._get_service("migration")
        if migration_svc is not None and hasattr(migration_svc, "list"):
            try:
                for mig in migration_svc.list():
                    if mig.workloadId == workload_id:
                        if mig.phase not in ("COMPLETED", "FAILED", "ROLLED_BACK", "IDLE"):
                            return True
            except Exception:
                pass
        return False

    def _is_in_cooldown(self, workload_id: str, current_ts: float) -> bool:
        """Check if the workload is within the 2-minute post-action cooldown window."""
        exp = self._workload_cooldown.get(workload_id, 0.0)
        return current_ts < exp

    async def _trigger_fired(self, trigger: Trigger, device_id: str, ts: float) -> None:
        """Evaluate running workloads on the triggered device, pick best target, and emit recommendation."""
        workloads = self._get_running_workloads(device_id)
        if not workloads:
            log.info("Trigger %s fired for device %s, but no active workloads found", trigger, device_id)
            return

        # Obtain local source device info
        devices_svc = self._get_service("devices")
        source_device: DeviceInfo
        if devices_svc is not None and hasattr(devices_svc, "local_info"):
            source_device = devices_svc.local_info()
        else:
            source_device = DeviceInfo(
                id=device_id,
                name="LocalDevice",
                os="linux",
                arch="x86_64",
                cpuCores=4,
                ramMb=8192,
                gpu=None,
                diskFreeMb=50000,
                runtimes={"python": "3.11.9"},
                libs=[],
                addrs=[],
                agentVersion="0.1.0",
            )

        # Collect candidate peers
        candidates: list[DeviceInfo] = []
        peers_svc = self._get_service("peers")
        if peers_svc is not None and hasattr(peers_svc, "list_peers"):
            candidates.extend(peers_svc.list_peers())
        elif devices_svc is not None and hasattr(devices_svc, "list_devices"):
            candidates.extend([d for d in devices_svc.list_devices() if d.id != source_device.id])

        stats_map: dict[str, Stats] = {}
        links_map: dict[str, LinkQuality] = {}

        for cand in candidates:
            if devices_svc is not None and hasattr(devices_svc, "latest_stats"):
                st = devices_svc.latest_stats(cand.id)
                if st is not None:
                    stats_map[cand.id] = st
            if peers_svc is not None and hasattr(peers_svc, "link_quality"):
                lk = peers_svc.link_quality(cand.id)
                if lk is not None:
                    links_map[cand.id] = lk

        is_auto = self.mode == "auto"

        for w in workloads:
            # 1. No action while a migration is already running for that workload
            if self._is_migration_active(w.id):
                log.info("Workload %s has an active migration; suppressing trigger %s", w.id, trigger)
                continue

            # 2. 2-minute cooldown per workload after any action
            if self._is_in_cooldown(w.id, ts):
                log.info("Workload %s is in cooldown; suppressing trigger %s", w.id, trigger)
                continue

            # 3. Evaluate every paired peer and select the best target
            best = best_target(
                manifest=w,
                source=source_device,
                candidates=candidates,
                candidate_stats=stats_map,
                candidate_links=links_map,
            )

            target_id: str | None = None
            decision: Decision = "STAY"
            reasons = []

            if best is not None:
                chosen_device, eval_result = best
                target_id = chosen_device.id
                decision = eval_result.decision
                reasons = eval_result.reasons

            # 4. Create and publish Recommendation
            rec = Recommendation(
                workloadId=w.id,
                trigger=trigger,
                targetId=target_id,
                decision=decision,
                reasons=reasons,
                auto=is_auto,
                ts=ts,
            )
            self._recommendations[w.id] = rec

            # Record decision log entry
            log_entry = DecisionLog(
                id=f"dec-{uuid.uuid4().hex[:12]}",
                ts=ts,
                workloadId=w.id,
                trigger=trigger,
                decision=decision,
                reasons=reasons,
            )

            # Publish to event bus
            if hasattr(self.ctx, "bus"):
                await self.ctx.bus.publish(RecommendationEvent(rec=rec))
                await self.ctx.bus.publish(DecisionLoggedEvent(log=log_entry))

            history_svc = self._get_service("history")
            if history_svc is not None and hasattr(history_svc, "log_decision"):
                try:
                    await history_svc.log_decision(log_entry)
                except Exception:
                    pass

            # 5. Apply action cooldown (2 minutes)
            self._workload_cooldown[w.id] = ts + self.cooldown_sec

            # 6. Execute action in auto mode
            if is_auto and target_id:
                migration_svc = self._get_service("migration")
                remote_svc = self._get_service("remote")
                if decision == "MIGRATE" and migration_svc is not None:
                    log.info("Auto mode: starting migration of %s to %s", w.id, target_id)
                    try:
                        await migration_svc.start(w.id, target_id, trigger)
                    except Exception as err:
                        log.error("Failed to auto-start migration for %s: %s", w.id, err)

                elif decision == "REMOTE_ACCESS" and remote_svc is not None:
                    log.info("Auto mode: initiating remote access for %s to %s", w.id, target_id)
                    try:
                        await remote_svc.start_session(w.id, target_id)
                    except Exception as err:
                        log.error("Failed to auto-start remote access for %s: %s", w.id, err)

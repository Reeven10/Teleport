"""Shared Context handed to every module entry function: bus, settings and the service registry."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from contract.contract import (
    AuthorityService,
    DeviceService,
    FeasibilityEngine,
    HistoryStore,
    MigrationManager,
    Orchestrator,
    PeerLink,
    RemoteService,
    Service,
)

from .bus import EventBus
from .settings import Prefs, Settings, SimProfile

if TYPE_CHECKING:
    from ..migration.store import CheckpointStore
    from .workloads import WorkloadRunner


class Context:
    def __init__(
        self,
        settings: Settings,
        device_id: str,
        sim_profile: SimProfile | None = None,
        prefs: Prefs | None = None,
    ) -> None:
        self.settings = settings
        self.device_id = device_id
        self.sim_profile = sim_profile
        self.prefs = prefs or Prefs()
        self.bus = EventBus()
        self._services: dict[str, Service] = {}

    def register(self, name: str, service: Service) -> None:
        self._services[name] = service

    def services(self) -> list[tuple[str, Service]]:
        """Registered services in registration (= start) order."""
        return list(self._services.items())

    def _get(self, name: str) -> Service:
        try:
            return self._services[name]
        except KeyError:
            raise RuntimeError(f"service {name!r} is not registered yet") from None

    @property
    def workloads(self) -> WorkloadRunner:
        """Workload registry and runner (core): list(), runs(), start/pause/resume/terminate."""
        return cast("WorkloadRunner", self._get("workloads"))

    @property
    def checkpoints(self) -> CheckpointStore:
        return self.workloads.store

    @property
    def authority(self) -> AuthorityService:
        return cast(AuthorityService, self._get("authority"))

    @property
    def history(self) -> HistoryStore:
        return cast(HistoryStore, self._get("history"))

    @property
    def devices(self) -> DeviceService:
        return cast(DeviceService, self._get("devices"))

    @property
    def peers(self) -> PeerLink:
        return cast(PeerLink, self._get("peers"))

    @property
    def feasibility(self) -> FeasibilityEngine:
        return cast(FeasibilityEngine, self._get("feasibility"))

    @property
    def migration(self) -> MigrationManager:
        return cast(MigrationManager, self._get("migration"))

    @property
    def orchestrator(self) -> Orchestrator:
        return cast(Orchestrator, self._get("orchestrator"))

    @property
    def remote(self) -> RemoteService:
        return cast(RemoteService, self._get("remote"))

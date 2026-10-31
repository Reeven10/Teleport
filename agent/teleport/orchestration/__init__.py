"""Orchestration module (P3).

Monitors live stats and link quality, evaluates battery trend predictions,
and publishes recommendations or triggers automated migrations.
"""

from __future__ import annotations

from ..core.context import Context
from .predictor import BatteryPredictor
from .service import OrchestratorService

__all__ = ["OrchestratorService", "BatteryPredictor", "create_orchestrator"]


def create_orchestrator(ctx: Context) -> OrchestratorService:
    return OrchestratorService(ctx)

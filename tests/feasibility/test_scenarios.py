"""Automated test suite verifying the 34 feasibility scenarios in scenarios.yaml (P3)."""

from __future__ import annotations

import pytest
import yaml

from dev.feasibility.runner import (
    SCENARIOS_PATH,
    _resolve_device,
    _resolve_link,
    _resolve_manifest,
    _resolve_stats,
)
from teleport.feasibility.engine import evaluate_feasibility


def load_all_scenarios() -> list[dict]:
    with open(SCENARIOS_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("scenarios", [])


ALL_SCENARIOS = load_all_scenarios()


@pytest.mark.parametrize("sc", ALL_SCENARIOS, ids=lambda sc: sc["id"])
def test_scenario_passes(sc: dict) -> None:
    manifest = _resolve_manifest(sc["manifest"])
    source = _resolve_device(sc["source"])
    target = _resolve_device(sc["target"])
    link = _resolve_link(sc.get("link"))
    target_stats = _resolve_stats(sc.get("stats"))
    source_stats = _resolve_stats(sc.get("source_stats"))
    snapshot_size_mb = float(sc.get("snapshot_size_mb", 0.0))

    result = evaluate_feasibility(
        manifest=manifest,
        source=source,
        target=target,
        link=link,
        target_stats=target_stats,
        source_stats=source_stats,
        snapshot_size_mb=snapshot_size_mb,
    )

    actual_decision = str(result.decision)
    exp_decision = sc["expected_decision"]
    assert actual_decision == exp_decision, (
        f"Scenario {sc['id']} expected decision {exp_decision}, got {actual_decision}. "
        f"Reasons: {[r.text for r in result.reasons]}"
    )

    actual_blocks = [r.code for r in result.reasons if r.severity == "block"]
    exp_blocking_codes = sc.get("expected_blocking_codes", [])
    for exp_code in exp_blocking_codes:
        assert any(exp_code in b for b in actual_blocks), (
            f"Scenario {sc['id']} expected blocking code containing '{exp_code}', "
            f"got actual blocks: {actual_blocks}"
        )

"""Tests for feasibility explanation formatting and ordering (P3)."""

from __future__ import annotations

import time

from contract.contract import Decision, FeasibilityResult, Reason
from teleport.feasibility.explain import explain


def make_result(
    decision: Decision,
    reasons: list[Reason],
) -> FeasibilityResult:
    return FeasibilityResult(
        workloadId="w-1",
        sourceId="dev-src",
        targetId="dev-tgt",
        decision=decision,
        reasons=reasons,
        estTransferSec=2.5,
        estInterruptionMs=150,
        ts=time.time(),
    )


class TestFeasibilityExplain:
    def test_ordering_blocks_warnings_passes(self) -> None:
        reasons = [
            Reason(code="r1", severity="pass", text="Pass 1: RAM OK."),
            Reason(code="r2", severity="warn", text="Warn 1: High latency."),
            Reason(code="r3", severity="block", text="Block 1: CPU arch mismatch."),
            Reason(code="r4", severity="pass", text="Pass 2: OS OK."),
            Reason(code="r5", severity="block", text="Block 2: Disk full."),
            Reason(code="r6", severity="warn", text="Warn 2: Battery low."),
        ]
        result = make_result("STAY", reasons)
        exp = explain(result)

        assert exp.decision == "STAY"
        assert "Migration blocked" in exp.headline
        # Verify strict order: blocks first, then warnings, then passes
        assert len(exp.bullets) == 6
        assert exp.bullets[0] == "Block 1: CPU arch mismatch."
        assert exp.bullets[1] == "Block 2: Disk full."
        assert exp.bullets[2] == "Warn 1: High latency."
        assert exp.bullets[3] == "Warn 2: Battery low."
        assert exp.bullets[4] == "Pass 1: RAM OK."
        assert exp.bullets[5] == "Pass 2: OS OK."

    def test_headline_migrate_clean(self) -> None:
        reasons = [
            Reason(code="decision_summary", severity="pass", text="Feasibility decision: MIGRATE."),
            Reason(code="r1", severity="pass", text="RAM OK."),
            Reason(code="r2", severity="pass", text="OS OK."),
        ]
        result = make_result("MIGRATE", reasons)
        exp = explain(result)

        assert exp.headline == "Workload can be migrated safely"
        assert exp.bullets == ["RAM OK.", "OS OK."]

    def test_headline_migrate_with_warnings(self) -> None:
        reasons = [
            Reason(code="r1", severity="warn", text="Target battery is 25% (discharging)."),
            Reason(code="r2", severity="pass", text="RAM OK."),
        ]
        result = make_result("MIGRATE", reasons)
        exp = explain(result)

        assert exp.headline == "Migration feasible with 1 warning"
        assert exp.bullets[0] == "Target battery is 25% (discharging)."
        assert exp.bullets[1] == "RAM OK."

    def test_headline_remote_access(self) -> None:
        reasons = [
            Reason(code="r1", severity="block", text="Runtime version mismatch: Python 3.9 < 3.11."),
            Reason(code="r2", severity="pass", text="Link streaming capable."),
        ]
        result = make_result("REMOTE_ACCESS", reasons)
        exp = explain(result)

        assert "remote access recommended" in exp.headline
        assert exp.bullets[0] == "Runtime version mismatch: Python 3.9 < 3.11."
        assert exp.bullets[1] == "Link streaming capable."

    def test_to_dict_and_str(self) -> None:
        reasons = [
            Reason(code="r1", severity="pass", text="All systems go."),
        ]
        result = make_result("MIGRATE", reasons)
        exp = explain(result)

        data = exp.to_dict()
        assert data["headline"] == exp.headline
        assert data["bullets"] == ["All systems go."]

        text = str(exp)
        assert exp.headline in text
        assert "- All systems go." in text

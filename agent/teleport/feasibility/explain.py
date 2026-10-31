"""Feasibility explanation generator (P3).

Transforms a FeasibilityResult into a clear headline and ordered plain-English
bullet points (blocks first, then warnings, then passes) for the dashboard and history.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from contract.contract import FeasibilityResult, Reason


class FeasibilityExplanation(BaseModel):
    """Structured explanation of a feasibility decision."""

    headline: str
    bullets: list[str] = Field(default_factory=list)
    decision: str
    blocks: list[Reason] = Field(default_factory=list)
    warnings: list[Reason] = Field(default_factory=list)
    passes: list[Reason] = Field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert explanation to a JSON-serializable dictionary."""
        return self.model_dump()

    def __str__(self) -> str:
        lines = [self.headline]
        for bullet in self.bullets:
            lines.append(f"- {bullet}")
        return "\n".join(lines)


def explain(result: FeasibilityResult) -> FeasibilityExplanation:
    """Generate a headline and prioritized bullet points from a FeasibilityResult.

    Order of bullets is strictly by importance:
    1. Blocks (critical obstacles preventing direct migration)
    2. Warnings (advisories that do not prevent execution)
    3. Passes (satisfied requirements)
    """
    decision_val = str(result.decision)

    blocks: list[Reason] = []
    warnings: list[Reason] = []
    passes: list[Reason] = []

    for r in result.reasons:
        if r.code == "decision_summary":
            continue
        if r.severity == "block":
            blocks.append(r)
        elif r.severity == "warn":
            warnings.append(r)
        else:
            passes.append(r)

    # Determine plain-English headline
    if decision_val == "MIGRATE":
        if warnings:
            count = len(warnings)
            suffix = "s" if count > 1 else ""
            headline = f"Migration feasible with {count} warning{suffix}"
        else:
            headline = "Workload can be migrated safely"
    elif decision_val == "REMOTE_ACCESS":
        headline = "Direct migration blocked; remote access recommended"
    elif decision_val == "STAY":
        headline = "Migration blocked; workload must stay on current device"
    else:
        headline = f"Feasibility decision: {decision_val}"

    # Bullets strictly ordered by importance: blocks -> warnings -> passes
    bullets: list[str] = (
        [r.text for r in blocks]
        + [r.text for r in warnings]
        + [r.text for r in passes]
    )

    # If no checks were evaluated, fallback to a note
    if not bullets:
        for r in result.reasons:
            if r.code == "decision_summary":
                bullets.append(r.text)
        if not bullets:
            bullets.append(f"No specific checks evaluated (decision: {decision_val}).")

    return FeasibilityExplanation(
        headline=headline,
        bullets=bullets,
        decision=decision_val,
        blocks=blocks,
        warnings=warnings,
        passes=passes,
    )

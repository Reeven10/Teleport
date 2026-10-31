"""CLI harness for testing feasibility checks on device and workload profiles (P3).

Usage:
    python -m dev.feasibility.cli --manifest m.json --source s.json --target t.json --link l.json
    python -m dev.feasibility.cli --manifest m.json --source s.json --target t.json --link l.json --stats stats.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from agent.teleport.feasibility.checks import run_all_checks
from contract.contract import (
    Decision,
    DeviceInfo,
    LinkQuality,
    Reason,
    Stats,
    WorkloadManifest,
)

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "tests" / "feasibility" / "fixtures"


def resolve_file_path(path_str: str) -> Path:
    """Resolve a file path, checking current directory, absolute path, and fixtures directory."""
    p = Path(path_str)
    if p.exists():
        return p
    # Try relative to fixtures directory
    fixture_candidate = FIXTURES_DIR / path_str
    if fixture_candidate.exists():
        return fixture_candidate
    fixture_candidate_json = FIXTURES_DIR / f"{path_str}.json"
    if fixture_candidate_json.exists():
        return fixture_candidate_json
    # Return as-is for standard error reporting
    return p


def load_json_file(path_str: str) -> dict[str, Any]:
    """Resolve and load a JSON file into a Python dictionary."""
    path = resolve_file_path(path_str)
    if not path.exists():
        raise FileNotFoundError(f"File not found: '{path_str}' (checked {path})")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


CHECK_NAMES = [
    "Architecture",
    "Operating System",
    "Runtime",
    "Libraries",
    "RAM (Free)",
    "CPU Cores",
    "Disk Space",
    "GPU Acceleration",
    "Target Battery",
    "Target Online",
    "Link Quality",
]


def determine_verdict(
    manifest: WorkloadManifest, reasons: list[Reason], link: LinkQuality | None
) -> tuple[Decision, str]:
    """Determine the final feasibility verdict and explanation based on precedence rules."""
    has_block = any(r.severity == "block" for r in reasons)
    warnings = [r for r in reasons if r.severity == "warn"]

    if not has_block:
        if warnings:
            return (
                "MIGRATE",
                f"Workload can be migrated with {len(warnings)} warning(s).",
            )
        return "MIGRATE", "All compatibility and resource checks passed successfully."

    # Blocks exist: can we fall back to REMOTE_ACCESS?
    remote_capable = getattr(manifest, "remoteCapable", False)
    link_viable = (
        link is not None
        and getattr(link, "lossPct", 100.0) <= 5.0
        and getattr(link, "mbps", 0.0) >= 2.0
        and getattr(link, "rttMs", 999.0) <= 300.0
    )

    if remote_capable and link_viable:
        return (
            "REMOTE_ACCESS",
            "Direct migration blocked; remote access fallback is viable (workload is remoteCapable and link supports streaming).",
        )
    if not remote_capable:
        return (
            "STAY",
            "Migration blocked and workload is not remoteCapable; workload must STAY on source.",
        )
    return (
        "STAY",
        "Migration blocked and network link cannot support remote streaming; workload must STAY on source.",
    )


def format_table(
    manifest: WorkloadManifest,
    target: DeviceInfo,
    reasons: list[Reason],
    verdict: Decision,
    verdict_explanation: str,
) -> str:
    """Build a formatted ASCII report table."""
    col_check_w = 18
    col_sev_w = 9
    col_code_w = 18
    col_reason_w = 70

    sep_line = (
        "+"
        + "-" * (col_check_w + 2)
        + "+"
        + "-" * (col_sev_w + 2)
        + "+"
        + "-" * (col_code_w + 2)
        + "+"
        + "-" * (col_reason_w + 2)
        + "+"
    )
    header = (
        f"| {'Check':<{col_check_w}} "
        f"| {'Severity':<{col_sev_w}} "
        f"| {'Code':<{col_code_w}} "
        f"| {'Reason':<{col_reason_w}} |"
    )

    lines: list[str] = [
        "",
        "=" * len(sep_line),
        f" TELEPORT FEASIBILITY EVALUATION: {manifest.name} -> {target.name}",
        "=" * len(sep_line),
        sep_line,
        header,
        sep_line,
    ]

    for name, reason in zip(CHECK_NAMES, reasons):
        sev_str = reason.severity.upper()
        # Truncate or wrap reason text cleanly if overly long
        r_text = reason.text
        if len(r_text) > col_reason_w:
            r_display = r_text[: col_reason_w - 3] + "..."
        else:
            r_display = r_text

        line = (
            f"| {name:<{col_check_w}} "
            f"| {sev_str:<{col_sev_w}} "
            f"| {reason.code:<{col_code_w}} "
            f"| {r_display:<{col_reason_w}} |"
        )
        lines.append(line)

    lines.append(sep_line)

    # Summary counts
    pass_cnt = sum(1 for r in reasons if r.severity == "pass")
    warn_cnt = sum(1 for r in reasons if r.severity == "warn")
    block_cnt = sum(1 for r in reasons if r.severity == "block")

    lines.extend(
        [
            "",
            f"  Summary:  PASS = {pass_cnt}   |   WARN = {warn_cnt}   |   BLOCK = {block_cnt}",
            f"  Verdict:  [{verdict}] - {verdict_explanation}",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Teleport Feasibility Engine CLI - Evaluates migration capability between devices."
    )
    parser.add_argument(
        "--manifest",
        "-m",
        required=True,
        help="Path or name of workload manifest JSON file.",
    )
    parser.add_argument(
        "--source",
        "-s",
        required=True,
        help="Path or name of source DeviceInfo JSON file.",
    )
    parser.add_argument(
        "--target",
        "-t",
        required=True,
        help="Path or name of target DeviceInfo JSON file.",
    )
    parser.add_argument(
        "--link",
        "-l",
        required=True,
        help="Path or name of LinkQuality JSON file (or 'none' for disconnected).",
    )
    parser.add_argument(
        "--stats",
        help="Optional path to target device Stats JSON file.",
    )
    parser.add_argument(
        "--target-stats",
        help="Alias for --stats.",
    )
    parser.add_argument(
        "--snapshot-size-mb",
        type=float,
        default=0.0,
        help="Estimated snapshot size in MB (default: 0.0).",
    )

    args = parser.parse_args(argv)

    try:
        manifest_raw = load_json_file(args.manifest)
        manifest = WorkloadManifest.model_validate(manifest_raw)

        # Source is required by CLI interface
        load_json_file(args.source)

        target_raw = load_json_file(args.target)
        target = DeviceInfo.model_validate(target_raw)

        link: LinkQuality | None = None
        if args.link.lower() != "none":
            link_raw = load_json_file(args.link)
            link = LinkQuality.model_validate(link_raw)

        # Look for stats: explicit argument, or try adjacent stats file
        stats_path_arg = args.target_stats or args.stats
        stats: Stats | None = None
        if stats_path_arg:
            stats_raw = load_json_file(stats_path_arg)
            stats = Stats.model_validate(stats_raw)
        else:
            # Auto-detect matching stats fixture if target file name matches device_*
            target_path = resolve_file_path(args.target)
            target_stem = target_path.stem
            if target_stem.startswith("device_"):
                candidate_stats_name = target_stem.replace("device_", "stats_") + ".json"
                candidate_stats_path = target_path.parent / candidate_stats_name
                if candidate_stats_path.exists():
                    with candidate_stats_path.open("r", encoding="utf-8") as f:
                        stats = Stats.model_validate(json.load(f))

        reasons = run_all_checks(
            manifest=manifest,
            target=target,
            stats=stats,
            link=link,
            snapshot_size_mb=args.snapshot_size_mb,
        )

        verdict, explanation = determine_verdict(manifest, reasons, link)
        table_output = format_table(manifest, target, reasons, verdict, explanation)
        print(table_output)
        return 0

    except Exception as exc:
        print(f"Error during feasibility evaluation: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())


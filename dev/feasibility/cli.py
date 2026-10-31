"""CLI harness for testing feasibility checks on device and workload profiles (P3).

Usage:
    python -m dev.feasibility.cli --manifest m.json --source s.json --target t.json --link l.json
    python -m dev.feasibility.cli --manifest m.json --source s.json --target t.json \
        --link l.json --stats stats.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, cast

from contract.contract import (
    DeviceInfo,
    FeasibilityResult,
    LinkQuality,
    Stats,
    WorkloadManifest,
)
from teleport.feasibility.engine import evaluate_feasibility

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
    return p


def load_json_file(path_str: str) -> dict[str, Any]:
    """Resolve and load a JSON file into a Python dictionary."""
    path = resolve_file_path(path_str)
    if not path.exists():
        raise FileNotFoundError(f"File not found: '{path_str}' (checked {path})")
    with path.open("r", encoding="utf-8") as f:
        return cast(dict[str, Any], json.load(f))


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


def format_table(
    manifest: WorkloadManifest,
    target: DeviceInfo,
    result: FeasibilityResult,
) -> str:
    """Build a formatted ASCII report table."""
    col_check_w = 18
    col_sev_w = 9
    col_code_w = 26
    col_reason_w = 66

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

    # Index 0 is the summary reason
    summary_reason = result.reasons[0] if result.reasons else None
    check_reasons = result.reasons[1:] if len(result.reasons) > 1 else result.reasons

    # Print summary row at top
    if summary_reason:
        s_display = (
            summary_reason.text[: col_reason_w - 3] + "..."
            if len(summary_reason.text) > col_reason_w
            else summary_reason.text
        )
        lines.append(
            f"| {'[SUMMARY]':<{col_check_w}} "
            f"| {summary_reason.severity.upper():<{col_sev_w}} "
            f"| {summary_reason.code:<{col_code_w}} "
            f"| {s_display:<{col_reason_w}} |"
        )
        lines.append(sep_line)

    for idx, reason in enumerate(check_reasons):
        name = CHECK_NAMES[idx] if idx < len(CHECK_NAMES) else reason.code.split(".")[0].title()
        sev_str = reason.severity.upper()
        r_text = reason.text
        r_display = r_text[: col_reason_w - 3] + "..." if len(r_text) > col_reason_w else r_text

        line = (
            f"| {name:<{col_check_w}} "
            f"| {sev_str:<{col_sev_w}} "
            f"| {reason.code:<{col_code_w}} "
            f"| {r_display:<{col_reason_w}} |"
        )
        lines.append(line)

    lines.append(sep_line)

    # Summary counts (excluding summary reason at index 0)
    pass_cnt = sum(1 for r in check_reasons if r.severity == "pass")
    warn_cnt = sum(1 for r in check_reasons if r.severity == "warn")
    block_cnt = sum(1 for r in check_reasons if r.severity == "block")

    estimates_line = (
        f"  Estimates: estTransferSec = {result.estTransferSec:.2f}s  |  "
        f"estInterruptionMs = {result.estInterruptionMs:.1f}ms"
    )

    lines.extend(
        [
            "",
            f"  Summary:   PASS = {pass_cnt}   |   WARN = {warn_cnt}   |   BLOCK = {block_cnt}",
            estimates_line,
            f"  Verdict:   [{result.decision}] - {summary_reason.text if summary_reason else ''}",
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
        "--source-stats",
        help="Optional path to source device Stats JSON file.",
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

        source_raw = load_json_file(args.source)
        source = DeviceInfo.model_validate(source_raw)

        target_raw = load_json_file(args.target)
        target = DeviceInfo.model_validate(target_raw)

        link: LinkQuality | None = None
        if args.link.lower() != "none":
            link_raw = load_json_file(args.link)
            link = LinkQuality.model_validate(link_raw)

        # Target stats auto-detection
        stats_path_arg = args.target_stats or args.stats
        target_stats: Stats | None = None
        if stats_path_arg:
            stats_raw = load_json_file(stats_path_arg)
            target_stats = Stats.model_validate(stats_raw)
        else:
            target_path = resolve_file_path(args.target)
            target_stem = target_path.stem
            if target_stem.startswith("device_"):
                candidate_stats_name = target_stem.replace("device_", "stats_") + ".json"
                candidate_stats_path = target_path.parent / candidate_stats_name
                if candidate_stats_path.exists():
                    with candidate_stats_path.open("r", encoding="utf-8") as f:
                        target_stats = Stats.model_validate(json.load(f))

        # Source stats
        source_stats: Stats | None = None
        if args.source_stats:
            source_stats_raw = load_json_file(args.source_stats)
            source_stats = Stats.model_validate(source_stats_raw)

        result = evaluate_feasibility(
            manifest=manifest,
            source=source,
            target=target,
            link=link,
            target_stats=target_stats,
            source_stats=source_stats,
            snapshot_size_mb=args.snapshot_size_mb,
        )

        table_output = format_table(manifest, target, result)
        print(table_output)
        return 0

    except Exception as exc:
        print(f"Error during feasibility evaluation: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

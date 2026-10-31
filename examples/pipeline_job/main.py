#!/usr/bin/env python3
"""Pipeline Job Demo Workload for Teleport.

A realistic batch data processing pipeline that runs in 6 distinct stages,
periodically emitting user-defined checkpoints via the Teleport SDK.
"""

from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path
from typing import Any

import teleport_sdk as teleport

TOTAL_RECORDS = 200 if os.environ.get("QUICK_TEST") == "1" else 2000
BATCH_SIZE = 100
SLEEP_INTERVAL = 0.01 if os.environ.get("QUICK_TEST") == "1" else 0.4


def save_file(filename: str, data: Any) -> None:
    Path(filename).write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_file(filename: str, default: Any = None) -> Any:
    p = Path(filename)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return default
    return default


def main() -> None:
    print("[Pipeline] Starting Pipeline Batch Processor...", flush=True)

    # 1. Initialize Teleport SDK if available
    sdk_active = False
    try:
        teleport.init()
        sdk_active = True
        print("[Pipeline] Teleport SDK connected to agent daemon.", flush=True)
    except Exception as e:
        print(f"[Pipeline] Running in standalone local mode ({e}).", flush=True)

    # 2. Checkpoint 1: Config
    restored_config = teleport.restore("config") if sdk_active else None
    config: dict[str, Any]
    if isinstance(restored_config, dict):
        config = restored_config
    else:
        loaded = load_file("config.json")
        if isinstance(loaded, dict):
            config = loaded
        else:
            config = {
                "job_id": "pipeline-batch-2026",
                "total_records": TOTAL_RECORDS,
                "batch_size": BATCH_SIZE,
                "version": "1.0.0",
            }
    save_file("config.json", config)
    if sdk_active:
        teleport.checkpoint("config", config)

    # 3. Checkpoint 2: Input Data
    restored_input = teleport.restore("input_data") if sdk_active else None
    input_data: list[dict[str, Any]]
    if isinstance(restored_input, dict) and isinstance(restored_input.get("items"), list):
        input_data = restored_input["items"]
    elif isinstance(restored_input, list):
        input_data = restored_input
    else:
        loaded_input = load_file("input_data.json")
        if isinstance(loaded_input, list):
            input_data = loaded_input
        else:
            print(f"[Pipeline] Generating initial dataset of {TOTAL_RECORDS} records...", flush=True)
            input_data = [
                {"id": i, "raw_metric": math.sin(i * 0.1) * 100.0, "category": f"cat_{i % 8}"}
                for i in range(TOTAL_RECORDS)
            ]
    save_file("input_data.json", input_data)
    if sdk_active:
        teleport.checkpoint("input_data", {"items": input_data})

    # 4. Checkpoint 3 & 4: Stage 1 & Stage 2 outputs
    restored_stage1 = teleport.restore("stage1_output") if sdk_active else None
    restored_stage2 = teleport.restore("stage2_output") if sdk_active else None

    stage1: list[dict[str, Any]]
    if isinstance(restored_stage1, dict) and isinstance(restored_stage1.get("items"), list):
        stage1 = restored_stage1["items"]
    elif isinstance(restored_stage1, list):
        stage1 = restored_stage1
    else:
        stage1 = load_file("stage1.json", []) or []

    stage2: dict[str, float] = (
        restored_stage2
        if isinstance(restored_stage2, dict)
        else (load_file("stage2.json", {}) or {})
    )
    save_file("stage1.json", stage1)
    save_file("stage2.json", stage2)

    # 5. Checkpoint 5: Model Index
    restored_model = teleport.restore("model_index") if sdk_active else None
    model_index: dict[str, Any]
    if isinstance(restored_model, dict):
        model_index = restored_model
    else:
        loaded_model = load_file("model_index.json")
        if isinstance(loaded_model, dict):
            model_index = loaded_model
        else:
            model_index = {
                "feature_weights": [0.25, 0.45, 0.15, 0.15],
                "index_version": 4,
                "trained_at": time.time(),
            }
    save_file("model_index.json", model_index)
    if sdk_active:
        teleport.checkpoint("model_index", model_index)

    # 6. Checkpoint 6: Progress Cursor
    restored_progress = teleport.restore("progress") if sdk_active else None
    progress: dict[str, Any]
    if isinstance(restored_progress, dict):
        progress = restored_progress
    else:
        loaded_prog = load_file("progress.json")
        if isinstance(loaded_prog, dict):
            progress = loaded_prog
        else:
            progress = {"cursor": 0, "completed": False, "epoch": 1}

    cursor = int(progress.get("cursor", 0))
    if cursor > 0:
        print(
            f"[Pipeline] >>> RESUMING WORKLOAD STATE: continuing from record {cursor} / {TOTAL_RECORDS} <<<",
            flush=True,
        )
    else:
        print(f"[Pipeline] Starting batch run from beginning (0 / {TOTAL_RECORDS})", flush=True)

    # Register fence callback to flush all state to disk and agent before cutover
    def handle_fence() -> None:
        print(
            "[Pipeline] !!! FENCE SIGNAL RECEIVED: Synchronizing all 6 checkpoints to agent !!!",
            flush=True,
        )
        cur_progress = {"cursor": cursor, "completed": cursor >= TOTAL_RECORDS, "fenced_at": time.time()}
        save_file("progress.json", cur_progress)
        save_file("stage1.json", stage1)
        save_file("stage2.json", stage2)
        if sdk_active:
            teleport.checkpoint("progress", cur_progress)
            teleport.checkpoint("stage1_output", {"items": stage1})
            teleport.checkpoint("stage2_output", stage2)

    if sdk_active:
        teleport.on_fence(handle_fence)

    # Main processing loop
    while cursor < TOTAL_RECORDS:
        if sdk_active and teleport.should_stop():
            print("[Pipeline] Workload stopped by Teleport agent controller.", flush=True)
            break

        end = min(cursor + BATCH_SIZE, TOTAL_RECORDS)
        # Process batch
        for idx in range(cursor, end):
            item = input_data[idx]
            norm_val = round(float(item["raw_metric"]) / 100.0, 4)
            cat = str(item["category"])
            stage1.append({"id": idx, "normalized": norm_val, "category": cat})
            stage2[cat] = stage2.get(cat, 0.0) + norm_val

        cursor = end
        pct = (cursor / TOTAL_RECORDS) * 100.0
        print(
            f"[Pipeline] Processing records: {cursor:4d} / {TOTAL_RECORDS} ({pct:5.1f}%) | "
            f"Stage 1 count: {len(stage1)} | Categories: {len(stage2)}",
            flush=True,
        )

        # Update progress and save checkpoints
        progress = {"cursor": cursor, "completed": cursor >= TOTAL_RECORDS, "updated_at": time.time()}
        save_file("progress.json", progress)
        save_file("stage1.json", stage1)
        save_file("stage2.json", stage2)

        if sdk_active:
            teleport.checkpoint("progress", progress)
            teleport.checkpoint("stage1_output", {"items": stage1})
            teleport.checkpoint("stage2_output", stage2)

        # Sleep briefly to demonstrate live progress in dashboards
        time.sleep(SLEEP_INTERVAL)

    print("[Pipeline] Batch processing completed successfully! All records verified.", flush=True)


if __name__ == "__main__":
    main()

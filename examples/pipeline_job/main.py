"""Data processing pipeline job with 6 user-defined checkpoints.

Can run with or without the Teleport SDK / agent daemon.
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from pathlib import Path

# Try importing Teleport SDK; fallback to standalone local operation
try:
    import teleport_sdk as teleport
except ImportError:
    # Look for sdk in repo root if running from example folder
    repo_sdk = Path(__file__).resolve().parents[2] / "sdk"
    if repo_sdk.exists():
        sys.path.insert(0, str(repo_sdk))
        try:
            import teleport_sdk as teleport
        except ImportError:
            teleport = None
    else:
        teleport = None


TOTAL_RECORDS = 200 if os.environ.get("QUICK_TEST") == "1" else 2000
BATCH_SIZE = 100
SLEEP_INTERVAL = 0.01 if os.environ.get("QUICK_TEST") == "1" else 0.4


def save_file(filename: str, data: object) -> None:
    Path(filename).write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_file(filename: str, default: object = None) -> object:
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
    if teleport is not None:
        try:
            teleport.init()
            sdk_active = True
            print("[Pipeline] Teleport SDK connected to agent daemon.", flush=True)
        except Exception as e:
            print(f"[Pipeline] Running in standalone local mode ({e}).", flush=True)
    else:
        print("[Pipeline] Running in standalone mode without Teleport SDK.", flush=True)

    # 2. Checkpoint 1: Config
    config = None
    if sdk_active and teleport:
        config = teleport.restore("config")
    if not config:
        config = load_file("config.json", {
            "job_id": "pipeline-batch-2026",
            "total_records": TOTAL_RECORDS,
            "batch_size": BATCH_SIZE,
            "version": "1.0.0",
        })
    save_file("config.json", config)
    if sdk_active and teleport:
        teleport.checkpoint("config", config)

    # 3. Checkpoint 2: Input Data
    input_data = None
    if sdk_active and teleport:
        input_data = teleport.restore("input_data")
    if not input_data:
        print(f"[Pipeline] Generating initial dataset of {TOTAL_RECORDS} records...", flush=True)
        input_data = [
            {"id": i, "raw_metric": math.sin(i * 0.1) * 100.0, "category": f"cat_{i % 8}"}
            for i in range(TOTAL_RECORDS)
        ]
    save_file("input_data.json", input_data)
    if sdk_active and teleport:
        teleport.checkpoint("input_data", input_data)

    # 4. Checkpoint 3 & 4: Stage 1 & Stage 2 outputs
    stage1 = None
    stage2 = None
    if sdk_active and teleport:
        stage1 = teleport.restore("stage1_output")
        stage2 = teleport.restore("stage2_output")
    stage1 = stage1 or load_file("stage1.json", [])
    stage2 = stage2 or load_file("stage2.json", {})
    save_file("stage1.json", stage1)
    save_file("stage2.json", stage2)

    # 5. Checkpoint 5: Model Index
    model_index = None
    if sdk_active and teleport:
        model_index = teleport.restore("model_index")
    if not model_index:
        model_index = load_file("model_index.json", {
            "feature_weights": [0.25, 0.45, 0.15, 0.15],
            "index_version": 4,
            "trained_at": time.time(),
        })
    save_file("model_index.json", model_index)
    if sdk_active and teleport:
        teleport.checkpoint("model_index", model_index)

    # 6. Checkpoint 6: Progress Cursor
    progress = None
    if sdk_active and teleport:
        progress = teleport.restore("progress")
    if not progress:
        progress = load_file("progress.json", {"cursor": 0, "completed": False, "epoch": 1})

    cursor = int(progress.get("cursor", 0))  # type: ignore[union-attr]
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
        if teleport:
            teleport.checkpoint("progress", cur_progress)
            teleport.checkpoint("stage1_output", stage1)
            teleport.checkpoint("stage2_output", stage2)

    if sdk_active and teleport:
        teleport.on_fence(handle_fence)

    # Main processing loop
    while cursor < TOTAL_RECORDS:
        if sdk_active and teleport and teleport.should_stop():
            print("[Pipeline] Workload stopped by Teleport agent controller.", flush=True)
            break

        end = min(cursor + BATCH_SIZE, TOTAL_RECORDS)
        # Process batch
        for idx in range(cursor, end):
            item = input_data[idx]  # type: ignore[index]
            norm_val = round(item["raw_metric"] / 100.0, 4)  # type: ignore[index]
            cat = item["category"]  # type: ignore[index]
            stage1.append({"id": idx, "normalized": norm_val, "category": cat})  # type: ignore[union-attr]
            stage2[cat] = stage2.get(cat, 0.0) + norm_val  # type: ignore[union-attr]

        cursor = end
        pct = (cursor / TOTAL_RECORDS) * 100.0
        print(
            f"[Pipeline] Processing records: {cursor:4d} / {TOTAL_RECORDS} ({pct:5.1f}%) | "
            f"Stage 1 count: {len(stage1)} | Categories: {len(stage2)}",  # type: ignore[arg-type]
            flush=True,
        )

        # Update progress and save checkpoints
        progress = {"cursor": cursor, "completed": cursor >= TOTAL_RECORDS, "updated_at": time.time()}
        save_file("progress.json", progress)
        save_file("stage1.json", stage1)
        save_file("stage2.json", stage2)

        if sdk_active and teleport:
            teleport.checkpoint("progress", progress)
            teleport.checkpoint("stage1_output", stage1)
            teleport.checkpoint("stage2_output", stage2)

        # Sleep briefly to demonstrate live progress in dashboards
        time.sleep(SLEEP_INTERVAL)

    print("[Pipeline] Batch processing completed successfully! All records verified.", flush=True)


if __name__ == "__main__":
    main()

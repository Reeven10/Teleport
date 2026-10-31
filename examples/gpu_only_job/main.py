#!/usr/bin/env python3
"""GPU-Only Workload Demo for Teleport.

Simulates a CUDA/GPU hardware accelerated machine learning / raytracing render task.
Requires NVIDIA GPU and x86_64 architecture. When evaluated against arm64-lowspec,
Teleport's Feasibility Engine automatically rejects migration and triggers REMOTE_ACCESS fallback.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import teleport_sdk as teleport


def save_state(frame: int, samples: int, vram_mb: int) -> None:
    data = {
        "frame": frame,
        "samples_per_pixel": samples,
        "vram_allocated_mb": vram_mb,
        "ts": time.time(),
    }
    Path("frame_state.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_state() -> dict[str, Any]:
    p = Path("frame_state.json")
    if p.exists():
        try:
            loaded = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                return loaded
        except Exception:
            return {}
    return {}


def main() -> None:
    print("[GPU-Compute] Initializing Neural Raytracing Engine...", flush=True)

    sdk_active = False
    try:
        teleport.init()
        sdk_active = True
        print("[GPU-Compute] Teleport SDK connected to agent.", flush=True)
    except Exception as e:
        print(f"[GPU-Compute] Standalone execution ({e}).", flush=True)

    restored = teleport.restore("frame_state") if sdk_active else None
    state: dict[str, Any]
    if isinstance(restored, dict):
        state = restored
    else:
        state = load_state()

    frame = int(state.get("frame", 0))
    print("[GPU-Compute] Device Context: NVIDIA CUDA Raytracing Architecture (x86_64 Host)", flush=True)
    if frame > 0:
        print(f"[GPU-Compute] Resuming render sequence from frame {frame}", flush=True)

    vram_mb = 1840

    while True:
        if sdk_active and teleport.should_stop():
            print("[GPU-Compute] Render process stopped by controller.", flush=True)
            break

        frame += 1
        samples = (frame * 16) % 1024 + 16

        save_state(frame, samples, vram_mb)
        if sdk_active:
            teleport.checkpoint("frame_state", {
                "frame": frame,
                "samples_per_pixel": samples,
                "vram_allocated_mb": vram_mb,
                "ts": time.time(),
            })

        print(
            f"[GPU-Compute] Frame: {frame:05d} rendered | Samples: {samples:4d}/px | "
            f"VRAM: {vram_mb} MB | Engine: OptiX 8.0",
            flush=True,
        )
        if os.environ.get("RUN_ONCE") == "1":
            break
        time.sleep(0.5)


if __name__ == "__main__":
    main()

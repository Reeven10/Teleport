"""GPU-Only High-Throughput Raytracer and Neural Inference Workload.

Declares needsGpu: true and arch: [x86_64].
Migrating to an arm64 low-spec device evaluates to REMOTE_ACCESS fallback.
Runs standalone without Teleport.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# Optional Teleport SDK import
try:
    import teleport_sdk as teleport
except ImportError:
    repo_sdk = Path(__file__).resolve().parents[2] / "sdk"
    if repo_sdk.exists():
        sys.path.insert(0, str(repo_sdk))
        try:
            import teleport_sdk as teleport
        except ImportError:
            teleport = None
    else:
        teleport = None


def save_state(frame: int, samples: int, vram_mb: int) -> None:
    data = {
        "frame": frame,
        "samples_per_pixel": samples,
        "vram_allocated_mb": vram_mb,
        "ts": time.time(),
    }
    Path("frame_state.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_state() -> dict[str, object]:
    p = Path("frame_state.json")
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
        except Exception:
            return {}
    return {}


def main() -> None:
    print("[GPU-Compute] Initializing Neural Raytracing Engine...", flush=True)

    sdk_active = False
    if teleport is not None:
        try:
            teleport.init()
            sdk_active = True
            print("[GPU-Compute] Teleport SDK connected to agent.", flush=True)
        except Exception as e:
            print(f"[GPU-Compute] Standalone execution ({e}).", flush=True)

    state = None
    if sdk_active and teleport:
        state = teleport.restore("frame_state")
    if not state:
        state = load_state()

    frame = int(state.get("frame", 0))  # type: ignore[union-attr]
    print("[GPU-Compute] Device Context: NVIDIA CUDA Raytracing Architecture (x86_64 Host)", flush=True)
    if frame > 0:
        print(f"[GPU-Compute] Resuming render sequence from frame {frame}", flush=True)

    vram_mb = 1840

    while True:
        if sdk_active and teleport and teleport.should_stop():
            print("[GPU-Compute] Render process stopped by controller.", flush=True)
            break

        frame += 1
        samples = (frame * 16) % 1024 + 16

        save_state(frame, samples, vram_mb)
        if sdk_active and teleport:
            teleport.checkpoint("frame_state", {
                "frame": frame,
                "samples_per_pixel": samples,
                "vram_allocated_mb": vram_mb,
                "ts": time.time(),
            })

        print(
            f"[GPU-Compute] Render Pass #{frame:05d} | Samples: {samples:4d} spp | "
            f"VRAM: {vram_mb} MB | Metal/ARM: Incompatible | 60.2 FPS",
            flush=True,
        )

        if os.environ.get("RUN_ONCE") == "1":
            break

        time.sleep(0.5)


if __name__ == "__main__":
    main()

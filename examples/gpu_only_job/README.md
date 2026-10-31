# GPU-Only Neural Raytracer Workload

A hardware-pinned compute workload designed to trigger Teleport's zero-install **Remote Access fallback**.

## Feasibility Policy

In `teleport.yaml`:
- `needsGpu: true`: Requires dedicated GPU compute acceleration.
- `arch: [x86_64]`: Pinned to x86_64 hardware.
- `remoteCapable: true`: Explicitly permits low-latency interactive streaming when native migration is infeasible.

When the Teleport Feasibility Engine evaluates migrating this workload to an `arm64` peer without a dedicated CUDA GPU (such as a simulated ARM64 low-spec device), native state transfer is blocked. Because `remoteCapable` is true, Teleport returns decision `REMOTE_ACCESS`, launching low-latency screen and input streaming rather than failing.

## Running Standalone

```bash
cd examples/gpu_only_job
python main.py
```


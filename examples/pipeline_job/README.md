# Pipeline Batch Processor Demo Workload

A stateful multi-stage Python data processing job demonstrating Teleport's checkpoint synchronization and zero double-spend authority migration.

## Checkpoint Architecture

The workload partitions state into 6 user-defined checkpoints defined in `teleport.yaml`:
1. `config` (`config.json`): Static job parameters, batch sizes, and dataset configuration.
2. `input_data` (`input_data.json`): Raw dataset generated at startup.
3. `stage1_output` (`stage1.json`): Normalized record transformations.
4. `stage2_output` (`stage2.json`): Metric category aggregations.
5. `model_index` (`model_index.json`): Reference feature indices and weights.
6. `progress` (`progress.json`): Execution cursor, completion status, and fencing timestamps.

## Running Standalone (Without Teleport)

The workload runs seamlessly without an agent daemon or SDK installation:

```bash
cd examples/pipeline_job
python main.py
```

If stopped with Ctrl+C and rerun, it reads `progress.json` and continues directly from the last recorded checkpoint.

## Running With Teleport

Launch the workload under the Teleport runner:

```bash
# Via REST API
curl -X POST http://127.0.0.1:8765/api/workloads/start \
  -H "Content-Type: application/json" \
  -d '{"manifestPath": "examples/pipeline_job"}'
```

When a migration is triggered to a peer node, all 6 checkpoints are packaged into tarballs, SHA-256 validated chunk-by-chunk on the target node, and authority cleanly transitions with millisecond interruption time.


"""Test that all demo workloads in examples/ parse cleanly and can start."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from teleport.core.manifest import load_manifest

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_pipeline_job_manifest() -> None:
    manifest, folder = load_manifest(REPO_ROOT / "examples" / "pipeline_job")
    assert manifest.id == "pipeline-job"
    assert manifest.runtime.name == "python"
    assert len(manifest.checkpoints) == 6
    checkpoint_ids = [c.id for c in manifest.checkpoints]
    assert checkpoint_ids == [
        "config",
        "input_data",
        "stage1_output",
        "stage2_output",
        "model_index",
        "progress",
    ]


def test_gpu_only_job_manifest() -> None:
    manifest, folder = load_manifest(REPO_ROOT / "examples" / "gpu_only_job")
    assert manifest.id == "gpu-only-job"
    assert manifest.needsGpu is True
    assert manifest.arch == ["x86_64"]
    assert manifest.remoteCapable is True
    assert len(manifest.checkpoints) == 1


def test_notepad_app_manifest() -> None:
    manifest, folder = load_manifest(REPO_ROOT / "examples" / "notepad_app")
    assert manifest.id == "notepad-app"
    assert manifest.remoteCapable is True
    assert len(manifest.checkpoints) == 1
    assert manifest.checkpoints[0].id == "document_state"


def test_examples_run_standalone(tmp_path: Path) -> None:
    """Verify that workloads can run standalone without Teleport."""
    import os

    # 1. Pipeline Job
    script_path = REPO_ROOT / "examples" / "pipeline_job" / "main.py"
    env = dict(os.environ, QUICK_TEST="1")
    proc = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0
    assert "Pipeline Batch Processor" in proc.stdout
    assert (tmp_path / "progress.json").exists()

    # 2. GPU Only Job
    gpu_script = REPO_ROOT / "examples" / "gpu_only_job" / "main.py"
    proc_gpu = subprocess.run(
        [sys.executable, str(gpu_script)],
        cwd=tmp_path,
        env=dict(os.environ, RUN_ONCE="1"),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc_gpu.returncode == 0
    assert "Neural Raytracing Engine" in proc_gpu.stdout
    assert (tmp_path / "frame_state.json").exists()

    # 3. Notepad App Headless
    notepad_script = REPO_ROOT / "examples" / "notepad_app" / "main.py"
    proc_notepad = subprocess.run(
        [sys.executable, str(notepad_script), "--headless"],
        cwd=tmp_path,
        env=dict(os.environ, RUN_ONCE="1"),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc_notepad.returncode == 0
    assert "Collaborative Scratchpad" in proc_notepad.stdout
    assert (tmp_path / "document.txt").exists()

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from teleport.core.manifest import ManifestError, load_manifest, parse_manifest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def sample() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load((FIXTURES / "teleport.yaml").read_text())
    return data


def problems(data: Any) -> list[str]:
    with pytest.raises(ManifestError) as e:
        parse_manifest(data)
    return e.value.problems


def test_sample_manifest_loads() -> None:
    manifest, folder = load_manifest(FIXTURES / "teleport.yaml")
    assert manifest.id == "photo-tagger"
    assert [c.id for c in manifest.checkpoints] == ["config", "db", "model", "progress"]
    assert manifest.runtime.minVersion == "3.11" and manifest.remoteCapable
    assert folder == FIXTURES


def test_folder_path_finds_teleport_yaml() -> None:
    manifest, _ = load_manifest(FIXTURES / "counter_job")
    assert manifest.id == "counter-job" and len(manifest.checkpoints) == 6


def test_id_defaults_to_slug_of_name() -> None:
    data = sample()
    del data["id"]
    assert parse_manifest(data).id == "photo-tagger"


def test_missing_and_wrong_types_are_reported_with_paths() -> None:
    data = sample()
    del data["command"]
    data["minRamMb"] = "lots"
    data["checkpoints"][1] = {"name": "no id"}
    found = problems(data)
    assert "command: Field required" in found
    assert any(p.startswith("minRamMb:") for p in found)
    assert "checkpoints[1].id: Field required" in found


def test_semantic_rules() -> None:
    data = sample()
    data["checkpoints"].append({"id": "config", "name": "dup", "paths": ["../secret"]})
    data["arch"] = []
    data["typo"] = 1
    data["runtime"]["minVersion"] = "latest"
    found = problems(data)
    assert "checkpoints[4].id: duplicate id 'config'" in found
    assert any("must be relative" in p for p in found)
    assert "arch: list at least one architecture" in found
    assert "unknown field 'typo'" in found
    assert any(p.startswith("runtime.minVersion") for p in found)


def test_invalid_yaml(tmp_path: Path) -> None:
    (tmp_path / "teleport.yaml").write_text("id: [unclosed")
    with pytest.raises(ManifestError, match="invalid YAML"):
        load_manifest(tmp_path)


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_manifest(tmp_path / "nope")

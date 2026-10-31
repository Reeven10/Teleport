"""teleport.yaml loader: parses a workload manifest into WorkloadManifest with readable errors."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Any

import yaml
from pydantic import ValidationError

from contract.contract import WorkloadManifest

from .settings import REPO_ROOT

MANIFEST_NAME = "teleport.yaml"
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
RESERVED_PREFIX = "teleport."  # system units, e.g. teleport.code
VERSION_RE = re.compile(r"^\d+(\.\d+)*$")


class ManifestError(ValueError):
    def __init__(self, source: str, problems: list[str]) -> None:
        self.source = source
        self.problems = problems
        super().__init__(f"{source}: " + "; ".join(problems))


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", name.strip()).strip("-.").lower()[:64]


def parse_manifest(data: Any, source: str = MANIFEST_NAME) -> WorkloadManifest:
    if not isinstance(data, dict):
        raise ManifestError(source, ["top level must be a mapping"])
    data = dict(data)
    if "id" not in data and isinstance(data.get("name"), str):
        data["id"] = _slug(data["name"])

    problems = [f"unknown field '{k}'" for k in data if k not in WorkloadManifest.model_fields]
    try:
        manifest = WorkloadManifest.model_validate(data)
    except ValidationError as e:
        for err in e.errors():
            loc = ".".join(str(p) if isinstance(p, str) else f"[{p}]" for p in err["loc"])
            problems.append(f"{loc.replace('.[', '[')}: {err['msg']}")
        raise ManifestError(source, problems) from None

    if not ID_RE.match(manifest.id):
        problems.append(f"id: {manifest.id!r} must match {ID_RE.pattern}")
    if not manifest.command.strip():
        problems.append("command: must not be empty")
    if not VERSION_RE.match(manifest.runtime.minVersion):
        problems.append(f"runtime.minVersion: {manifest.runtime.minVersion!r} is not like 3.11")
    if not manifest.arch:
        problems.append("arch: list at least one architecture")
    if not manifest.os:
        problems.append("os: list at least one OS")
    for field in ("minRamMb", "minCpuCores", "minDiskMb"):
        if getattr(manifest, field) < 0:
            problems.append(f"{field}: must be >= 0")
    if not manifest.checkpoints:
        problems.append("checkpoints: define at least one checkpoint")
    seen: set[str] = set()
    for i, ck in enumerate(manifest.checkpoints):
        if not ID_RE.match(ck.id):
            problems.append(f"checkpoints[{i}].id: {ck.id!r} must match {ID_RE.pattern}")
        if ck.id.startswith(RESERVED_PREFIX):
            problems.append(f"checkpoints[{i}].id: ids starting with {RESERVED_PREFIX!r} are reserved")
        if ck.id in seen:
            problems.append(f"checkpoints[{i}].id: duplicate id {ck.id!r}")
        seen.add(ck.id)
        for p in ck.paths:
            pp = PurePosixPath(p.replace("\\", "/"))
            if pp.is_absolute() or ".." in pp.parts or re.match(r"^[A-Za-z]:", p):
                problems.append(f"checkpoints[{i}].paths: {p!r} must be relative to the workload folder")
    if problems:
        raise ManifestError(source, problems)
    return manifest


def resolve_manifest_path(manifest_path: str | Path) -> Path:
    """A teleport.yaml file, or a folder holding one; relative paths try cwd, then the repo root."""
    path = Path(manifest_path)
    if not path.is_absolute() and not path.exists():
        path = REPO_ROOT / path
    if path.is_dir():
        path = path / MANIFEST_NAME
    if not path.is_file():
        raise FileNotFoundError(f"manifest not found: {manifest_path}")
    return path.resolve()


def load_manifest(manifest_path: str | Path) -> tuple[WorkloadManifest, Path]:
    """(manifest, its folder). The folder holds the workload code and is the source of its workdir."""
    path = resolve_manifest_path(manifest_path)
    try:
        data = yaml.safe_load(path.read_text("utf-8"))
    except yaml.YAMLError as e:
        raise ManifestError(str(path), [f"invalid YAML: {e}"]) from None
    return parse_manifest(data, str(path)), path.parent

"""Snapshot and chunk hash validation helpers."""

from __future__ import annotations

import hashlib
import hmac
from pathlib import Path


def sha256_bytes(data: bytes) -> str:
    """Compute hex SHA-256 digest of in-memory bytes."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, chunk_size: int = 65536) -> str:
    """Compute hex SHA-256 digest of a file on disk in chunks."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def constant_time_compare(val1: str, val2: str) -> bool:
    """Constant-time comparison to guard against timing attacks."""
    return hmac.compare_digest(val1.lower().strip(), val2.lower().strip())


def verify_checkpoint(path: Path, expected_sha256: str) -> bool:
    """Validate that checkpoint file matches expected SHA-256 digest."""
    if not path.is_file():
        return False
    actual = sha256_file(path)
    return constant_time_compare(actual, expected_sha256)

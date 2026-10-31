"""Tests for snapshot and checkpoint integrity helpers."""

from __future__ import annotations

from pathlib import Path

from teleport.security.snapshots import (
    constant_time_compare,
    sha256_bytes,
    sha256_file,
    verify_checkpoint,
)


def test_sha256_helpers_and_verify_checkpoint(tmp_path: Path) -> None:
    data = b"State snapshot data chunk 12345"
    expected_hex = sha256_bytes(data)

    test_file = tmp_path / "checkpoint.bin"
    test_file.write_bytes(data)

    # sha256_file matches sha256_bytes
    assert sha256_file(test_file) == expected_hex

    # verify_checkpoint succeeds
    assert verify_checkpoint(test_file, expected_hex)
    assert verify_checkpoint(test_file, expected_hex.upper())

    # Tampered file fails verification
    test_file.write_bytes(b"corrupted state")
    assert not verify_checkpoint(test_file, expected_hex)

    # Missing file returns False
    assert not verify_checkpoint(tmp_path / "nonexistent.bin", expected_hex)


def test_constant_time_compare() -> None:
    assert constant_time_compare("abc123DEF", "abc123def")
    assert not constant_time_compare("abc123", "xyz987")

"""Tests for short-lived remote access viewer tokens."""

from __future__ import annotations

import time
from pathlib import Path

from teleport.security.tokens import RemoteTokenManager


def test_token_issue_and_verify_single_use(tmp_path: Path) -> None:
    mgr = RemoteTokenManager(tmp_path)
    viewer = "viewer-device-99"

    token = mgr.issue_token(viewer_id=viewer, ttl_seconds=60.0)
    assert isinstance(token, str)
    assert "." in token

    # First consumption succeeds
    assert mgr.verify_and_consume_token(token, viewer_id=viewer)

    # Replay / reuse refused
    assert not mgr.verify_and_consume_token(token, viewer_id=viewer)


def test_token_expiry_refused(tmp_path: Path) -> None:
    mgr = RemoteTokenManager(tmp_path)
    viewer = "viewer-device-99"

    # Token with 0.1s TTL
    token = mgr.issue_token(viewer_id=viewer, ttl_seconds=0.05)
    time.sleep(0.1)

    assert not mgr.verify_and_consume_token(token, viewer_id=viewer)


def test_token_viewer_mismatch_refused(tmp_path: Path) -> None:
    mgr = RemoteTokenManager(tmp_path)
    token = mgr.issue_token(viewer_id="legitimate-viewer", ttl_seconds=60.0)

    # Different viewer is refused
    assert not mgr.verify_and_consume_token(token, viewer_id="impostor-viewer")


def test_token_tamper_refused(tmp_path: Path) -> None:
    mgr = RemoteTokenManager(tmp_path)
    token = mgr.issue_token(viewer_id="viewer-1", ttl_seconds=60.0)

    parts = token.split(".")
    tampered_sig = parts[1][:-2] + ("AA" if parts[1][-2:] != "AA" else "BB")
    tampered_token = f"{parts[0]}.{tampered_sig}"

    assert not mgr.verify_and_consume_token(tampered_token, viewer_id="viewer-1")

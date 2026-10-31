"""Tests for RealSecureSession: X25519 DH, HKDF, AES-256-GCM, counter nonces, replay protection."""

from __future__ import annotations

from pathlib import Path

import pytest

from teleport.security.identity import SecurityError
from teleport.security.session import RealSecureSession


def test_session_handshake_and_bidirectional_traffic(tmp_path: Path) -> None:
    session_a = RealSecureSession(tmp_path / "a")
    session_b = RealSecureSession(tmp_path / "b")

    # Unestablished sessions cannot encrypt or decrypt
    with pytest.raises(SecurityError, match="Cannot encrypt"):
        session_a.encrypt(b"premature")
    with pytest.raises(SecurityError, match="Cannot decrypt"):
        session_b.decrypt(b"premature")

    # Exchange public keys
    eph_a = session_a.ephemeral_public_key()
    id_a = session_a.identity_public_key()

    eph_b = session_b.ephemeral_public_key()
    id_b = session_b.identity_public_key()

    # Session A is initiator, Session B is responder
    session_a.establish(eph_b, id_b, is_initiator=True)
    session_b.establish(eph_a, id_a, is_initiator=False)

    # A -> B message
    msg_a = b'{"t": "mig.prepare", "workloadId": "job-123"}'
    ciphertext_a = session_a.encrypt(msg_a)
    decrypted_b = session_b.decrypt(ciphertext_a)
    assert decrypted_b == msg_a

    # B -> A message
    msg_b = b'{"t": "mig.ready", "workloadId": "job-123"}'
    ciphertext_b = session_b.encrypt(msg_b)
    decrypted_a = session_a.decrypt(ciphertext_b)
    assert decrypted_a == msg_b


def test_session_tampered_ciphertext_rejected(tmp_path: Path) -> None:
    session_a = RealSecureSession(tmp_path / "a")
    session_b = RealSecureSession(tmp_path / "b")

    session_a.establish(session_b.ephemeral_public_key(), session_b.identity_public_key(), is_initiator=True)
    session_b.establish(session_a.ephemeral_public_key(), session_a.identity_public_key(), is_initiator=False)

    valid_ciphertext = session_a.encrypt(b"sensitive state data")

    # Tamper with the ciphertext body
    tampered_bytes = bytearray(valid_ciphertext)
    tampered_bytes[-1] ^= 0x01
    tampered_ciphertext = bytes(tampered_bytes)

    with pytest.raises(SecurityError, match="Tampered ciphertext rejected"):
        session_b.decrypt(tampered_ciphertext)


def test_session_replayed_frame_rejected(tmp_path: Path) -> None:
    session_a = RealSecureSession(tmp_path / "a")
    session_b = RealSecureSession(tmp_path / "b")

    session_a.establish(session_b.ephemeral_public_key(), session_b.identity_public_key(), is_initiator=True)
    session_b.establish(session_a.ephemeral_public_key(), session_a.identity_public_key(), is_initiator=False)

    frame = session_a.encrypt(b"critical state update")

    # First receive succeeds
    assert session_b.decrypt(frame) == b"critical state update"

    # Replay of the exact same frame is refused
    with pytest.raises(SecurityError, match="Replay detected"):
        session_b.decrypt(frame)


def test_session_directional_role_mismatch_rejected(tmp_path: Path) -> None:
    session_a = RealSecureSession(tmp_path / "a")
    session_b = RealSecureSession(tmp_path / "b")

    session_a.establish(session_b.ephemeral_public_key(), session_b.identity_public_key(), is_initiator=True)
    session_b.establish(session_a.ephemeral_public_key(), session_a.identity_public_key(), is_initiator=False)

    # Frame encrypted by A with INIT role cannot be reflected back to A as incoming
    frame_from_a = session_a.encrypt(b"reflected")
    with pytest.raises(SecurityError, match="Directional role mismatch"):
        session_a.decrypt(frame_from_a)

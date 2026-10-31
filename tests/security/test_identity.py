"""Tests for Ed25519 device identity and peer public key store (TOFU)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from teleport.security.identity import DeviceIdentity, PeerKeyStore, SecurityError


def test_device_identity_keypair_generation_and_persistence(tmp_path: Path) -> None:
    home = tmp_path / "teleport"
    ident1 = DeviceIdentity(home)

    key_file = home / "identity.pem"
    assert key_file.is_file()
    if os.name != "nt":
        assert (key_file.stat().st_mode & 0o777) == 0o600

    pub1 = ident1.public_key_bytes()
    assert len(pub1) == 32
    pub1_b64 = ident1.public_key_b64()
    assert len(pub1_b64) > 0

    # Reload from same home -> preserves identity
    ident2 = DeviceIdentity(home)
    assert ident2.public_key_bytes() == pub1
    assert ident2.public_key_b64() == pub1_b64


def test_device_identity_signature_roundtrip_and_tamper(tmp_path: Path) -> None:
    ident = DeviceIdentity(tmp_path)
    data = b"Hello Teleport Migration Manifest"

    sig = ident.sign(data)
    assert isinstance(sig, str)

    # Valid verification
    assert DeviceIdentity.verify(data, sig, ident.public_key_bytes())

    # Tampered data rejected
    assert not DeviceIdentity.verify(b"Tampered Manifest", sig, ident.public_key_bytes())

    # Wrong key rejected
    other_ident = DeviceIdentity(tmp_path / "other")
    assert not DeviceIdentity.verify(data, sig, other_ident.public_key_bytes())

    # Corrupted signature rejected
    bad_sig = "A" * len(sig)
    assert not DeviceIdentity.verify(data, bad_sig, ident.public_key_bytes())


def test_peer_key_store_tofu_and_key_change_detected(tmp_path: Path) -> None:
    home = tmp_path / "teleport"
    store = PeerKeyStore(home)

    peer_id = "dev-target-1"
    ident_a = DeviceIdentity(tmp_path / "dev_a")
    key_a = ident_a.public_key_bytes()

    # Record on first use
    store.record_peer_key(peer_id, key_a)
    assert store.has_peer_key(peer_id)
    assert store.get_peer_key(peer_id) == key_a

    # Reload store from disk
    store_reloaded = PeerKeyStore(home)
    assert store_reloaded.get_peer_key(peer_id) == key_a

    # Recording same key again is idempotent
    store.record_peer_key(peer_id, key_a)

    # Key change detected: unknown or changed key raises SecurityError
    ident_impostor = DeviceIdentity(tmp_path / "impostor")
    key_impostor = ident_impostor.public_key_bytes()

    with pytest.raises(SecurityError, match="Peer key change detected"):
        store.record_peer_key(peer_id, key_impostor)

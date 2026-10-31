"""Tests for manifest signing and verification helpers."""

from __future__ import annotations

from pathlib import Path

from teleport.security.identity import DeviceIdentity, PeerKeyStore
from teleport.security.manifest import sign_manifest, verify_manifest


def test_manifest_signing_and_verification_roundtrip(tmp_path: Path) -> None:
    sender_home = tmp_path / "sender"
    receiver_home = tmp_path / "receiver"

    sender_ident = DeviceIdentity(sender_home)
    receiver_peer_keys = PeerKeyStore(receiver_home)

    sender_id = "dev-sender"
    receiver_peer_keys.record_peer_key(sender_id, sender_ident.public_key_bytes())

    manifest_bytes = b'{"workloadId": "job-abc", "entrypoint": "main.py", "files": ["checkpoint.bin"]}'

    signature = sign_manifest(manifest_bytes, sender_ident)
    assert len(signature) > 0

    # Verification passes
    assert verify_manifest(manifest_bytes, signature, sender_id, receiver_peer_keys)

    # Tampered manifest rejected
    tampered_bytes = b'{"workloadId": "job-abc", "entrypoint": "malicious.py"}'
    assert not verify_manifest(tampered_bytes, signature, sender_id, receiver_peer_keys)

    # Unknown sender device rejected
    assert not verify_manifest(manifest_bytes, signature, "dev-unknown", receiver_peer_keys)

"""Manifest signing and verification helpers for migration preparation."""

from __future__ import annotations

import logging

from .identity import DeviceIdentity, PeerKeyStore

log = logging.getLogger("teleport.security.manifest")


def sign_manifest(manifest_bytes: bytes, identity: DeviceIdentity) -> str:
    """Sign workload manifest bytes using source device's Ed25519 identity key."""
    return identity.sign(manifest_bytes)


def verify_manifest(
    manifest_bytes: bytes,
    signature_b64: str,
    device_id: str,
    peer_keys: PeerKeyStore,
) -> bool:
    """Verify workload manifest signature against trusted public key of source device_id."""
    pub_key = peer_keys.get_peer_key(device_id)
    if not pub_key:
        log.warning("Cannot verify manifest: device %s has no recorded trusted key", device_id)
        return False

    return DeviceIdentity.verify(manifest_bytes, signature_b64, pub_key)

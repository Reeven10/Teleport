"""Insecure plaintext session for development and testing.

Logs a loud warning on use. To be replaced with real Ed25519/X25519/AES-256-GCM session.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from pathlib import Path

from .interface import SecureSession

log = logging.getLogger("teleport.security")


class PlaintextDevSession(SecureSession):
    """Insecure development session performing plaintext passthrough."""

    _warned = False

    def __init__(self, key_seed: str | Path = "teleport-dev") -> None:
        self.key_seed = str(key_seed)
        self.peer_ephemeral: bytes | None = None
        self.peer_identity: bytes | None = None

        if not PlaintextDevSession._warned:
            PlaintextDevSession._warned = True
            log.warning("*******************************************************************")
            log.warning(" [INSECURE] PlaintextDevSession ACTIVE! Traffic is NOT encrypted!  ")
            log.warning(" Real Ed25519/X25519/AES-GCM session will replace this in Prompt 4. ")
            log.warning("*******************************************************************")

    def identity_public_key(self) -> bytes:
        return hashlib.sha256(f"identity:{self.key_seed}".encode()).digest()

    def ephemeral_public_key(self) -> bytes:
        return hashlib.sha256(f"ephemeral:{self.key_seed}".encode()).digest()

    def establish(
        self,
        peer_ephemeral_public_key: bytes,
        peer_identity_public_key: bytes,
        is_initiator: bool = True,
    ) -> None:
        self.peer_ephemeral = peer_ephemeral_public_key
        self.peer_identity = peer_identity_public_key

    def encrypt(self, plaintext: bytes) -> bytes:
        return plaintext

    def decrypt(self, ciphertext: bytes) -> bytes:
        return ciphertext

    def sign(self, data: bytes) -> str:
        digest = hashlib.sha256(data).digest()
        return base64.b64encode(digest).decode("utf-8")

    def verify(self, data: bytes, signature: str, identity_public_key: bytes) -> bool:
        expected = self.sign(data)
        return signature == expected

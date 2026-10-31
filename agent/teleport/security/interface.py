"""Security interfaces and protocol definitions for Teleport."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class SecureSession(Protocol):
    """P2. Ed25519 identity, X25519 + HKDF session key, AES-256-GCM, manifest signatures."""

    def identity_public_key(self) -> bytes: ...
    def ephemeral_public_key(self) -> bytes: ...
    def establish(self, peer_ephemeral_public_key: bytes, peer_identity_public_key: bytes) -> None: ...
    def encrypt(self, plaintext: bytes) -> bytes: ...
    def decrypt(self, ciphertext: bytes) -> bytes: ...
    def sign(self, data: bytes) -> str:
        """Base64 Ed25519 signature with this device's identity key."""
        ...

    def verify(self, data: bytes, signature: str, identity_public_key: bytes) -> bool: ...


ISecureSession = SecureSession

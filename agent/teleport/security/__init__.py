"""Security (P2). INSECURE STUB from P1: plaintext passthrough. Replace with the real SecureSession
(Ed25519 identity, X25519 + HKDF, AES-256-GCM) keeping the SecureSession Protocol."""

from __future__ import annotations


class SecureSession:
    def identity_public_key(self) -> bytes:
        return b""

    def ephemeral_public_key(self) -> bytes:
        return b""

    def establish(self, peer_ephemeral_public_key: bytes, peer_identity_public_key: bytes) -> None:
        pass

    def encrypt(self, plaintext: bytes) -> bytes:
        return plaintext

    def decrypt(self, ciphertext: bytes) -> bytes:
        return ciphertext

    def sign(self, data: bytes) -> str:
        return ""

    def verify(self, data: bytes, signature: str, identity_public_key: bytes) -> bool:
        return False


__all__ = ["SecureSession"]

"""Authenticated, encrypted session implementing X25519 + HKDF + AES-256-GCM."""

from __future__ import annotations

import logging
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from .identity import DeviceIdentity, SecurityError
from .interface import SecureSession

log = logging.getLogger("teleport.security.session")


class RealSecureSession(SecureSession):
    """Production SecureSession: X25519, HKDF, AES-256-GCM, counter nonce, and replay defense."""

    def __init__(self, home: Path | None = None) -> None:
        key_home = home or (Path.home() / ".teleport")
        self.identity = DeviceIdentity(key_home)
        self._ephemeral_private = x25519.X25519PrivateKey.generate()
        self._peer_ephemeral_bytes: bytes | None = None
        self._peer_identity_bytes: bytes | None = None

        self._tx_aesgcm: AESGCM | None = None
        self._rx_aesgcm: AESGCM | None = None
        self._role_prefix: bytes = b"INIT"
        self._peer_role_prefix: bytes = b"RESP"

        self._tx_seq: int = 0
        self._rx_highest_seq: int = -1
        self._rx_seen_seqs: set[int] = set()
        self._established: bool = False

    def identity_public_key(self) -> bytes:
        """32-byte Ed25519 identity public key."""
        return self.identity.public_key_bytes()

    def ephemeral_public_key(self) -> bytes:
        """32-byte X25519 ephemeral public key."""
        return self._ephemeral_private.public_key().public_bytes(
            encoding=Encoding.Raw,
            format=PublicFormat.Raw,
        )

    def establish(
        self,
        peer_ephemeral_public_key: bytes,
        peer_identity_public_key: bytes,
        is_initiator: bool = True,
    ) -> None:
        """Perform X25519 DH exchange and HKDF directional key expansion."""
        self._peer_ephemeral_bytes = peer_ephemeral_public_key
        self._peer_identity_bytes = peer_identity_public_key

        peer_x25519 = x25519.X25519PublicKey.from_public_bytes(peer_ephemeral_public_key)
        shared_secret = self._ephemeral_private.exchange(peer_x25519)

        # HKDF expansion: 64 bytes total -> two 32-byte keys for AES-256
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=64,
            salt=None,
            info=b"teleport-v1-session",
        )
        derived = hkdf.derive(shared_secret)

        if is_initiator:
            self._role_prefix = b"INIT"
            self._peer_role_prefix = b"RESP"
            tx_key = derived[:32]
            rx_key = derived[32:]
        else:
            self._role_prefix = b"RESP"
            self._peer_role_prefix = b"INIT"
            tx_key = derived[32:]
            rx_key = derived[:32]

        self._tx_aesgcm = AESGCM(tx_key)
        self._rx_aesgcm = AESGCM(rx_key)
        self._tx_seq = 0
        self._rx_highest_seq = -1
        self._rx_seen_seqs.clear()
        self._established = True
        log.debug("Established RealSecureSession (role=%s)", self._role_prefix.decode("ascii"))

    def encrypt(self, plaintext: bytes) -> bytes:
        """Encrypt message with directional AES-256-GCM and increment monotonic sequence counter."""
        if not self._established or self._tx_aesgcm is None:
            # Before handshake completes, traffic passes authenticated or throws
            raise SecurityError("Cannot encrypt before secure session is established")

        seq = self._tx_seq
        self._tx_seq += 1

        # 12-byte Nonce: 4-byte role prefix + 8-byte big-endian counter
        nonce = self._role_prefix + seq.to_bytes(8, "big")
        ciphertext = self._tx_aesgcm.encrypt(nonce, plaintext, associated_data=nonce)

        # Wire packet: 12-byte nonce header + ciphertext (including 16-byte GCM tag)
        return nonce + ciphertext

    def decrypt(self, ciphertext: bytes) -> bytes:
        """Decrypt AES-256-GCM frame, enforcing replay and reorder protection."""
        if not self._established or self._rx_aesgcm is None:
            raise SecurityError("Cannot decrypt before secure session is established")

        if len(ciphertext) < 28:  # 12-byte nonce + at least 16-byte auth tag
            raise SecurityError("Malformed packet: insufficient bytes for nonce and auth tag")

        nonce = ciphertext[:12]
        role = nonce[:4]
        seq = int.from_bytes(nonce[4:12], "big")

        if role != self._peer_role_prefix:
            raise SecurityError(
                f"Directional role mismatch: expected {self._peer_role_prefix!r}, got {role!r}"
            )

        # Replay protection check
        if seq <= self._rx_highest_seq and seq in self._rx_seen_seqs:
            raise SecurityError(f"Replay detected: frame sequence {seq} was already received")
        if self._rx_highest_seq >= 128 and seq < (self._rx_highest_seq - 128):
            raise SecurityError(f"Replayed frame rejected: sequence {seq} falls outside sliding window")

        # Decrypt & verify tag
        try:
            payload = ciphertext[12:]
            plaintext = self._rx_aesgcm.decrypt(nonce, payload, associated_data=nonce)
        except InvalidTag as e:
            raise SecurityError("Tampered ciphertext rejected: authentication tag mismatch") from e

        # Mark sequence received in sliding window
        self._rx_seen_seqs.add(seq)
        if seq > self._rx_highest_seq:
            self._rx_highest_seq = seq
            cutoff = self._rx_highest_seq - 128
            self._rx_seen_seqs = {s for s in self._rx_seen_seqs if s >= cutoff}

        return plaintext

    def sign(self, data: bytes) -> str:
        """Sign data with Ed25519 identity key, returning base64 signature."""
        return self.identity.sign(data)

    def verify(self, data: bytes, signature: str, identity_public_key: bytes) -> bool:
        """Verify Ed25519 signature."""
        return DeviceIdentity.verify(data, signature, identity_public_key)

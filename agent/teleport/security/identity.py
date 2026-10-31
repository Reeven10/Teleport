"""Ed25519 device identity keypair management and peer public key store."""

from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

log = logging.getLogger("teleport.security.identity")


class SecurityError(Exception):
    """Raised for cryptographic integrity, replay, or authentication failures."""


class DeviceIdentity:
    """Manages the host's long-term Ed25519 identity keypair stored in TELEPORT_HOME."""

    def __init__(self, home: Path) -> None:
        self.home = home
        self.key_path = home / "identity.pem"
        self._private_key: ed25519.Ed25519PrivateKey = self._load_or_generate()

    def _load_or_generate(self) -> ed25519.Ed25519PrivateKey:
        self.home.mkdir(parents=True, exist_ok=True)
        if self.key_path.exists():
            try:
                pem_data = self.key_path.read_bytes()
                priv_key = serialization.load_pem_private_key(pem_data, password=None)
                if isinstance(priv_key, ed25519.Ed25519PrivateKey):
                    return priv_key
            except Exception as e:
                log.warning(
                    "Failed to load existing identity key at %s: %s. Generating new one.",
                    self.key_path,
                    e,
                )

        # Generate new Ed25519 key
        priv_key = ed25519.Ed25519PrivateKey.generate()
        pem_data = priv_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        self.key_path.write_bytes(pem_data)
        try:
            # Restrict file permissions on POSIX
            os.chmod(self.key_path, 0o600)
        except Exception:
            pass

        log.info("Generated new Ed25519 device identity key at %s", self.key_path)
        return priv_key

    def public_key_bytes(self) -> bytes:
        """Raw 32-byte Ed25519 public key."""
        return self._private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

    def public_key_b64(self) -> str:
        """Base64 representation of 32-byte Ed25519 public key."""
        return base64.b64encode(self.public_key_bytes()).decode("ascii")

    def sign(self, data: bytes) -> str:
        """Sign data with Ed25519 private key, returning base64 signature."""
        sig = self._private_key.sign(data)
        return base64.b64encode(sig).decode("ascii")

    @staticmethod
    def verify(data: bytes, signature_b64: str, public_key_bytes: bytes) -> bool:
        """Verify base64 signature against raw Ed25519 public key bytes."""
        try:
            pub = ed25519.Ed25519PublicKey.from_public_bytes(public_key_bytes)
            sig_bytes = base64.b64decode(signature_b64)
            pub.verify(sig_bytes, data)
            return True
        except (InvalidSignature, ValueError, Exception):
            return False


class PeerKeyStore:
    """Persistent storage for trusted peer Ed25519 public keys (Trust On First Use)."""

    def __init__(self, home: Path) -> None:
        self.home = home
        self.file_path = home / "peer_keys.json"
        self._keys: dict[str, str] = {}  # device_id -> base64 public key
        self.load()

    def load(self) -> None:
        if not self.file_path.exists():
            return
        try:
            raw = json.loads(self.file_path.read_text("utf-8"))
            if isinstance(raw, dict):
                self._keys = {k: str(v) for k, v in raw.items()}
        except Exception as e:
            log.warning("Failed to load peer keys from %s: %s", self.file_path, e)

    def save(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        temp_path = self.home / f"peer_keys.json.tmp.{os.getpid()}"
        try:
            temp_path.write_text(json.dumps(self._keys, indent=2), "utf-8")
            temp_path.replace(self.file_path)
        except Exception:
            self.file_path.write_text(json.dumps(self._keys, indent=2), "utf-8")
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    def record_peer_key(self, peer_id: str, public_key_bytes: bytes) -> None:
        """Record trusted public key. Rejects key changes (TOFU violation / MITM)."""
        key_b64 = base64.b64encode(public_key_bytes).decode("ascii")
        if peer_id in self._keys:
            if self._keys[peer_id] != key_b64:
                raise SecurityError(
                    f"Peer key change detected for device {peer_id}! "
                    f"Possible man-in-the-middle attack or device re-created."
                )
            return

        self._keys[peer_id] = key_b64
        self.save()
        log.info("Recorded trusted Ed25519 key for peer %s", peer_id)

    def get_peer_key(self, peer_id: str) -> bytes | None:
        if key_b64 := self._keys.get(peer_id):
            return base64.b64decode(key_b64)
        return None

    def has_peer_key(self, peer_id: str) -> bool:
        return peer_id in self._keys

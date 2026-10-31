"""Security module (P2).

Provides Ed25519 identity, X25519 session exchange, AES-256-GCM authenticated encryption,
manifest signing/verification, snapshot integrity helpers, and remote access tokens.
"""

from __future__ import annotations

import os

from .dev_session import PlaintextDevSession
from .identity import DeviceIdentity, PeerKeyStore, SecurityError
from .interface import ISecureSession
from .manifest import sign_manifest, verify_manifest
from .session import RealSecureSession
from .snapshots import constant_time_compare, sha256_bytes, sha256_file, verify_checkpoint
from .tokens import RemoteTokenManager

# Default to RealSecureSession; allow PlaintextDevSession only behind explicit dev flag
SecureSession: type[RealSecureSession] = RealSecureSession
if os.environ.get("TELEPORT_INSECURE_DEV_SESSION") == "1":
    SecureSession = PlaintextDevSession  # type: ignore[assignment]

__all__ = [
    "DeviceIdentity",
    "ISecureSession",
    "PeerKeyStore",
    "PlaintextDevSession",
    "RealSecureSession",
    "RemoteTokenManager",
    "SecureSession",
    "SecurityError",
    "constant_time_compare",
    "sha256_bytes",
    "sha256_file",
    "sign_manifest",
    "verify_checkpoint",
    "verify_manifest",
]

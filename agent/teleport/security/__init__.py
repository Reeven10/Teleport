"""Security module (P2).

Provides the SecureSession interface and PlaintextDevSession.
"""

from __future__ import annotations

from .dev_session import PlaintextDevSession
from .interface import ISecureSession

# Concrete implementation satisfying the SecureSession Protocol
SecureSession = PlaintextDevSession

__all__ = ["ISecureSession", "PlaintextDevSession", "SecureSession"]

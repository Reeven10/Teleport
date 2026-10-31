"""One-time session token management for remote access.

Generates and validates single-use cryptographically secure session tokens.
Can be replaced with P2's token helper once on main.
"""

from __future__ import annotations

import secrets
import time
from typing import Protocol


class TokenManager(Protocol):
    def generate_token(self, session_id: str, ttl_sec: float = 120.0) -> str: ...
    def validate_and_consume(self, session_id: str, token: str) -> bool: ...


class LocalSessionTokenManager:
    """In-memory one-time session token store with expiration."""

    def __init__(self) -> None:
        # token -> (session_id, expires_at)
        self._tokens: dict[str, tuple[str, float]] = {}

    def generate_token(self, session_id: str, ttl_sec: float = 120.0) -> str:
        self._cleanup_expired()
        token = secrets.token_urlsafe(32)
        expires_at = time.time() + ttl_sec
        self._tokens[token] = (session_id, expires_at)
        return token

    def validate_and_consume(self, session_id: str, token: str) -> bool:
        self._cleanup_expired()
        if not token:
            return False

        record = self._tokens.get(token)
        if record is None:
            return False

        expected_session_id, expires_at = record
        if time.time() > expires_at:
            self._tokens.pop(token, None)
            return False

        if expected_session_id != session_id:
            return False

        # One-time use: consume immediately
        del self._tokens[token]
        return True

    def _cleanup_expired(self) -> None:
        now = time.time()
        expired = [t for t, (_, exp) in self._tokens.items() if now > exp]
        for t in expired:
            self._tokens.pop(t, None)


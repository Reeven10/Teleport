"""Short-lived, one-time remote access session tokens bound to paired viewers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from pathlib import Path

log = logging.getLogger("teleport.security.tokens")


class RemoteTokenManager:
    """Manages creation, verification, single-use enforcement, and expiration of remote viewer tokens."""

    def __init__(self, home: Path | None = None) -> None:
        token_home = home or (Path.home() / ".teleport")
        token_home.mkdir(parents=True, exist_ok=True)
        self.secret_path = token_home / "token_secret.bin"
        self._secret = self._load_or_create_secret()
        self._consumed_nonces: set[str] = set()

    def _load_or_create_secret(self) -> bytes:
        if self.secret_path.exists():
            try:
                sec = self.secret_path.read_bytes()
                if len(sec) >= 32:
                    return sec
            except Exception:
                pass

        sec = secrets.token_bytes(32)
        try:
            self.secret_path.write_bytes(sec)
        except Exception:
            pass
        return sec

    def issue_token(self, viewer_id: str, ttl_seconds: float = 60.0) -> str:
        """Issue signed, timestamped token bound to viewer_id."""
        nonce = secrets.token_hex(16)
        exp = time.time() + ttl_seconds
        payload = {
            "viewer_id": viewer_id,
            "nonce": nonce,
            "exp": exp,
        }
        payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        sig = hmac.new(self._secret, payload_bytes, hashlib.sha256).digest()
        p_b64 = base64.urlsafe_b64encode(payload_bytes).decode("ascii")
        sig_b64 = base64.urlsafe_b64encode(sig).decode("ascii")
        return f"{p_b64}.{sig_b64}"

    def verify_and_consume_token(self, token: str, viewer_id: str) -> bool:
        """Verify token authenticity, expiration, viewer binding, and enforce single-use consumption."""
        parts = token.split(".")
        if len(parts) != 2:
            log.warning("Rejected remote token: invalid structure")
            return False

        try:
            payload_bytes = base64.urlsafe_b64decode(parts[0].encode("ascii"))
            sig_bytes = base64.urlsafe_b64decode(parts[1].encode("ascii"))
        except Exception:
            return False

        # Verify HMAC signature
        expected_sig = hmac.new(self._secret, payload_bytes, hashlib.sha256).digest()
        if not hmac.compare_digest(sig_bytes, expected_sig):
            log.warning("Rejected remote token: HMAC signature mismatch")
            return False

        try:
            payload = json.loads(payload_bytes.decode("utf-8"))
            token_viewer = str(payload.get("viewer_id", ""))
            nonce = str(payload.get("nonce", ""))
            exp = float(payload.get("exp", 0.0))
        except Exception:
            return False

        # 1. Verify viewer binding
        if token_viewer != viewer_id:
            log.warning(
                "Rejected remote token: viewer mismatch (expected %s, got %s)",
                viewer_id,
                token_viewer,
            )
            return False

        # 2. Check expiration
        now = time.time()
        if now > exp:
            log.warning("Rejected remote token: expired (%ds past expiration)", int(now - exp))
            return False

        # 3. Enforce single-use consumption (prevent reuse)
        if nonce in self._consumed_nonces:
            log.warning("Rejected remote token: already consumed / replayed")
            return False

        self._consumed_nonces.add(nonce)
        return True

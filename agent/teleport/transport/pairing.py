"""Pairing manager for Teleport peer links.

Handles 6-digit PIN generation, display, rate limiting, and verification.
"""

from __future__ import annotations

import contextlib
import logging
import os
import secrets
import time
from typing import TYPE_CHECKING, Any

import httpx
from fastapi import HTTPException

from contract.contract import DeviceInfo
from teleport.security.identity import DeviceIdentity, PeerKeyStore

if TYPE_CHECKING:
    from ..core.context import Context

log = logging.getLogger("teleport.transport.pairing")


class PairingManager:
    """Manages PIN creation, rate-limited verification, and remote pairing requests."""

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self.identity = DeviceIdentity(ctx.settings.home)
        self.peer_keys = PeerKeyStore(ctx.settings.home)
        self._pin: str = self._initial_pin()
        self._failed_attempts: int = 0
        self._lockout_until: float = 0.0
        self._max_attempts = 3
        self._lockout_seconds = 15.0

    def _initial_pin(self) -> str:
        dev_pin = os.environ.get("TELEPORT_DEV_PIN")
        if dev_pin and len(dev_pin) == 6 and dev_pin.isdigit():
            return dev_pin
        return f"{secrets.randbelow(1_000_000):06d}"

    @property
    def pin(self) -> str:
        return self._pin

    def generate_pin(self) -> str:
        """Rotate and return a new 6-digit PIN."""
        self._pin = f"{secrets.randbelow(1_000_000):06d}"
        self._failed_attempts = 0
        self._lockout_until = 0.0
        log.info("Generated new Teleport pairing PIN: %s", self._pin)
        return self._pin

    def verify_pin(self, candidate_pin: str) -> tuple[bool, str | None]:
        """Verify candidate PIN against active PIN with rate limiting.

        Returns (is_valid, error_message).
        """
        now = time.time()
        if now < self._lockout_until:
            remaining = int(self._lockout_until - now) + 1
            log.warning("Pairing attempt blocked due to rate limit (%ds remaining)", remaining)
            return False, f"Rate limited: too many failed attempts. Try again in {remaining}s."

        if candidate_pin.strip() != self._pin:
            self._failed_attempts += 1
            if self._failed_attempts >= self._max_attempts:
                self._lockout_until = now + self._lockout_seconds
                log.warning("Pairing rate limit triggered: locked out for %ds", self._lockout_seconds)
                err_msg = (
                    f"Rate limited: {self._max_attempts} failed attempts. "
                    f"Locked out for {int(self._lockout_seconds)}s."
                )
                return False, err_msg

            remaining_tries = self._max_attempts - self._failed_attempts
            return False, f"Invalid PIN ({remaining_tries} attempts remaining)."

        # Success: reset rate limiting counters
        self._failed_attempts = 0
        self._lockout_until = 0.0
        return True, None

    async def initiate_remote_pair(self, addr: str, pin: str, local_device: DeviceInfo) -> DeviceInfo:
        """Call remote peer's /api/pair/verify endpoint to authenticate and pair."""
        clean_addr = addr.strip()
        if clean_addr.startswith("http://") or clean_addr.startswith("https://"):
            base_url = clean_addr.rstrip("/")
        elif clean_addr.startswith("ws://"):
            base_url = "http://" + clean_addr[5:].rstrip("/")
        elif clean_addr.startswith("wss://"):
            base_url = "https://" + clean_addr[6:].rstrip("/")
        else:
            base_url = f"http://{clean_addr.rstrip('/')}"

        # If path ends with /peer, strip it
        if base_url.endswith("/peer"):
            base_url = base_url[:-5]

        verify_url = f"{base_url}/api/pair/verify"
        payload = {
            "pin": pin.strip(),
            "device": local_device.model_dump(),
            "identity_key": self.identity.public_key_b64(),
        }

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(verify_url, json=payload)
        except httpx.ConnectTimeout as e:
            raise HTTPException(
                status_code=504,
                detail=(
                    f"Connection to '{addr}' timed out. "
                    "Verify that the device is online and port is allowed through firewalls."
                ),
            ) from e
        except (httpx.ConnectError, ConnectionRefusedError) as e:
            raise HTTPException(
                status_code=502,
                detail=(
                    f"Cannot reach device at '{addr}' (connection refused). "
                    "Check that Teleport agent is running on the other device."
                ),
            ) from e
        except Exception as e:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to connect to device at '{addr}': {e}",
            ) from e

        if resp.status_code == 429:
            remote_err = (
                "Pairing rate limited: too many failed attempts. Generate a new PIN on the target device."
            )
            with contextlib.suppress(Exception):
                remote_err = resp.json().get("detail", remote_err)
            raise HTTPException(status_code=429, detail=remote_err)

        if resp.status_code in (401, 403):
            remote_err = (
                "Pairing rejected: invalid PIN. Check the 6-digit PIN displayed on the target device."
            )
            with contextlib.suppress(Exception):
                remote_err = resp.json().get("detail", remote_err)
            raise HTTPException(status_code=401, detail=remote_err)

        if resp.status_code != 200:
            raise HTTPException(
                status_code=resp.status_code,
                detail=f"Pairing request failed (HTTP {resp.status_code}): {resp.text}",
            )

        data: dict[str, Any] = resp.json()
        if not data.get("ok"):
            err = data.get("error", "Pairing rejected by peer")
            raise HTTPException(status_code=401, detail=err)

        peer_data = data.get("device")
        if not peer_data:
            raise HTTPException(status_code=502, detail="Peer returned success without DeviceInfo")

        # Record peer Ed25519 identity key
        if remote_key_b64 := data.get("identity_key"):
            import base64

            remote_key_bytes = base64.b64decode(remote_key_b64)
            self.peer_keys.record_peer_key(peer_data["id"], remote_key_bytes)

        return DeviceInfo.model_validate(peer_data)

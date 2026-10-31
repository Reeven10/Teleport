from __future__ import annotations

from pathlib import Path

import pytest

from contract.contract import RemoteSessionEvent
from teleport.core import Settings, build_context
from teleport.remote import RemoteServiceImpl
from teleport.remote.capture import FakeCaptureBackend
from teleport.remote.tokens import LocalSessionTokenManager


def test_one_time_token_lifecycle() -> None:
    tm = LocalSessionTokenManager()
    token = tm.generate_token(session_id="sess-100", ttl_sec=60.0)

    assert bool(token)

    # First validation succeeds and consumes the token
    assert tm.validate_and_consume("sess-100", token) is True

    # Second validation fails (single-use)
    assert tm.validate_and_consume("sess-100", token) is False


def test_one_time_token_wrong_session() -> None:
    tm = LocalSessionTokenManager()
    token = tm.generate_token(session_id="sess-alpha")

    # Attempt to consume with wrong session ID
    assert tm.validate_and_consume("sess-beta", token) is False

    # Still valid for correct session
    assert tm.validate_and_consume("sess-alpha", token) is True


def test_one_time_token_expired() -> None:
    tm = LocalSessionTokenManager()
    # Negative TTL to simulate instant expiration
    token = tm.generate_token(session_id="sess-exp", ttl_sec=-1.0)
    assert tm.validate_and_consume("sess-exp", token) is False


@pytest.mark.asyncio
async def test_session_lifecycle_and_consent(tmp_path: Path) -> None:
    ctx = build_context(Settings(home=tmp_path / "home"))
    service = RemoteServiceImpl(ctx, capture_backend=FakeCaptureBackend())

    received_events: list[RemoteSessionEvent] = []

    async def on_remote_session(event: RemoteSessionEvent) -> None:
        received_events.append(event)

    ctx.bus.subscribe(RemoteSessionEvent, on_remote_session)

    # 1. Start session -> pending consent
    session = await service.start_session(workload_id="w-ml", viewer_id="v-peer")
    assert session.workloadId == "w-ml"
    assert session.viewerId == "v-peer"
    assert session.consent is False

    # 2. Grant consent
    approved = await service.consent(session.id, allow=True)
    assert approved.id == session.id
    assert approved.consent is True

    # Verifies both events were published to event bus
    assert len(received_events) == 2
    assert received_events[0].session.consent is False
    assert received_events[1].session.consent is True

    # 3. Stop session
    assert await service.stop_session(session.id) is True
    assert len(service.sessions()) == 0


@pytest.mark.asyncio
async def test_remote_consent_policy_auto_allow(tmp_path: Path) -> None:
    ctx = build_context(Settings(home=tmp_path / "home"))
    object.__setattr__(ctx.prefs, "remoteConsent", "auto_allow")
    service = RemoteServiceImpl(ctx, capture_backend=FakeCaptureBackend())

    session = await service.start_session(workload_id="w-ml", viewer_id="v-peer")
    assert session.consent is True


@pytest.mark.asyncio
async def test_remote_consent_policy_deny_all(tmp_path: Path) -> None:
    ctx = build_context(Settings(home=tmp_path / "home"))
    object.__setattr__(ctx.prefs, "remoteConsent", "deny_all")
    service = RemoteServiceImpl(ctx, capture_backend=FakeCaptureBackend())

    session = await service.start_session(workload_id="w-ml", viewer_id="v-peer")
    assert session.consent is False


@pytest.mark.asyncio
async def test_remote_consent_policy_prefs_json(tmp_path: Path) -> None:
    import json
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    (home / "prefs.json").write_text(json.dumps({"remoteConsent": "auto_allow"}), encoding="utf-8")
    ctx = build_context(Settings(home=home))
    service = RemoteServiceImpl(ctx, capture_backend=FakeCaptureBackend())

    session = await service.start_session(workload_id="w-ml", viewer_id="v-peer")
    assert session.consent is True

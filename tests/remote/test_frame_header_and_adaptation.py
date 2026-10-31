from __future__ import annotations

import time

import pytest

from teleport.remote.capture import (
    FRAME_HEADER_SIZE,
    FakeCaptureBackend,
    FrameEncoder,
    FrameHeader,
    calculate_adaptive_profile,
)


def test_frame_header_pack_unpack() -> None:
    now = time.time()
    header = FrameHeader(width=1920, height=1080, sequence=42, timestamp=now)

    packed = header.pack()
    assert len(packed) == FRAME_HEADER_SIZE == 20

    unpacked = FrameHeader.unpack(packed)
    assert unpacked.width == 1920
    assert unpacked.height == 1080
    assert unpacked.sequence == 42
    assert abs(unpacked.timestamp - now) < 1e-6


def test_frame_header_invalid_length() -> None:
    with pytest.raises(ValueError, match="too short"):
        FrameHeader.unpack(b"too_short_bytes")


def test_adaptive_profile_high_speed() -> None:
    profile = calculate_adaptive_profile(
        backlog_count=0,
        rtt_ms=1.2,
        mbps=1000.0,
        loss_pct=0.0,
        target_height=720,
        original_height=1080,
    )
    assert profile.fps == 20.0
    assert profile.jpeg_quality == 75
    assert profile.scale == pytest.approx(0.67, abs=0.02)


def test_adaptive_profile_degraded_network() -> None:
    # High packet loss
    profile_loss = calculate_adaptive_profile(
        backlog_count=0,
        rtt_ms=25.0,
        mbps=50.0,
        loss_pct=3.5,
    )
    assert profile_loss.fps == 10.0
    assert profile_loss.jpeg_quality == 40

    # High send backlog
    profile_backlog = calculate_adaptive_profile(
        backlog_count=3,
        rtt_ms=5.0,
        mbps=200.0,
        loss_pct=0.0,
    )
    assert profile_backlog.fps == 10.0
    assert profile_backlog.jpeg_quality == 40


def test_frame_encoder_skips_unchanged() -> None:
    backend = FakeCaptureBackend(width=640, height=360)
    encoder = FrameEncoder()

    # Frame 1: initial image
    backend.set_color_seed(1)
    img1 = backend.grab_screen()
    payload1, header1 = encoder.encode(img1, quality=70, scale=1.0, skip_unchanged=True)

    assert payload1 is not None
    assert header1 is not None
    assert header1.sequence == 1
    assert len(payload1) > FRAME_HEADER_SIZE

    # Frame 2: identical image -> should be skipped!
    img2 = backend.grab_screen()
    payload2, header2 = encoder.encode(img2, quality=70, scale=1.0, skip_unchanged=True)

    assert payload2 is None
    assert header2 is None

    # Frame 3: modified color seed -> should encode with sequence 2
    backend.set_color_seed(2)
    img3 = backend.grab_screen()
    payload3, header3 = encoder.encode(img3, quality=70, scale=1.0, skip_unchanged=True)

    assert payload3 is not None
    assert header3 is not None
    assert header3.sequence == 2

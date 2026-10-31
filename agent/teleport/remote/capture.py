"""Screen capture with mss, PIL JPEG compression, and adaptive rate/quality."""

from __future__ import annotations

import hashlib
import io
import struct
import time
from dataclasses import dataclass
from typing import Protocol

from PIL import Image

# Binary Frame Header:
# 4 bytes uint32: width
# 4 bytes uint32: height
# 4 bytes uint32: sequence
# 8 bytes double: timestamp (seconds)
# Total = 20 bytes
FRAME_HEADER_FORMAT = ">IIId"
FRAME_HEADER_SIZE = struct.calcsize(FRAME_HEADER_FORMAT)


@dataclass(frozen=True)
class FrameHeader:
    width: int
    height: int
    sequence: int
    timestamp: float

    def pack(self) -> bytes:
        return struct.pack(FRAME_HEADER_FORMAT, self.width, self.height, self.sequence, self.timestamp)

    @classmethod
    def unpack(cls, data: bytes) -> FrameHeader:
        if len(data) < FRAME_HEADER_SIZE:
            raise ValueError(f"Data too short for FrameHeader: {len(data)} < {FRAME_HEADER_SIZE}")
        w, h, seq, ts = struct.unpack(FRAME_HEADER_FORMAT, data[:FRAME_HEADER_SIZE])
        return cls(width=w, height=h, sequence=seq, timestamp=ts)


class CaptureBackend(Protocol):
    def grab_screen(self) -> Image.Image: ...
    def get_screen_size(self) -> tuple[int, int]: ...


class MssCaptureBackend:
    """Production screen grabber using mss."""

    def __init__(self, monitor_index: int = 1) -> None:
        import mss

        self._sct = mss.mss()
        self._monitor_index = monitor_index

    def get_monitor_info(self) -> dict[str, int]:
        monitors = self._sct.monitors
        if self._monitor_index < len(monitors):
            return dict(monitors[self._monitor_index])
        return dict(monitors[0])

    def get_screen_size(self) -> tuple[int, int]:
        m = self.get_monitor_info()
        return m["width"], m["height"]

    def grab_screen(self) -> Image.Image:
        m = self.get_monitor_info()
        raw = self._sct.grab(m)
        # mss returns BGRA, convert to RGB
        return Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")


class FakeCaptureBackend:
    """Deterministic test capture backend producing colored test patterns."""

    def __init__(self, width: int = 1280, height: int = 720) -> None:
        self.width = width
        self.height = height
        self._color_seed = 0

    def get_screen_size(self) -> tuple[int, int]:
        return self.width, self.height

    def set_color_seed(self, seed: int) -> None:
        self._color_seed = seed

    def grab_screen(self) -> Image.Image:
        # Generate predictable test image
        r = (self._color_seed * 40) % 256
        g = (self._color_seed * 80) % 256
        b = (self._color_seed * 120) % 256
        return Image.new("RGB", (self.width, self.height), color=(r, g, b))


@dataclass
class QualityProfile:
    fps: float
    jpeg_quality: int
    scale: float


def calculate_adaptive_profile(
    backlog_count: int = 0,
    rtt_ms: float = 1.0,
    mbps: float = 1000.0,
    loss_pct: float = 0.0,
    target_height: int = 720,
    original_height: int = 1080,
) -> QualityProfile:
    """Calculate adaptive frame rate (10-20 FPS) and JPEG quality.

    Driven by send backlog, network RTT, throughput, and packet loss.
    """
    # 1. Base scale factor targeting ~720p or original scaled down
    if original_height > target_height:
        base_scale = round(target_height / original_height, 2)
    else:
        base_scale = 1.0

    # 2. Network quality tiering
    if loss_pct > 3.0 or rtt_ms > 100.0 or mbps < 15.0 or backlog_count > 2:
        # Heavily degraded
        fps = 10.0
        quality = 40
        scale = max(0.4, base_scale * 0.75)
    elif loss_pct > 1.0 or rtt_ms > 50.0 or mbps < 40.0 or backlog_count > 1:
        # Moderate / Wi-Fi typical
        fps = 12.0
        quality = 55
        scale = max(0.5, base_scale * 0.85)
    elif rtt_ms < 20.0 and mbps >= 100.0 and backlog_count == 0:
        # High speed / Cable
        fps = 20.0
        quality = 75
        scale = base_scale
    else:
        # Default baseline
        fps = 15.0
        quality = 65
        scale = base_scale

    return QualityProfile(fps=fps, jpeg_quality=quality, scale=scale)


class FrameEncoder:
    """Encodes PIL Images to binary JPEG frames with header, skipping unchanged frames."""

    def __init__(self) -> None:
        self._sequence = 0
        self._last_hash: str | None = None

    def encode(
        self,
        img: Image.Image,
        quality: int = 65,
        scale: float = 1.0,
        skip_unchanged: bool = True,
        timestamp: float | None = None,
    ) -> tuple[bytes | None, FrameHeader | None]:
        """Returns (binary_payload, header).

        If the image is identical to the previous frame and skip_unchanged is True,
        returns (None, None).
        """
        ts = time.time() if timestamp is None else timestamp

        # Fast content hash check using downsampled thumbnail
        if skip_unchanged:
            thumb = img.resize((64, 36), Image.Resampling.NEAREST)
            current_hash = hashlib.md5(thumb.tobytes()).hexdigest()
            if current_hash == self._last_hash:
                return None, None
            self._last_hash = current_hash

        # Scale down if needed
        if scale < 0.99:
            new_w = max(160, int(round(img.width * scale)))
            new_h = max(90, int(round(img.height * scale)))
            img_to_encode = img.resize((new_w, new_h), Image.Resampling.BILINEAR)
        else:
            img_to_encode = img

        buf = io.BytesIO()
        img_to_encode.save(buf, format="JPEG", quality=quality, optimize=True)
        jpeg_data = buf.getvalue()

        self._sequence += 1
        header = FrameHeader(
            width=img_to_encode.width,
            height=img_to_encode.height,
            sequence=self._sequence,
            timestamp=ts,
        )

        payload = header.pack() + jpeg_data
        return payload, header

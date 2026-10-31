"""Host-side remote streaming session and WebSocket frame/input pump."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from starlette.websockets import WebSocket, WebSocketDisconnect

from contract.contract import LinkQuality, RemoteSession

from .capture import (
    CaptureBackend,
    FrameEncoder,
    MssCaptureBackend,
    calculate_adaptive_profile,
)
from .input import CoordinateMapper, InputController

log = logging.getLogger(__name__)


class RemoteHostSession:
    """Manages one live remote access session on the host device."""

    def __init__(
        self,
        session_id: str,
        workload_id: str,
        viewer_id: str,
        host_id: str,
        backend: CaptureBackend | None = None,
        input_controller: InputController | None = None,
        inactivity_timeout_sec: float = 60.0,
    ) -> None:
        self.session_id = session_id
        self.workload_id = workload_id
        self.viewer_id = viewer_id
        self.host_id = host_id
        self.consent = False
        self._consent_event = asyncio.Event()

        self.backend = backend or MssCaptureBackend()
        self.input_controller = input_controller or InputController(
            mapper=CoordinateMapper(
                monitor=getattr(
                    self.backend,
                    "get_monitor_info",
                    lambda: {"left": 0, "top": 0, "width": 1920, "height": 1080},
                )()
            )
        )
        self.encoder = FrameEncoder()

        self.inactivity_timeout_sec = inactivity_timeout_sec
        self.created_at = time.time()
        self.last_activity_at = time.time()
        self.current_fps = 15.0

        self.active_ws: WebSocket | None = None
        self._stop_event = asyncio.Event()
        self._is_stopped = False

    def to_contract(self) -> RemoteSession:
        return RemoteSession(
            id=self.session_id,
            workloadId=self.workload_id,
            hostId=self.host_id,
            viewerId=self.viewer_id,
            consent=self.consent,
            fps=self.current_fps,
            ts=time.time(),
        )

    def set_consent(self, allow: bool) -> None:
        self.consent = allow
        self._consent_event.set()

    def stop(self) -> None:
        self._is_stopped = True
        self._stop_event.set()
        if self.active_ws:
            asyncio.create_task(self._safe_close_ws(self.active_ws))

    async def _safe_close_ws(self, ws: WebSocket, code: int = 1000, reason: str = "session ended") -> None:
        try:
            await ws.close(code=code, reason=reason)
        except Exception:
            pass

    async def handle_connection(
        self,
        websocket: WebSocket,
        link_quality_getter: Any | None = None,
    ) -> None:
        """Runs the streaming and input loop for an authorized viewer connection."""
        if self.active_ws is not None:
            # Only one viewer per session
            await websocket.close(code=4409, reason="another viewer is already connected to this session")
            return

        self.active_ws = websocket
        self.last_activity_at = time.time()

        try:
            # 1. Wait for host consent if not yet granted
            if not self.consent:
                try:
                    # Wait up to 30s for host user to approve consent
                    await asyncio.wait_for(self._consent_event.wait(), timeout=30.0)
                except TimeoutError:
                    await websocket.close(code=4408, reason="consent timeout: host did not respond")
                    return

            if not self.consent:
                await websocket.close(code=4403, reason="consent denied by host")
                return

            # 2. Run frame sender and input listener concurrently
            send_task = asyncio.create_task(self._send_frames_loop(websocket, link_quality_getter))
            recv_task = asyncio.create_task(self._recv_input_loop(websocket))
            watchdog_task = asyncio.create_task(self._inactivity_watchdog())

            tasks = [send_task, recv_task, watchdog_task]
            done, pending = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )

            for t in pending:
                t.cancel()

        except WebSocketDisconnect:
            log.info("Remote viewer disconnected: session=%s", self.session_id)
        except Exception as err:
            log.warning("Remote session error: %r", err)
        finally:
            self.active_ws = None
            # Release all held keys and mouse buttons on disconnect
            self.input_controller.release_all()

    async def _send_frames_loop(self, ws: WebSocket, link_quality_getter: Any | None) -> None:
        """Captures frames, compresses them, and sends binary payloads to the viewer."""
        backlog_count = 0

        while not self._stop_event.is_set():
            loop_start = time.monotonic()

            # Query current link quality if available
            link: LinkQuality | None = None
            if link_quality_getter:
                try:
                    link = link_quality_getter(self.viewer_id)
                except Exception:
                    pass

            rtt = link.rttMs if link else 1.0
            mbps = link.mbps if link else 1000.0
            loss = link.lossPct if link else 0.0

            screen_w, screen_h = self.backend.get_screen_size()
            profile = calculate_adaptive_profile(
                backlog_count=backlog_count,
                rtt_ms=rtt,
                mbps=mbps,
                loss_pct=loss,
                original_height=screen_h,
            )
            self.current_fps = profile.fps

            # Capture frame in worker thread to prevent event loop blocking
            try:
                img = await asyncio.to_thread(self.backend.grab_screen)
                payload, header = await asyncio.to_thread(
                    self.encoder.encode,
                    img,
                    profile.jpeg_quality,
                    profile.scale,
                    True,  # skip unchanged frames
                )

                if payload is not None:
                    # Send binary frame over WebSocket
                    await ws.send_bytes(payload)
                    backlog_count = 0
                else:
                    # Unchanged frame skipped
                    pass

            except Exception as err:
                log.debug("Frame capture/send dropped: %r", err)
                backlog_count += 1

            # Sleep to match target FPS
            target_delay = 1.0 / max(5.0, profile.fps)
            elapsed = time.monotonic() - loop_start
            sleep_time = max(0.005, target_delay - elapsed)
            await asyncio.sleep(sleep_time)

    async def _recv_input_loop(self, ws: WebSocket) -> None:
        """Receives JSON input events from viewer and dispatches them to input controller."""
        while not self._stop_event.is_set():
            data = await ws.receive_text()
            self.last_activity_at = time.time()
            try:
                event = json.loads(data)
                if isinstance(event, dict):
                    # Inject in thread to avoid UI thread blocking
                    await asyncio.to_thread(self.input_controller.process_event, event)
            except Exception as err:
                log.debug("Error processing viewer input: %r", err)

    async def _inactivity_watchdog(self) -> None:
        """Monitors session activity and terminates if inactive for too long."""
        while not self._stop_event.is_set():
            await asyncio.sleep(5.0)
            idle_sec = time.time() - self.last_activity_at
            if idle_sec > self.inactivity_timeout_sec:
                log.info("Remote session timed out due to inactivity (%d sec)", idle_sec)
                self.stop()
                break

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from teleport.core import Settings, create_app
from teleport.remote.capture import FakeCaptureBackend, FrameHeader
from teleport.remote.input import CoordinateMapper, InputController


class MockMouse:
    def __init__(self) -> None:
        self.position: tuple[int, int] = (0, 0)
        self.pressed: list[Any] = []
        self.released: list[Any] = []

    def press(self, b: Any) -> None:
        self.pressed.append(b)

    def release(self, b: Any) -> None:
        self.released.append(b)

    def scroll(self, dx: int, dy: int) -> None:
        pass


class MockKeyboard:
    def __init__(self) -> None:
        self.pressed: list[Any] = []
        self.released: list[Any] = []
        self.typed: list[str] = []

    def press(self, k: Any) -> None:
        self.pressed.append(k)

    def release(self, k: Any) -> None:
        self.released.append(k)

    def type(self, t: str) -> None:
        self.typed.append(t)


def test_remote_websocket_streaming_and_input(tmp_path: Path) -> None:
    settings = Settings(home=tmp_path / "home")
    app = create_app(settings)

    ctx = app.state.ctx
    mock_mouse = MockMouse()
    mock_kb = MockKeyboard()
    input_ctrl = InputController(mapper=CoordinateMapper(), mouse=mock_mouse, keyboard=mock_kb)
    fake_backend = FakeCaptureBackend(width=800, height=600)
    fake_backend.set_color_seed(10)

    # Use the naturally registered RemoteServiceImpl, setting its backend
    remote_svc = ctx.remote
    remote_svc.capture_backend = fake_backend

    with TestClient(app) as client:
        # 1. Start session
        start_res = client.post("/api/remote/start", json={"workloadId": "w-test", "viewerId": "viewer-1"})
        assert start_res.status_code == 200
        session_id = start_res.json()["id"]

        # 2. Before consent, token endpoint must reject with 403
        unauth_tok = client.get(f"/api/remote/token/{session_id}")
        assert unauth_tok.status_code == 403

        # 3. Approve consent
        consent_res = client.post("/api/remote/consent", json={"sessionId": session_id, "allow": True})
        assert consent_res.status_code == 200
        assert consent_res.json()["consent"] is True

        # 4. Now token endpoint generates token
        tok_res = client.get(f"/api/remote/token/{session_id}")
        assert tok_res.status_code == 200
        token = tok_res.json()["token"]

        # Inject mock input controller into active host session
        active_session = remote_svc._sessions[session_id]
        active_session.input_controller = input_ctrl

        # 4. Connect WebSocket with token
        with client.websocket_connect(f"/ws/remote/{session_id}?token={token}") as ws:
            # Receive at least one binary frame
            data = ws.receive_bytes()
            assert len(data) >= 20

            # Verify frame header
            header = FrameHeader.unpack(data)
            assert header.width == 800
            assert header.height == 600
            assert header.sequence >= 1

            # Send input events over WebSocket
            ws.send_json({"type": "mouse_move", "x": 0.5, "y": 0.5})
            ws.send_json({"type": "mouse_down", "button": "left", "x": 0.5, "y": 0.5})
            ws.send_json({"type": "key_down", "key": "Enter"})

        # On disconnect, held keys and buttons are cleaned up automatically
        assert len(input_ctrl.held_buttons) == 0
        assert len(input_ctrl.held_keys) == 0

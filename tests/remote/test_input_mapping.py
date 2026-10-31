from __future__ import annotations

from typing import Any

from pynput.mouse import Button

from teleport.remote.input import SPECIAL_KEY_MAP, CoordinateMapper, InputController


class MockMouse:
    def __init__(self) -> None:
        self.position = (0, 0)
        self.pressed: list[Button] = []
        self.released: list[Button] = []
        self.scrolled: list[tuple[int, int]] = []

    def press(self, button: Button) -> None:
        self.pressed.append(button)

    def release(self, button: Button) -> None:
        self.released.append(button)

    def scroll(self, dx: int, dy: int) -> None:
        self.scrolled.append((dx, dy))


class MockKeyboard:
    def __init__(self) -> None:
        self.pressed: list[Any] = []
        self.released: list[Any] = []
        self.typed: list[str] = []

    def press(self, key: Any) -> None:
        self.pressed.append(key)

    def release(self, key: Any) -> None:
        self.released.append(key)

    def type(self, text: str) -> None:
        self.typed.append(text)


def test_coordinate_mapping_primary_monitor() -> None:
    mapper = CoordinateMapper({"left": 0, "top": 0, "width": 1920, "height": 1080})

    # Corners
    assert mapper.map_coords(0.0, 0.0) == (0, 0)
    assert mapper.map_coords(1.0, 1.0) == (1919, 1079)

    # Center
    assert mapper.map_coords(0.5, 0.5) == (960, 540)

    # Out of bounds clamping
    assert mapper.map_coords(-0.5, 1.5) == (0, 1079)


def test_coordinate_mapping_multi_monitor_offsets() -> None:
    # Secondary monitor placed to the right
    mapper_right = CoordinateMapper({"left": 1920, "top": 0, "width": 2560, "height": 1440})
    assert mapper_right.map_coords(0.0, 0.0) == (1920, 0)
    assert mapper_right.map_coords(1.0, 1.0) == (1920 + 2559, 1439)

    # Secondary monitor placed to the left (negative coordinates)
    mapper_left = CoordinateMapper({"left": -1920, "top": 0, "width": 1920, "height": 1080})
    assert mapper_left.map_coords(0.0, 0.0) == (-1920, 0)
    assert mapper_left.map_coords(1.0, 1.0) == (-1, 1079)
    assert mapper_left.map_coords(0.5, 0.5) == (-960, 540)


def test_input_controller_mouse_actions() -> None:
    mapper = CoordinateMapper({"left": 0, "top": 0, "width": 1000, "height": 1000})
    mouse = MockMouse()
    kb = MockKeyboard()
    controller = InputController(mapper=mapper, mouse=mouse, keyboard=kb)

    # Mouse move
    controller.process_event({"type": "mouse_move", "x": 0.25, "y": 0.5})
    assert mouse.position == (250, 500)

    # Mouse down
    controller.process_event({"type": "mouse_down", "button": "left", "x": 0.3, "y": 0.4})
    assert Button.left in mouse.pressed
    assert Button.left in controller.held_buttons

    # Mouse up
    controller.process_event({"type": "mouse_up", "button": "left", "x": 0.3, "y": 0.4})
    assert Button.left in mouse.released
    assert Button.left not in controller.held_buttons

    # Wheel scroll
    controller.process_event({"type": "wheel", "dx": 0, "dy": -200})
    assert len(mouse.scrolled) == 1
    assert mouse.scrolled[0] == (0, 2)


def test_input_controller_keyboard_actions() -> None:
    mapper = CoordinateMapper()
    mouse = MockMouse()
    kb = MockKeyboard()
    controller = InputController(mapper=mapper, mouse=mouse, keyboard=kb)

    # Key down special key (Enter)
    controller.process_event({"type": "key_down", "key": "Enter"})
    assert SPECIAL_KEY_MAP["Enter"] in kb.pressed
    assert SPECIAL_KEY_MAP["Enter"] in controller.held_keys

    # Key up
    controller.process_event({"type": "key_up", "key": "Enter"})
    assert SPECIAL_KEY_MAP["Enter"] in kb.released
    assert SPECIAL_KEY_MAP["Enter"] not in controller.held_keys

    # Printable character
    controller.process_event({"type": "key_down", "key": "a"})
    assert "a" in kb.pressed
    assert "a" in controller.held_keys

    # Text input typing
    controller.process_event({"type": "text", "text": "hello teleport"})
    assert "hello teleport" in kb.typed

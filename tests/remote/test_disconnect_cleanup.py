from __future__ import annotations

from typing import Any

from pynput.keyboard import Key
from pynput.mouse import Button

from teleport.remote.input import CoordinateMapper, InputController


class MockMouse:
    def __init__(self) -> None:
        self.position = (0, 0)
        self.pressed: list[Button] = []
        self.released: list[Button] = []

    def press(self, button: Button) -> None:
        self.pressed.append(button)

    def release(self, button: Button) -> None:
        self.released.append(button)

    def scroll(self, dx: int, dy: int) -> None:
        pass


class MockKeyboard:
    def __init__(self) -> None:
        self.pressed: list[Any] = []
        self.released: list[Any] = []

    def press(self, key: Any) -> None:
        self.pressed.append(key)

    def release(self, key: Any) -> None:
        self.released.append(key)

    def type(self, text: str) -> None:
        pass


def test_disconnect_releases_held_keys_and_buttons() -> None:
    mouse = MockMouse()
    kb = MockKeyboard()
    controller = InputController(mapper=CoordinateMapper(), mouse=mouse, keyboard=kb)

    # Simulate viewer pressing left button and right button
    controller.process_event({"type": "mouse_down", "button": "left"})
    controller.process_event({"type": "mouse_down", "button": "right"})

    # Simulate viewer pressing Control, Shift, and 'x'
    controller.process_event({"type": "key_down", "key": "Control"})
    controller.process_event({"type": "key_down", "key": "Shift"})
    controller.process_event({"type": "key_down", "key": "x"})

    assert controller.held_buttons == {Button.left, Button.right}
    assert Key.ctrl in controller.held_keys
    assert Key.shift in controller.held_keys
    assert "x" in controller.held_keys

    # Now viewer disconnects -> release_all() is called!
    controller.release_all()

    # Verify both sets are empty
    assert len(controller.held_buttons) == 0
    assert len(controller.held_keys) == 0

    # Verify all mouse buttons were released
    assert Button.left in mouse.released
    assert Button.right in mouse.released

    # Verify all keys were released
    assert Key.ctrl in kb.released
    assert Key.shift in kb.released
    assert "x" in kb.released

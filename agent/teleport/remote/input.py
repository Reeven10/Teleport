"""Input injection handling for mouse and keyboard events with coordinate mapping."""

from __future__ import annotations

import logging
from typing import Any

from pynput.keyboard import Controller as KeyboardController
from pynput.keyboard import Key
from pynput.mouse import Button
from pynput.mouse import Controller as MouseController

log = logging.getLogger(__name__)

# Key translation map from Web Event key/code strings to pynput.keyboard.Key
SPECIAL_KEY_MAP: dict[str, Key] = {
    "Enter": Key.enter,
    "Backspace": Key.backspace,
    "Tab": Key.tab,
    "Escape": Key.esc,
    "Space": Key.space,
    " ": Key.space,
    "Shift": Key.shift,
    "ShiftLeft": Key.shift_l,
    "ShiftRight": Key.shift_r,
    "Control": Key.ctrl,
    "ControlLeft": Key.ctrl_l,
    "ControlRight": Key.ctrl_r,
    "Alt": Key.alt,
    "AltLeft": Key.alt_l,
    "AltRight": Key.alt_r,
    "Meta": Key.cmd,
    "MetaLeft": Key.cmd_l,
    "MetaRight": Key.cmd_r,
    "Super": Key.cmd,
    "ArrowUp": Key.up,
    "ArrowDown": Key.down,
    "ArrowLeft": Key.left,
    "ArrowRight": Key.right,
    "Home": Key.home,
    "End": Key.end,
    "PageUp": Key.page_up,
    "PageDown": Key.page_down,
    "Delete": Key.delete,
    "Insert": Key.insert,
    "CapsLock": Key.caps_lock,
    "F1": Key.f1,
    "F2": Key.f2,
    "F3": Key.f3,
    "F4": Key.f4,
    "F5": Key.f5,
    "F6": Key.f6,
    "F7": Key.f7,
    "F8": Key.f8,
    "F9": Key.f9,
    "F10": Key.f10,
    "F11": Key.f11,
    "F12": Key.f12,
}

BUTTON_MAP: dict[str, Button] = {
    "left": Button.left,
    "right": Button.right,
    "middle": Button.middle,
    "0": Button.left,
    "1": Button.middle,
    "2": Button.right,
}


class CoordinateMapper:
    """Translates normalized (0.0 .. 1.0) viewer coordinates to absolute screen pixels.

    Handles multi-monitor geometry, offsets, and display scaling.
    """

    def __init__(self, monitor: dict[str, int] | None = None) -> None:
        # Default monitor geometry
        self.monitor = monitor or {"left": 0, "top": 0, "width": 1920, "height": 1080}

    def set_monitor(self, monitor: dict[str, int]) -> None:
        self.monitor = monitor

    def map_coords(self, norm_x: float, norm_y: float) -> tuple[int, int]:
        """Maps normalized (0.0 to 1.0) into absolute (left + x*width, top + y*height)."""
        left = self.monitor.get("left", 0)
        top = self.monitor.get("top", 0)
        width = max(1, self.monitor.get("width", 1920))
        height = max(1, self.monitor.get("height", 1080))

        # Clamp normalized coordinates to [0.0, 1.0]
        clamped_x = max(0.0, min(1.0, float(norm_x)))
        clamped_y = max(0.0, min(1.0, float(norm_y)))

        abs_x = left + int(round(clamped_x * (width - 1)))
        abs_y = top + int(round(clamped_y * (height - 1)))

        return abs_x, abs_y


class InputController:
    """Dispatches mouse and keyboard events safely, tracking state for cleanup."""

    def __init__(
        self,
        mapper: CoordinateMapper | None = None,
        mouse: Any | None = None,
        keyboard: Any | None = None,
    ) -> None:
        self.mapper = mapper or CoordinateMapper()
        self.mouse = mouse or MouseController()
        self.keyboard = keyboard or KeyboardController()

        # Track held keys and buttons to release on disconnect
        self.held_buttons: set[Button] = set()
        self.held_keys: set[Key | str] = set()

    def process_event(self, event: dict[str, Any]) -> None:
        """Process a structured JSON input event from the viewer."""
        event_type = event.get("type", "")

        try:
            if event_type == "mouse_move":
                norm_x = event.get("x", 0.0)
                norm_y = event.get("y", 0.0)
                abs_x, abs_y = self.mapper.map_coords(norm_x, norm_y)
                self.mouse.position = (abs_x, abs_y)

            elif event_type == "mouse_down":
                btn = self._resolve_button(event.get("button", "left"))
                if "x" in event and "y" in event:
                    abs_x, abs_y = self.mapper.map_coords(event["x"], event["y"])
                    self.mouse.position = (abs_x, abs_y)
                self.mouse.press(btn)
                self.held_buttons.add(btn)

            elif event_type == "mouse_up":
                btn = self._resolve_button(event.get("button", "left"))
                if "x" in event and "y" in event:
                    abs_x, abs_y = self.mapper.map_coords(event["x"], event["y"])
                    self.mouse.position = (abs_x, abs_y)
                self.mouse.release(btn)
                self.held_buttons.discard(btn)

            elif event_type == "wheel":
                dx = event.get("dx", 0) or event.get("deltaX", 0)
                dy = event.get("dy", 0) or event.get("deltaY", 0)
                # Normalize wheel ticks
                tick_x = int(-dx / 100) if dx != 0 else 0
                tick_y = int(-dy / 100) if dy != 0 else 0
                if tick_x == 0 and dx != 0:
                    tick_x = -1 if dx > 0 else 1
                if tick_y == 0 and dy != 0:
                    tick_y = -1 if dy > 0 else 1
                self.mouse.scroll(tick_x, tick_y)

            elif event_type == "key_down":
                key_token = self._resolve_key(event)
                if key_token:
                    self.keyboard.press(key_token)
                    self.held_keys.add(key_token)

            elif event_type == "key_up":
                key_token = self._resolve_key(event)
                if key_token:
                    self.keyboard.release(key_token)
                    self.held_keys.discard(key_token)

            elif event_type == "text":
                text = event.get("text", "")
                if text:
                    self.keyboard.type(text)

        except Exception as err:
            log.warning("Error injecting input event %r: %r", event, err)

    def release_all(self) -> None:
        """Release all held keys and mouse buttons. Called on viewer disconnect."""
        # Release buttons
        for btn in list(self.held_buttons):
            try:
                self.mouse.release(btn)
            except Exception as err:
                log.debug("Error releasing mouse button %r: %r", btn, err)
        self.held_buttons.clear()

        # Release keys
        for key in list(self.held_keys):
            try:
                self.keyboard.release(key)
            except Exception as err:
                log.debug("Error releasing key %r: %r", key, err)
        self.held_keys.clear()

    def _resolve_button(self, btn_val: Any) -> Button:
        key = str(btn_val).lower()
        return BUTTON_MAP.get(key, Button.left)

    def _resolve_key(self, event: dict[str, Any]) -> Key | str | None:
        key_str = event.get("key", "")
        code_str = event.get("code", "")

        # Try code first (e.g. "ShiftLeft"), then key (e.g. "Enter")
        if code_str in SPECIAL_KEY_MAP:
            return SPECIAL_KEY_MAP[code_str]
        if key_str in SPECIAL_KEY_MAP:
            return SPECIAL_KEY_MAP[key_str]

        # Single printable character
        if len(key_str) == 1:
            return key_str

        return None

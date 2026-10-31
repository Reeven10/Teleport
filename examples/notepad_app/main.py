#!/usr/bin/env python3
"""Interactive GUI Notepad / Collaborative Scratchpad for Teleport Remote Access.

Demonstrates fallback to Remote Access: when evaluated for migration,
feasibility confirms it is interactive and remoteCapable, allowing viewers to
connect to the host screen and inject keystrokes/clicks remotely.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import teleport_sdk as teleport

DEFAULT_TEXT = (
    "=== Teleport Collaborative Scratchpad ===\n\n"
    "This workload is running live on the host node.\n"
    "When accessed remotely, mouse clicks, scrolls, and keystrokes\n"
    "are captured in the browser canvas and forwarded via WebSocket.\n\n"
    "Type your notes here:\n"
)


def load_doc() -> tuple[str, dict[str, Any]]:
    text_path = Path("document.txt")
    state_path = Path("state.json")

    text = text_path.read_text(encoding="utf-8") if text_path.exists() else DEFAULT_TEXT
    state: dict[str, Any] = {}
    if state_path.exists():
        try:
            loaded = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                state = loaded
        except Exception:
            state = {}
    return text, state


def save_doc(text: str, cursor_index: str = "1.0") -> None:
    Path("document.txt").write_text(text, encoding="utf-8")
    meta = {
        "cursor_index": cursor_index,
        "char_count": len(text),
        "last_saved": time.time(),
    }
    Path("state.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def run_tkinter(initial_text: str, sdk_active: bool) -> None:
    """Run standard Tkinter GUI desktop window."""
    import tkinter as tk
    from tkinter import scrolledtext

    root = tk.Tk()
    root.title("Teleport Notepad (Host Workspace)")
    root.geometry("640x480")

    # Header label
    lbl = tk.Label(
        root,
        text="Teleport Remote Access Workload - Interactive GUI",
        font=("Segoe UI", 10, "bold"),
        bg="#1e293b",
        fg="#f8fafc",
        pady=8,
    )
    lbl.pack(fill=tk.X)

    # Scrolled text area
    text_area = scrolledtext.ScrolledText(
        root,
        wrap=tk.WORD,
        font=("Consolas", 11),
        undo=True,
    )
    text_area.insert(tk.INSERT, initial_text)
    text_area.pack(expand=True, fill=tk.BOTH, padx=4, pady=4)

    # Autosave timer
    def autosave() -> None:
        if sdk_active and teleport.should_stop():
            root.destroy()
            return
        content = text_area.get("1.0", tk.END)
        cur = text_area.index(tk.INSERT)
        save_doc(content, cur)
        if sdk_active:
            teleport.checkpoint("document", {"text": content, "cursor": cur})
        root.after(1000, autosave)

    root.after(1000, autosave)
    root.mainloop()


def run_headless_simulation(initial_text: str, sdk_active: bool) -> None:
    """Fallback runner for headless environments (CI / servers without X11 or DISPLAY)."""
    print(
        "[Notepad] Collaborative Scratchpad active (headless simulation). Running text loop...",
        flush=True,
    )
    text = initial_text
    counter = 0

    while True:
        if sdk_active and teleport.should_stop():
            print("[Notepad] Stopped by controller.", flush=True)
            break

        counter += 1
        line = f"Simulated Remote Keystroke Entry #{counter:04d} at {time.strftime('%H:%M:%S')}\n"
        text += line
        save_doc(text, cursor_index=f"{counter}.0")
        if sdk_active:
            teleport.checkpoint("document", {"text": text, "cursor": f"{counter}.0"})

        print(f"[Notepad] Document updated: {len(text)} characters (line {counter})", flush=True)
        if os.environ.get("RUN_ONCE") == "1":
            break
        time.sleep(1.0)


def main() -> None:
    print("[Notepad] Initializing Teleport Interactive Notepad Workload...", flush=True)

    sdk_active = False
    try:
        teleport.init()
        sdk_active = True
        print("[Notepad] Teleport SDK connected to agent.", flush=True)
    except Exception as e:
        print(f"[Notepad] Standalone execution ({e}).", flush=True)

    text, _ = load_doc()
    if sdk_active:
        restored = teleport.restore("document")
        if isinstance(restored, dict):
            text = str(restored.get("text", text))

    has_display = True
    if "--headless" in sys.argv:
        has_display = False
    elif sys.platform != "win32" and not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        has_display = False

    if has_display:
        try:
            run_tkinter(text, sdk_active)
        except Exception as e:
            print(
                f"[Notepad] Tkinter initialization failed ({e}), falling back to headless runner.",
                flush=True,
            )
            run_headless_simulation(text, sdk_active)
    else:
        run_headless_simulation(text, sdk_active)


if __name__ == "__main__":
    main()

"""Collaborative Scratchpad GUI App.

Interactive desktop text editor using Tkinter (with headless fallback for CI).
Used to demonstrate remote access with real mouse and keyboard input forwarding.
Keeps document text and cursor position in state checkpoints.
Runs standalone without Teleport.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# Optional Teleport SDK import
try:
    import teleport_sdk as teleport
except ImportError:
    repo_sdk = Path(__file__).resolve().parents[2] / "sdk"
    if repo_sdk.exists():
        sys.path.insert(0, str(repo_sdk))
        try:
            import teleport_sdk as teleport
        except ImportError:
            teleport = None
    else:
        teleport = None


DEFAULT_TEXT = (
    "=== Teleport Collaborative Scratchpad ===\n\n"
    "This workload is running live on the host node.\n"
    "When accessed remotely, mouse clicks, scrolls, and keystrokes\n"
    "are captured in the browser canvas and forwarded via WebSocket.\n\n"
    "Type your notes here:\n"
)


def load_doc() -> tuple[str, dict[str, object]]:
    text_path = Path("document.txt")
    state_path = Path("state.json")

    text = text_path.read_text(encoding="utf-8") if text_path.exists() else DEFAULT_TEXT
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
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
    import tkinter as tk

    root = tk.Tk()
    root.title("Teleport Collaborative Scratchpad")
    root.geometry("640x480")

    header_frame = tk.Frame(root, bg="#1e293b", height=40)
    header_frame.pack(fill=tk.X)

    title_label = tk.Label(
        header_frame,
        text="Teleport Scratchpad [Remote Access Viewport Ready]",
        bg="#1e293b",
        fg="#38bdf8",
        font=("Segoe UI", 10, "bold"),
        padx=10,
        pady=8,
    )
    title_label.pack(side=tk.LEFT)

    status_var = tk.StringVar(value="Ready")
    status_label = tk.Label(
        header_frame,
        textvariable=status_var,
        bg="#1e293b",
        fg="#94a3b8",
        font=("Segoe UI", 9),
        padx=10,
    )
    status_label.pack(side=tk.RIGHT)

    text_area = tk.Text(root, font=("Consolas", 11), wrap=tk.WORD, undo=True)
    text_area.insert("1.0", initial_text)
    text_area.pack(expand=True, fill=tk.BOTH, padx=8, pady=8)

    def on_change(event: object = None) -> None:
        content = text_area.get("1.0", tk.END)
        cur = text_area.index(tk.INSERT)
        save_doc(content, cur)
        if sdk_active and teleport:
            teleport.checkpoint("document_state", {
                "text": content,
                "cursor": cur,
                "ts": time.time(),
            })
        status_var.set(f"Chars: {len(content)} · Saved")

    text_area.bind("<KeyRelease>", on_change)

    def check_teleport_stop() -> None:
        if sdk_active and teleport and teleport.should_stop():
            print("[Notepad] Stop requested by controller. Saving state...", flush=True)
            on_change()
            root.destroy()
            return
        root.after(500, check_teleport_stop)

    root.after(500, check_teleport_stop)
    root.mainloop()


def run_headless(initial_text: str, sdk_active: bool) -> None:
    print("[Notepad] Running in headless/console mode...", flush=True)
    content = initial_text
    step = 0
    while True:
        if sdk_active and teleport and teleport.should_stop():
            print("[Notepad] Stopped by controller.", flush=True)
            break
        step += 1
        content += f"\n[Auto-Note {step:03d}] Remote operator heartbeat @ {time.strftime('%X')}"
        save_doc(content)
        if sdk_active and teleport:
            teleport.checkpoint("document_state", {"text": content, "step": step, "ts": time.time()})
        print(f"[Notepad] Document updated: {len(content)} characters. State checkpointed.", flush=True)
        if os.environ.get("RUN_ONCE") == "1":
            break
        time.sleep(1.0)


def main() -> None:
    print("[Notepad] Initializing Collaborative Scratchpad...", flush=True)

    sdk_active = False
    if teleport is not None:
        try:
            teleport.init()
            sdk_active = True
            print("[Notepad] Teleport SDK connected to agent.", flush=True)
        except Exception as e:
            print(f"[Notepad] Standalone mode ({e}).", flush=True)

    # Restore from checkpoint if available
    initial_text = None
    if sdk_active and teleport:
        restored = teleport.restore("document_state")
        if isinstance(restored, dict) and "text" in restored:
            initial_text = str(restored["text"])

    if not initial_text:
        initial_text, _ = load_doc()

    save_doc(initial_text)

    # Try Tkinter GUI first; fallback to headless if no DISPLAY
    use_gui = True
    if "--headless" in sys.argv or os.environ.get("HEADLESS") == "1":
        use_gui = False

    if use_gui:
        try:
            run_tkinter(initial_text, sdk_active)
        except Exception as e:
            print(f"[Notepad] GUI initialization skipped ({e}). Falling back to headless runner.", flush=True)
            run_headless(initial_text, sdk_active)
    else:
        run_headless(initial_text, sdk_active)


if __name__ == "__main__":
    main()

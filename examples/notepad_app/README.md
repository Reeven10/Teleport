# Collaborative Scratchpad GUI App

An interactive desktop text editor designed to demonstrate Teleport's **Remote Access Viewport** with live mouse and keyboard input forwarding.

## Overview

The app maintains document text and cursor position across checkpoints defined in `teleport.yaml`.

When accessed via Teleport Remote Access:
- The host captures screen frames at 10–20 FPS using `mss` and sends compressed frames over WebSocket `/ws/remote/{sessionId}`.
- The web viewer canvas captures mouse clicks, text selection, and keyboard input, forwarding normalized events to the host where `pynput` injects them into the scratchpad window.
- If run in a headless environment without an X11/Wayland/Windows display server, it automatically falls back to an interactive console loop with state checkpointing.

## Running Standalone

```bash
cd examples/notepad_app
python main.py
```


"""Counter job: counts up, checkpoints every step, resumes from restore.

Env: COUNTER_TARGET (default 100000000, so a demo never ends by itself), COUNTER_STEP_S (default 0.1).
Runs standalone or under Teleport.
"""

from __future__ import annotations

import os
import struct
import sys
import threading
import time
from pathlib import Path
from typing import Any

import teleport_sdk as teleport


def main() -> int:
    teleport.init()
    lock = threading.Lock()

    config = teleport.restore("config") or {
        "target": int(os.environ.get("COUNTER_TARGET", "100000000")),
        "stepS": float(os.environ.get("COUNTER_STEP_S", "0.1")),
    }
    assert isinstance(config, dict)
    counter = teleport.restore("counter")
    count = int(counter["count"]) if isinstance(counter, dict) else 0
    history_state = teleport.restore("history")
    history: list[int] = list(history_state["values"]) if isinstance(history_state, dict) else []
    meta_state = teleport.restore("meta")
    runs = int(meta_state["runs"]) + 1 if isinstance(meta_state, dict) and "runs" in meta_state else 1
    teleport.restore("journal")  # files come back in place (out/journal.txt)
    journal = Path("out/journal.txt")
    journal.parent.mkdir(parents=True, exist_ok=True)

    print(f"resumed count={count} runs={runs}" if counter else f"fresh start runs={runs}", flush=True)

    def save_all() -> None:
        with lock:
            state: dict[str, Any] = {"count": count}
            teleport.checkpoint("config", config)
            teleport.checkpoint("counter", state)
            teleport.checkpoint("history", {"values": history[-20:]})
            teleport.checkpoint("stats", struct.pack("<qd", count, time.time()))
            teleport.checkpoint("journal", files=[journal])
            teleport.checkpoint("meta", {"runs": runs, "pid": os.getpid()})

    teleport.on_fence(save_all)
    save_all()

    while count < int(config["target"]) and not teleport.should_stop():
        time.sleep(float(config["stepS"]))
        with lock:
            count += 1
            history.append(count)
            with journal.open("a", encoding="utf-8") as f:
                f.write(f"{count}\n")
            teleport.checkpoint("counter", {"count": count})
        print(f"count={count}", flush=True)
        if count % 5 == 0:
            save_all()

    save_all()
    print(f"done count={count} stopped={teleport.should_stop()}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

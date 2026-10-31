"""Teleport SDK: make a workload checkpointable and migratable.

    import teleport_sdk as teleport
    teleport.init()
    state = teleport.restore("counter") or {"count": 0}
    teleport.on_fence(lambda: teleport.checkpoint("counter", state))
    while not teleport.should_stop():
        ...
        teleport.checkpoint("counter", state)

Without an agent it works standalone, saving checkpoints under ./.teleport-local.
"""

from ._client import (
    Client,
    FenceCallback,
    TeleportError,
    checkpoint,
    init,
    on_fence,
    restore,
    should_stop,
)
from .unit import State

__version__ = "0.1.0"
__all__ = [
    "Client",
    "FenceCallback",
    "State",
    "TeleportError",
    "checkpoint",
    "init",
    "on_fence",
    "restore",
    "should_stop",
]

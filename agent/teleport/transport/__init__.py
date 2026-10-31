"""Transport module (P2).

Provides the PeerLink implementation, pairing manager, link type detection,
and peer WebSocket client and server channels.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from contract.contract import PeerLink

from .link_detector import classify_interface, select_best_address
from .service import PeerLinkService

if TYPE_CHECKING:
    from ..core.context import Context


def create_peer_link(ctx: Context) -> PeerLink:
    """Create and return a production PeerLink service satisfying contract.PeerLink Protocol."""
    return PeerLinkService(ctx)


__all__ = [
    "PeerLink",
    "PeerLinkService",
    "classify_interface",
    "create_peer_link",
    "select_best_address",
]

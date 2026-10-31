"""Peer stats relay (core wiring): sends local stats to connected peers as peer.stats and republishes
peers' stats on the local bus, so each dashboard sees every paired device live.

Interim home until the peer link does this itself (issue P2-2), then delete this module.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from contract.contract import PeerMessage, PeerStats, StatsUpdateEvent

from .context import Context

log = logging.getLogger("teleport.relay")


class PeerStatsRelay:
    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self._unsubscribe: Callable[[], None] | None = None

    async def _on_local_stats(self, event: StatsUpdateEvent) -> None:
        if event.stats.deviceId != self.ctx.device_id:
            return
        for peer in self.ctx.peer_directory.connected():
            try:
                await self.ctx.peers.send(peer, PeerStats(stats=event.stats))
            except Exception as e:
                log.debug("could not send stats to %s: %s", peer, e)

    async def _on_peer_message(self, from_id: str, msg: PeerMessage) -> None:
        if isinstance(msg, PeerStats) and msg.stats.deviceId == from_id:
            await self.ctx.bus.publish(StatsUpdateEvent(stats=msg.stats))

    async def startup(self) -> None:
        self.ctx.peers.on_message(self._on_peer_message)
        self._unsubscribe = self.ctx.bus.subscribe(StatsUpdateEvent, self._on_local_stats)

    async def shutdown(self) -> None:
        if self._unsubscribe:
            self._unsubscribe()

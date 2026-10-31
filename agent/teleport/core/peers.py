"""Known peer ids, kept current from bus events and peer traffic, so periodic senders (lease
sync) never call peers.list_peers() in a hot loop: with the P2 device service that call
re-probes the local device synchronously (~0.4 s, issue P2-7) and stalls the event loop."""

from __future__ import annotations

from collections.abc import Callable

from contract.contract import DevicePairedEvent, LinkUpdateEvent, PeerMessage

from .context import Context


class PeerDirectory:
    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self._ids: set[str] = set()
        self._unsubscribe: list[Callable[[], None]] = []

    def ids(self) -> list[str]:
        return sorted(self._ids)

    def connected(self) -> list[str]:
        """Known peers with a live link right now."""
        return [p for p in self.ids() if self.ctx.peers.link_quality(p) is not None]

    def add(self, device_id: str) -> None:
        if device_id != self.ctx.device_id:
            self._ids.add(device_id)

    async def _on_paired(self, event: DevicePairedEvent) -> None:
        self.add(event.device.id)

    async def _on_link(self, event: LinkUpdateEvent) -> None:
        self.add(event.link.peerId)

    async def _on_message(self, from_id: str, msg: PeerMessage) -> None:
        self.add(from_id)

    async def startup(self) -> None:
        for peer in self.ctx.peers.list_peers():  # once, at startup
            self.add(peer.id)
        self.ctx.peers.on_message(self._on_message)
        self._unsubscribe = [
            self.ctx.bus.subscribe(DevicePairedEvent, self._on_paired),
            self.ctx.bus.subscribe(LinkUpdateEvent, self._on_link),
        ]

    async def shutdown(self) -> None:
        for unsub in self._unsubscribe:
            unsub()

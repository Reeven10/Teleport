"""Typed async event bus. Handlers run concurrently; one failing handler never breaks the others."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar, cast

from contract.contract import BusEvent

log = logging.getLogger("teleport.bus")

E = TypeVar("E")
Handler = Callable[[Any], Awaitable[None]]
Unsubscribe = Callable[[], None]


class EventBus:
    def __init__(self) -> None:
        self._subs: list[tuple[type[Any] | None, Handler]] = []
        self._queues: set[asyncio.Queue[BusEvent]] = set()

    def subscribe(self, event_type: type[E], handler: Callable[[E], Awaitable[None]]) -> Unsubscribe:
        """Call `handler` for every published event of `event_type`, e.g. StatsUpdateEvent."""
        return self._add(event_type, cast(Handler, handler))

    def subscribe_all(self, handler: Callable[[BusEvent], Awaitable[None]]) -> Unsubscribe:
        return self._add(None, cast(Handler, handler))

    def _add(self, event_type: type[Any] | None, handler: Handler) -> Unsubscribe:
        entry = (event_type, handler)
        self._subs.append(entry)

        def unsubscribe() -> None:
            if entry in self._subs:
                self._subs.remove(entry)

        return unsubscribe

    def open_queue(self, maxsize: int = 1000) -> asyncio.Queue[BusEvent]:
        """Queue receiving every event (oldest dropped when full). Close with close_queue()."""
        q: asyncio.Queue[BusEvent] = asyncio.Queue(maxsize)
        self._queues.add(q)
        return q

    def close_queue(self, q: asyncio.Queue[BusEvent]) -> None:
        self._queues.discard(q)

    async def publish(self, event: BusEvent) -> None:
        for q in list(self._queues):
            if q.full():
                q.get_nowait()
            q.put_nowait(event)
        handlers = [h for t, h in list(self._subs) if t is None or isinstance(event, t)]
        if not handlers:
            return
        results = await asyncio.gather(*(h(event) for h in handlers), return_exceptions=True)
        for r in results:
            if isinstance(r, BaseException):
                log.error("bus handler failed for %s", event.t, exc_info=r)

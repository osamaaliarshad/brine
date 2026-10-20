"""In-process fan-out of "something changed" notifications to connected browsers.

Messages are small hints ({"type": "minion", "id": "rover-01"}), not data: the browser
re-fetches what it shows. That keeps one source of truth (the REST API) and means a missed
message can never leave a browser with wrong data, only briefly old data.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from app.ingest import Changes

log = logging.getLogger(__name__)

Message = dict[str, Any]


class EventBus:
    def __init__(self, queue_size: int = 1000) -> None:
        self._queue_size = queue_size
        self._subscribers: set[asyncio.Queue[Message]] = set()

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def publish(self, message: Message) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                # A stalled browser: drop its backlog and tell it to refetch everything.
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait({"type": "resync"})

    def publish_changes(self, changes: Changes) -> None:
        if changes.fleet:
            self.publish({"type": "fleet"})
        if changes.status:
            self.publish({"type": "status"})
        for mid in sorted(changes.minions):
            self.publish({"type": "minion", "id": mid})
        for jid in sorted(changes.jobs):
            self.publish({"type": "job", "jid": jid})

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[Message]]:
        queue: asyncio.Queue[Message] = asyncio.Queue(self._queue_size)
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)

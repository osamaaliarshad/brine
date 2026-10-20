"""The last few hundred raw Salt events, for the Events page.

Kept in memory only (they're a live view, not history: jobs and presence are what brine stores).
New subscribers get the recent backlog first, then live events.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import json
from collections import deque
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from app.salt.events import SaltEvent

MAX_DATA_BYTES = 32_000


def _compact(data: dict[str, Any]) -> dict[str, Any]:
    """Shorten what's useless or huge in a browser: public keys, giant job returns."""
    out = dict(data)
    pub = out.get("pub")
    if isinstance(pub, str) and len(pub) > 80:
        out["pub"] = pub[:40] + "…" + pub[-20:]
    size = len(json.dumps(out, default=str))
    if size > MAX_DATA_BYTES and "return" in out:
        out["return"] = {
            "_brine": f"return omitted from the live view ({size:,} bytes); see the job"
        }
    return out


class EventLog:
    def __init__(self, maxlen: int = 500) -> None:
        self._events: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._seq = itertools.count(1)
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    def append(self, event: SaltEvent) -> dict[str, Any]:
        entry = {
            "seq": next(self._seq),
            "received_at": datetime.now(UTC).isoformat(),
            "tag": event.tag,
            "data": _compact(event.data),
        }
        self._events.append(entry)
        for queue in list(self._subscribers):
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(entry)  # a stalled browser just misses events
        return entry

    def recent(self) -> list[dict[str, Any]]:
        return list(self._events)

    @contextlib.asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[dict[str, Any]]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(1000)
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)

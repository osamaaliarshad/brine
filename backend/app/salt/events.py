"""Salt events as delivered by salt-api's `/events` server-sent-event stream."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterable, AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SaltEvent:
    tag: str
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def stamp(self) -> datetime | None:
        """When the master fired the event (Salt's `_stamp`, UTC)."""
        return parse_stamp(self.data.get("_stamp"))


def parse_stamp(value: Any) -> datetime | None:
    """Parse Salt's `_stamp` (naive ISO-8601 in UTC)."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=UTC)
    except ValueError:
        return None


def parse_job_start_time(value: Any) -> datetime | None:
    """Parse `StartTime` from `jobs.list_jobs` ("2026, Oct 20 14:01:33.273737")."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y, %b %d %H:%M:%S.%f").replace(tzinfo=UTC)
    except ValueError:
        return None


async def parse_sse(lines: AsyncIterable[str]) -> AsyncIterator[SaltEvent]:
    """Turn SSE lines into events. salt-api sends `tag:` and `data:` lines, then a blank line;
    the JSON in `data` repeats the tag, so only `data` is used."""
    data_lines: list[str] = []
    async for line in lines:
        if line == "":
            if data_lines:
                payload, data_lines = "\n".join(data_lines), []
                event = _decode(payload)
                if event is not None:
                    yield event
            continue
        if line.startswith(":"):
            continue  # SSE comment / keep-alive
        name, _, value = line.partition(":")
        if name == "data":
            data_lines.append(value.removeprefix(" "))


def _decode(payload: str) -> SaltEvent | None:
    try:
        obj = json.loads(payload)
        tag = obj["tag"]
        data = obj.get("data")
    except (ValueError, KeyError, TypeError):
        log.warning("ignoring malformed event payload: %.200s", payload)
        return None
    return SaltEvent(tag=str(tag), data=data if isinstance(data, dict) else {"value": data})

"""The live Salt event bus (SaltGUI's Events page) and the master's reactor config."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.api.deps import RuntimeDep
from app.api.schemas import Reactor
from app.auth.users import CurrentUser
from app.masking import mask_event
from app.salt.client import SaltApiError

router = APIRouter()

KEEPALIVE_SECONDS = 15


def _sse(entry: dict[str, Any]) -> str:
    return f"data: {json.dumps(entry, default=str)}\n\n"


@router.get("/events/stream")
async def event_stream(
    request: Request, runtime: RuntimeDep, user: CurrentUser
) -> StreamingResponse:
    """Server-sent events: the recent backlog, then each Salt event as brine receives it.
    Every message carries a `seq`, so clients can drop duplicates after reconnecting. Pillar
    data in job returns is hidden from everyone but admins."""
    log = runtime.collector.event_log
    shown = (lambda entry: entry) if user.role == "admin" else mask_event

    async def events() -> AsyncIterator[str]:
        async with log.subscribe() as queue:
            for entry in log.recent():
                yield _sse(shown(entry))
            while not await request.is_disconnected():
                try:
                    entry = await asyncio.wait_for(queue.get(), KEEPALIVE_SECONDS)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                yield _sse(shown(entry))

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/reactors", response_model=list[Reactor])
async def reactors(runtime: RuntimeDep) -> list[Reactor]:
    """The master's `reactor` setting. Only that key leaves the server: the rest of the master
    config can hold secrets."""
    try:
        values = await runtime.client.wheel("config.values")
    except SaltApiError as exc:
        raise HTTPException(502, f"salt-api: {exc}") from exc
    result = []
    for entry in (values or {}).get("reactor") or []:
        if isinstance(entry, dict):
            for tag, sls in entry.items():
                files = sls if isinstance(sls, list) else [sls]
                result.append(Reactor(tag=str(tag), sls=[str(f) for f in files]))
    return result

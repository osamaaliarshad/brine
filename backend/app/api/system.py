from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.deps import RuntimeDep, SessionDep
from app.api.fleet import presence_info
from app.api.schemas import Key, SaltApiStatus, SystemStatus
from app.models import Minion
from app.status import minion_status

router = APIRouter()

KEEPALIVE_SECONDS = 15


@router.get("/keys", response_model=list[Key])
async def keys(runtime: RuntimeDep, session: SessionDep) -> list[Key]:
    presence = await presence_info(session)
    now = datetime.now(UTC)
    stale_after = timedelta(minutes=runtime.settings.fleet.stale_after_minutes)
    rows = await session.scalars(
        select(Minion).where(Minion.key_state != "deleted").order_by(Minion.id)
    )
    return [
        Key(
            id=m.id,
            key_state=m.key_state,
            fingerprint=m.key_fingerprint,
            first_seen_at=m.first_seen_at,
            last_seen_at=m.last_seen_at,
            status=minion_status(
                connected=m.connected,
                last_seen_at=m.last_seen_at,
                presence_at=presence.checked_at,
                now=now,
                stale_after=stale_after,
            )
            if m.key_state == "accepted"
            else None,
        )
        for m in rows
    ]


@router.get("/status", response_model=SystemStatus)
async def status(request: Request, runtime: RuntimeDep, session: SessionDep) -> SystemStatus:
    collector = runtime.collector.status
    return SystemStatus(
        version=request.app.version,
        salt_api=SaltApiStatus(
            url=str(runtime.settings.salt_api.url),
            connected=collector.connected,
            since=collector.since,
            error=collector.error,
            last_event_at=collector.last_event_at,
        ),
        presence_method_configured=runtime.settings.presence.method,
        presence=await presence_info(session),
        stale_after_minutes=runtime.settings.fleet.stale_after_minutes,
    )


@router.get("/stream")
async def stream(request: Request, runtime: RuntimeDep) -> StreamingResponse:
    """Server-sent events: small "this changed" hints; clients re-fetch what they display."""

    async def events() -> AsyncIterator[str]:
        async with runtime.bus.subscribe() as queue:
            yield f"data: {json.dumps({'type': 'hello'})}\n\n"
            while not await request.is_disconnected():
                try:
                    message = await asyncio.wait_for(queue.get(), KEEPALIVE_SECONDS)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                yield f"data: {json.dumps(message)}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app import inventory
from app.api.deps import RuntimeDep, SessionDep
from app.api.fleet import configured_columns, presence_info
from app.api.inventory import refused_sources
from app.api.schemas import (
    AuthSettings,
    DatabaseSettings,
    FleetSettings,
    InventoryCheck,
    InventorySettings,
    PresenceSettings,
    RoleCounts,
    SaltApiSettings,
    SaltApiStatus,
    SettingsView,
    SystemStatus,
)
from app.auth.oidc import provider_name
from app.db import async_url

router = APIRouter()

KEEPALIVE_SECONDS = 15


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


@router.get("/settings", response_model=SettingsView)
async def settings_view(request: Request, runtime: RuntimeDep, session: SessionDep) -> SettingsView:
    s = runtime.settings
    db_url = async_url(s.database)
    return SettingsView(
        version=request.app.version,
        salt_api=SaltApiSettings(
            url=str(s.salt_api.url),
            username=s.salt_api.username,
            eauth=s.salt_api.eauth,
            verify_tls=s.salt_api.verify_tls,
            timeout_seconds=s.salt_api.timeout_seconds,
        ),
        presence=PresenceSettings(
            method=s.presence.method,
            active_method=runtime.collector.status.presence_method,
            poll_seconds=s.presence.poll_seconds,
        ),
        fleet=FleetSettings(
            stale_after_minutes=s.fleet.stale_after_minutes,
            grains_refresh_minutes=s.fleet.grains_refresh_minutes,
            columns=configured_columns(runtime),
        ),
        jobs_backfill_limit=s.jobs.backfill_limit,
        retention=s.retention.model_dump(),
        database=DatabaseSettings(
            backend=db_url.get_backend_name(),
            url=db_url.set(drivername=db_url.get_backend_name()).render_as_string(
                hide_password=True
            ),
        ),
        auth=AuthSettings(
            provider=s.auth.provider,
            issuer=str(s.auth.issuer) if s.auth.issuer else None,
            display_name=provider_name(s.auth),
            configured=bool(s.auth.issuer and s.auth.client_id and s.auth.client_secret),
            allowed_domains=s.auth.allowed_domains,
            anonymous_role=s.auth.anonymous_role,
            session_hours=s.auth.session_hours,
            role_patterns=RoleCounts(
                viewer=len(s.roles.viewer),
                operator=len(s.roles.operator),
                admin=len(s.roles.admin),
            ),
        ),
        inventory=InventorySettings(
            refresh_hours=s.inventory.refresh_hours,
            checks=[
                InventoryCheck(name=name, command=command)
                for name, command in s.inventory.checks.items()
            ],
            acl=inventory.acl_lines(s),
            refused=await refused_sources(session, s),
        ),
    )

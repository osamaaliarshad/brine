"""Everything the running app holds: settings, database, salt-api client, collector, bus."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
from collections.abc import Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.auth.oidc import OidcClient, make_oidc_client
from app.bus import EventBus
from app.config import Settings
from app.db import create_engine, migrate, session_factory
from app.ingest import Ingest
from app.models import SystemState
from app.salt.client import SaltApiClient
from app.salt.collector import Collector

log = logging.getLogger(__name__)

SESSION_SECRET_STATE = "session_secret"  # noqa: S105 (a database key, not a secret)


async def _session_secret(settings: Settings, sessions: async_sessionmaker[AsyncSession]) -> str:
    """The configured secret, or one generated on first start and kept in the database, so
    sessions survive restarts without anyone having to set one up."""
    if settings.auth.session_secret:
        return settings.auth.session_secret.get_secret_value()
    async with sessions() as s, s.begin():
        row = await s.get(SystemState, SESSION_SECRET_STATE)
        if row is None:
            secret = secrets.token_urlsafe(48)
            s.add(SystemState(key=SESSION_SECRET_STATE, value=secret, updated_at=datetime.now(UTC)))
            return secret
        return str(row.value)


@dataclass
class Runtime:
    settings: Settings
    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]
    bus: EventBus
    ingest: Ingest
    client: SaltApiClient
    collector: Collector
    session_secret: str = field(repr=False)
    oidc: OidcClient | None = field(default=None, repr=False)
    _tasks: list[asyncio.Task[None]] = field(default_factory=list, repr=False)

    @classmethod
    async def start(cls, settings: Settings, *, run_collector: bool = True) -> Runtime:
        await migrate(settings.database)
        engine = create_engine(settings.database)
        sessions = session_factory(engine)
        bus = EventBus()
        ingest = Ingest(sessions, service_user=settings.salt_api.username)
        client = SaltApiClient(settings.salt_api)
        collector = Collector(client, ingest, settings, bus)
        runtime = cls(
            settings,
            engine,
            sessions,
            bus,
            ingest,
            client,
            collector,
            session_secret=await _session_secret(settings, sessions),
            oidc=make_oidc_client(settings.auth),
        )
        if settings.auth.provider == "none":
            log.warning(
                "sign-in is OFF (auth.provider: none): everyone who can reach brine is treated "
                "as %s. Use this for the demo or a laptop only.",
                settings.auth.anonymous_role,
            )
        if run_collector:
            runtime.background(collector.run(), "collector")
        return runtime

    def background(self, work: Coroutine[Any, Any, None], name: str) -> None:
        """Run `work` for as long as brine runs; it's cancelled on shutdown."""
        self._tasks.append(asyncio.create_task(work, name=name))

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await self.client.close()
        await self.engine.dispose()

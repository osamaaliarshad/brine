"""Everything the running app holds: settings, database, salt-api client, collector, bus."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.bus import EventBus
from app.config import Settings
from app.db import create_engine, migrate, session_factory
from app.ingest import Ingest
from app.salt.client import SaltApiClient
from app.salt.collector import Collector

log = logging.getLogger(__name__)


@dataclass
class Runtime:
    settings: Settings
    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]
    bus: EventBus
    ingest: Ingest
    client: SaltApiClient
    collector: Collector
    _task: asyncio.Task[None] | None = field(default=None, repr=False)

    @classmethod
    async def start(cls, settings: Settings, *, run_collector: bool = True) -> Runtime:
        await migrate(settings.database)
        engine = create_engine(settings.database)
        sessions = session_factory(engine)
        bus = EventBus()
        ingest = Ingest(sessions, service_user=settings.salt_api.username)
        client = SaltApiClient(settings.salt_api)
        collector = Collector(client, ingest, settings, bus)
        runtime = cls(settings, engine, sessions, bus, ingest, client, collector)
        if run_collector:
            runtime._task = asyncio.create_task(collector.run(), name="collector")
        return runtime

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        await self.client.close()
        await self.engine.dispose()

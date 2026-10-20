from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import create_engine, session_factory
from app.ingest import Ingest
from app.models import Base

T0 = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


class FakeClock:
    def __init__(self, start: datetime = T0) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: Any) -> datetime:
        self.now += timedelta(**kwargs)
        return self.now


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
async def sessions(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield session_factory(engine)
    await engine.dispose()


@pytest.fixture
def ingest(sessions: async_sessionmaker[AsyncSession], clock: FakeClock) -> Ingest:
    return Ingest(sessions, service_user="brine", clock=clock)

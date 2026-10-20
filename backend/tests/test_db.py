from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, select

from app.db import async_url, create_engine, migrate, session_factory
from app.models import Base, Minion


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("sqlite:///data/brine.db", "sqlite+aiosqlite:///data/brine.db"),
        ("sqlite+aiosqlite:///x.db", "sqlite+aiosqlite:///x.db"),
        ("postgresql://u:p@db/brine", "postgresql+asyncpg://u:***@db/brine"),
    ],
)
def test_async_url(given: str, expected: str) -> None:
    assert async_url(given).render_as_string() == expected


async def test_migrations_create_schema_matching_models(tmp_path: Path) -> None:
    database = f"sqlite:///{tmp_path / 'sub' / 'brine.db'}"
    await migrate(database)
    await migrate(database)  # idempotent

    def diff(conn: Connection) -> list[object]:
        return list(compare_metadata(MigrationContext.configure(conn), Base.metadata))

    engine = create_engine(database)
    async with engine.connect() as conn:
        assert await conn.run_sync(diff) == []
    await engine.dispose()


async def test_datetimes_round_trip_as_utc(tmp_path: Path) -> None:
    database = f"sqlite:///{tmp_path / 'brine.db'}"
    await migrate(database)
    engine = create_engine(database)
    sessions = session_factory(engine)
    pacific = timezone(timedelta(hours=-7))
    seen = datetime(2026, 10, 20, 5, 0, tzinfo=pacific)

    async with sessions() as session:
        session.add(Minion(id="m1", key_state="accepted", first_seen_at=seen, last_seen_at=seen))
        await session.commit()
    async with sessions() as session:
        minion = (await session.execute(select(Minion))).scalar_one()
    await engine.dispose()

    assert minion.last_seen_at == datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
    assert minion.last_seen_at.tzinfo is UTC


async def test_naive_datetimes_are_rejected(tmp_path: Path) -> None:
    database = f"sqlite:///{tmp_path / 'brine.db'}"
    await migrate(database)
    engine = create_engine(database)
    async with session_factory(engine)() as session:
        session.add(Minion(id="m1", key_state="accepted", first_seen_at=datetime(2026, 1, 1)))
        with pytest.raises(Exception, match="naive datetime"):
            await session.commit()
    await engine.dispose()

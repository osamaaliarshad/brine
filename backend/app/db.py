"""Database engine, sessions, and migrations.

SQLite works out of the box (`sqlite:///data/brine.db`); Postgres via `postgresql://...` with the
`postgres` extra installed. Plain URLs are mapped to the async drivers automatically.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import event
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

BACKEND_DIR = Path(__file__).resolve().parents[1]

_ASYNC_DRIVERS = {"sqlite": "sqlite+aiosqlite", "postgresql": "postgresql+asyncpg"}


def async_url(database: str) -> URL:
    """Map `sqlite:///x.db` / `postgresql://...` to their async-driver equivalents."""
    url = make_url(database)
    if url.drivername in _ASYNC_DRIVERS:
        url = url.set(drivername=_ASYNC_DRIVERS[url.drivername])
    return url


def _sqlite_pragmas(dbapi_conn: Any, _record: Any) -> None:
    cursor = dbapi_conn.cursor()
    # WAL lets the API read while the collector writes; busy_timeout rides out short locks.
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def create_engine(database: str) -> AsyncEngine:
    url = async_url(database)
    if url.get_backend_name() == "sqlite" and url.database not in (None, "", ":memory:"):
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(url)
    if url.get_backend_name() == "sqlite":
        event.listen(engine.sync_engine, "connect", _sqlite_pragmas)
    return engine


def session_factory(engine: AsyncEngine) -> async_sessionmaker[Any]:
    return async_sessionmaker(engine, expire_on_commit=False)


def alembic_config(database: str) -> AlembicConfig:
    cfg = AlembicConfig(str(BACKEND_DIR / "alembic.ini"))
    cfg.attributes["configure_logger"] = False
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    # `%` is alembic's interpolation character; escape it so passwords survive.
    cfg.set_main_option(
        "sqlalchemy.url",
        async_url(database).render_as_string(hide_password=False).replace("%", "%%"),
    )
    return cfg


async def migrate(database: str) -> None:
    """Bring the schema up to date. Runs in a thread: alembic drives its own event loop."""
    url = async_url(database)
    if url.get_backend_name() == "sqlite" and url.database not in (None, "", ":memory:"):
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(command.upgrade, alembic_config(database), "head")

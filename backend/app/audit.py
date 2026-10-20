"""The audit log: who did what, on which minions, and when."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import AuditEntry


async def record(
    sessions: async_sessionmaker[AsyncSession],
    *,
    actor: str,
    action: str,
    target: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """Append one entry. Actions are dotted, e.g. `auth.login`, `pillar.view`."""
    async with sessions() as s, s.begin():
        s.add(
            AuditEntry(
                at=datetime.now(UTC), actor=actor, action=action, target=target, detail=detail
            )
        )

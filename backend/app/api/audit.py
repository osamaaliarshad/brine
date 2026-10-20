"""The audit log, for admins."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import SessionDep
from app.auth.users import require_role
from app.models import AuditEntry

router = APIRouter(dependencies=[Depends(require_role("admin"))])


class AuditItem(BaseModel):
    id: int
    at: Any
    actor: str
    action: str
    target: str | None
    detail: dict[str, Any] | None


class AuditPage(BaseModel):
    entries: list[AuditItem]
    next_before: int | None


@router.get("/audit", response_model=AuditPage)
async def audit_log(
    session: SessionDep,
    limit: int = Query(100, ge=1, le=500),
    before: int | None = Query(None, description="id from the previous page's next_before"),
    actor: str | None = None,
    action: str | None = Query(None, description="exact action, or a prefix ending in '.'"),
) -> AuditPage:
    query = select(AuditEntry)
    if before is not None:
        if before < 1:
            raise HTTPException(400, "bad cursor")
        query = query.where(AuditEntry.id < before)
    if actor:
        query = query.where(AuditEntry.actor == actor)
    if action:
        query = query.where(
            AuditEntry.action.startswith(action)
            if action.endswith(".")
            else AuditEntry.action == action
        )
    rows = (await session.scalars(query.order_by(AuditEntry.id.desc()).limit(limit + 1))).all()
    entries = [AuditItem.model_validate(r, from_attributes=True) for r in rows[:limit]]
    return AuditPage(entries=entries, next_before=entries[-1].id if len(rows) > limit else None)

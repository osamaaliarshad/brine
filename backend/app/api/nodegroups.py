"""The master's nodegroups and who's in them (SaltGUI's Nodegroups page)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import RuntimeDep, SessionDep
from app.api.master import master_settings
from app.api.schemas import Nodegroup, Nodegroups
from app.models import Minion
from app.salt.client import SaltApiError

router = APIRouter()


def _expression(value: Any) -> str:
    return ", ".join(map(str, value)) if isinstance(value, list) else str(value)


@router.get("/nodegroups", response_model=Nodegroups)
async def nodegroups(runtime: RuntimeDep, session: SessionDep) -> Nodegroups:
    """Membership comes from the master's cache (`cache.grains` targeted at the nodegroup), so
    offline members count too and nothing runs on minions. Only the `nodegroups` setting is
    read out of the master config."""
    try:
        values = await master_settings(runtime)
        defined = (values or {}).get("nodegroups") or {}
        groups = []
        for name, expression in sorted(defined.items()):
            members = await runtime.client.runner("cache.grains", tgt=name, tgt_type="nodegroup")
            groups.append(
                Nodegroup(
                    name=str(name),
                    expression=_expression(expression),
                    members=sorted(members) if isinstance(members, dict) else [],
                )
            )
    except SaltApiError as exc:
        raise HTTPException(502, f"salt-api: {exc}") from exc
    accepted = (
        await session.scalars(
            select(Minion.id).where(Minion.key_state == "accepted").order_by(Minion.id)
        )
    ).all()
    grouped = {m for g in groups for m in g.members}
    return Nodegroups(groups=groups, ungrouped=[m for m in accepted if m not in grouped])

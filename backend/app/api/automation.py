"""Schedules and beacons across the whole fleet, asked live (SaltGUI's Schedules/Beacons pages)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException

from app.api.deps import RuntimeDep, SessionDep
from app.api.fleet import reachable
from app.api.schemas import FleetLiveView
from app.salt.client import SaltApiError

router = APIRouter()

AUTOMATION_CALLS = {"schedules": "schedule.list", "beacons": "beacons.list"}
TIMEOUT_SECONDS = 10


@router.get("/automation/{kind}", response_model=FleetLiveView)
async def automation(
    kind: Literal["schedules", "beacons"], runtime: RuntimeDep, session: SessionDep
) -> FleetLiveView:
    fun = AUTOMATION_CALLS[kind]
    ask, skipped = await reachable(runtime, session)
    try:
        result = (
            await runtime.client.local(
                ",".join(ask),
                fun,
                kwarg={"return_yaml": False},
                tgt_type="list",
                salt_timeout=TIMEOUT_SECONDS,
            )
            if ask
            else {}
        )
    except SaltApiError as exc:
        raise HTTPException(502, f"salt-api: {exc}") from exc
    return FleetLiveView(
        kind=kind,
        function=fun,
        fetched_at=datetime.now(UTC),
        results=dict(sorted(result.items())),
        missing=[m for m in ask if m not in result],
        skipped=skipped,
    )

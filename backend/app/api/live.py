"""Per-minion views fetched live from the minion through salt-api (not stored by brine).

These mirror SaltGUI's pillar/beacons/schedules/mine pages. Each answer says when it was
fetched; an offline minion simply doesn't answer.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException

from app.api.deps import RuntimeDep, SessionDep
from app.api.fleet import reachable
from app.api.schemas import LiveView
from app.models import Minion
from app.salt.client import SaltApiError

router = APIRouter()

LiveKind = Literal["pillar", "beacons", "schedules", "mine"]

# kind -> (execution function, kwargs). pillar.obfuscate keeps secret values out of the browser:
# it returns the structure with each value replaced by its type.
LIVE_CALLS: dict[str, tuple[str, dict[str, Any]]] = {
    "pillar": ("pillar.obfuscate", {}),
    "beacons": ("beacons.list", {"return_yaml": False}),
    "schedules": ("schedule.list", {"return_yaml": False}),
    "mine": ("mine.valid", {}),
}

LIVE_TIMEOUT_SECONDS = 10


@router.get("/minions/{minion_id}/live/{kind}", response_model=LiveView)
async def live_view(
    minion_id: str, kind: LiveKind, runtime: RuntimeDep, session: SessionDep
) -> LiveView:
    if await session.get(Minion, minion_id) is None:
        raise HTTPException(404, f"no minion {minion_id!r}")
    fun, kwarg = LIVE_CALLS[kind]
    _, offline = await reachable(runtime, session)
    if minion_id in offline:
        return LiveView(
            kind=kind,
            function=fun,
            fetched_at=datetime.now(UTC),
            answered=False,
            offline=True,
            data=None,
        )
    try:
        result = await runtime.client.local(
            minion_id, fun, kwarg=kwarg, tgt_type="list", salt_timeout=LIVE_TIMEOUT_SECONDS
        )
    except SaltApiError as exc:
        raise HTTPException(502, f"salt-api: {exc}") from exc
    fetched_at = datetime.now(UTC)
    if minion_id not in result:
        return LiveView(kind=kind, function=fun, fetched_at=fetched_at, answered=False, data=None)
    return LiveView(
        kind=kind, function=fun, fetched_at=fetched_at, answered=True, data=result[minion_id]
    )

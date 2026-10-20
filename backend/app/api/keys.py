"""Minion keys: the list, and accepting, rejecting or deleting them (admins only).

Every action re-reads the key from the master first and refuses if it isn't where the admin saw
it, or (when accepting) if its fingerprint changed. Salt's `key.*_dict` functions match exact
minion IDs within one key state, unlike `key.accept` and friends, which take a glob.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.api.deps import RuntimeDep, SessionDep
from app.api.fleet import presence_blind, presence_info
from app.api.schemas import (
    Capabilities,
    Capability,
    Key,
    KeyActionRequest,
    KeyActionResult,
)
from app.audit import record
from app.auth.users import CurrentUser, require_role
from app.commands import allowed_patterns
from app.ingest import KEY_LIST_FIELDS
from app.models import Minion
from app.runtime import Runtime
from app.salt.acl import missing
from app.salt.client import SaltApiError, SaltApiForbidden
from app.status import minion_status

router = APIRouter()

KeyAction = Literal["accept", "reject", "delete"]

# action -> (key states it applies to, Salt's exact-match wheel function, resulting state)
ACTIONS: dict[str, tuple[frozenset[str], str, str]] = {
    "accept": (frozenset({"pending", "rejected"}), "key.accept_dict", "accepted"),
    "reject": (frozenset({"pending", "accepted"}), "key.reject_dict", "rejected"),
    "delete": (
        frozenset({"pending", "accepted", "rejected", "denied"}),
        "key.delete_dict",
        "deleted",
    ),
}
KEY_FUNCTIONS = [fun for _, fun, _ in ACTIONS.values()]
KEY_DIRS = {state: name for name, state in KEY_LIST_FIELDS.items()}  # "pending" -> "minions_pre"


def needs_typed_confirmation(action: str, state: str) -> bool:
    """Deleting a key, or cutting off an accepted minion, takes typing the minion's name."""
    return action == "delete" or (action == "reject" and state == "accepted")


def _glob_literal(minion_id: str) -> str:
    """key.finger takes an fnmatch pattern; make this one match only `minion_id`."""
    return "".join(f"[{c}]" if c in "*?[" else c for c in minion_id)


async def _key_on_master(runtime: Runtime, minion_id: str) -> dict[str, Any]:
    """`key.finger` for exactly this minion: {"minions_pre": {id: fingerprint}, ...}."""
    finger = await runtime.client.wheel("key.finger", match=_glob_literal(minion_id))
    found: dict[str, Any] = {}
    for name in KEY_LIST_FIELDS:
        fingerprint = ((finger or {}).get(name) or {}).get(minion_id)
        if fingerprint:
            found[name] = {minion_id: str(fingerprint)}
    return found


def _states(found: dict[str, Any]) -> dict[str, str]:
    return {KEY_LIST_FIELDS[name]: fps[next(iter(fps))] for name, fps in found.items()}


@router.get("/keys", response_model=list[Key])
async def keys(runtime: RuntimeDep, session: SessionDep) -> list[Key]:
    presence = await presence_info(session)
    blind = await presence_blind(session)
    now = datetime.now(UTC)
    stale_after = timedelta(minutes=runtime.settings.fleet.stale_after_minutes)
    rows = await session.scalars(
        select(Minion).where(Minion.key_state != "deleted").order_by(Minion.id)
    )
    return [
        Key(
            id=m.id,
            key_state=m.key_state,
            fingerprint=m.key_fingerprint,
            first_seen_at=m.first_seen_at,
            last_seen_at=m.last_seen_at,
            status=minion_status(
                connected=m.connected,
                last_seen_at=m.last_seen_at,
                presence_at=presence.checked_at,
                now=now,
                stale_after=stale_after,
                observable=m.id not in blind,
            )
            if m.key_state == "accepted"
            else None,
        )
        for m in rows
    ]


@router.get("/capabilities", response_model=Capabilities)
async def capabilities(runtime: RuntimeDep, user: CurrentUser) -> Capabilities:
    """What the signed-in person may do, and what Salt lets brine's service account do, so the
    UI only offers what will work."""
    commands = allowed_patterns(user.role, runtime.settings.commands)
    try:
        perms = await runtime.client.permissions()
    except SaltApiError:
        return Capabilities(manage_keys=Capability(allowed=None, missing=[]), commands=commands)
    lacking = missing(perms, "wheel", KEY_FUNCTIONS)
    return Capabilities(
        manage_keys=Capability(allowed=not lacking, missing=lacking), commands=commands
    )


@router.post(
    "/keys/{minion_id}/{action}",
    response_model=KeyActionResult,
    dependencies=[Depends(require_role("admin"))],
)
async def key_action(
    minion_id: str,
    action: KeyAction,
    body: KeyActionRequest,
    runtime: RuntimeDep,
    user: CurrentUser,
) -> KeyActionResult:
    states, fun, result_state = ACTIONS[action]
    if body.state not in states:
        raise HTTPException(409, f"Can't {action} a key that's {body.state}.")
    if needs_typed_confirmation(action, body.state) and body.confirm != minion_id:
        raise HTTPException(422, f"Type the minion's name ({minion_id}) to confirm.")
    if action == "accept" and not body.fingerprint:
        raise HTTPException(422, "Accepting a key needs the fingerprint you checked.")

    try:
        now = _states(await _key_on_master(runtime, minion_id))
        if body.state not in now:
            where = " and ".join(sorted(now)) or "gone"
            raise HTTPException(
                409, f"{minion_id}'s key is {where} now, not {body.state}. Refresh and try again."
            )
        fingerprint = now[body.state]
        if body.fingerprint and body.fingerprint != fingerprint:
            raise HTTPException(
                409,
                f"{minion_id}'s key changed since you looked; its fingerprint is now "
                f"{fingerprint}. Check it again before accepting.",
            )
        kwargs: dict[str, Any] = {"match": {KEY_DIRS[body.state]: [minion_id]}}
        if action == "accept" and body.state == "rejected":
            kwargs["include_rejected"] = True
        if action == "reject" and body.state == "accepted":
            kwargs["include_accepted"] = True
        await runtime.client.wheel(fun, **kwargs)

        found = await _key_on_master(runtime, minion_id)
        after = _states(found)
        key_lists = await runtime.client.wheel("key.list_all")
    except SaltApiForbidden as exc:
        raise HTTPException(
            403,
            f"{exc}. Add it to external_auth for that account "
            "(see docs/permissions-and-salt-acl.md).",
        ) from exc
    except SaltApiError as exc:
        raise HTTPException(502, f"salt-api: {exc}") from exc

    done = body.state not in after if result_state == "deleted" else result_state in after
    if not done:
        where = " and ".join(sorted(after)) or "gone"
        raise HTTPException(502, f"Salt didn't {action} {minion_id}'s key; it's {where}.")

    runtime.bus.publish_changes(await runtime.ingest.keys(key_lists or {}))
    runtime.bus.publish_changes(await runtime.ingest.fingerprints(found))
    await record(
        runtime.sessions,
        actor=user.email,
        action=f"key.{action}",
        target=minion_id,
        detail={"from": body.state, "fingerprint": fingerprint},
    )
    # A deleted key a minion sends again straight away shows up as pending.
    new_state = result_state if result_state in after else next(iter(sorted(after)), "deleted")
    return KeyActionResult(id=minion_id, key_state=new_state)

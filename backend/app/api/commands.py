"""The command box: preview a command and exactly which minions it reaches, then run it.

Who may run what comes from `commands:` in the config (see app/commands.py); brine's Salt
account's external_auth limits it further. Every run is in the audit log, and minion jobs are
recorded under the person who ran them.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from fnmatch import fnmatchcase

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RuntimeDep, SessionDep
from app.api.fleet import reachable
from app.api.schemas import CommandPreview, CommandRequest, CommandResult
from app.audit import record
from app.auth.users import CurrentUser, User
from app.commands import (
    Command,
    CommandError,
    allowed_patterns,
    command_metadata,
    is_allowed,
    parse_command,
)
from app.models import Minion
from app.runtime import Runtime
from app.salt.client import SaltApiError, SaltApiForbidden

router = APIRouter(prefix="/commands")

# Runner and wheel calls answer when they're done; give slow ones (orchestrations) time.
COMMAND_WAIT_SECONDS = 300


def _command(body: CommandRequest, user: User, runtime: Runtime) -> Command:
    try:
        command = parse_command(body.command)
    except CommandError as exc:
        raise HTTPException(422, str(exc)) from exc
    patterns = allowed_patterns(user.role, runtime.settings.commands)
    if not patterns:
        raise HTTPException(403, f"The {user.role} role can't run commands in brine.")
    if not is_allowed(command, patterns):
        raise HTTPException(
            403,
            f"The {user.role} role can't run {command.qualified}. "
            f"It may run: {', '.join(patterns)}.",
        )
    return command


async def _resolve(
    runtime: Runtime, session: AsyncSession, body: CommandRequest
) -> tuple[list[str], list[str], bool]:
    """(matching accepted minions, list entries that aren't accepted minions, from the cache)."""
    target = body.target.strip()
    if not target:
        raise HTTPException(422, "Choose the minions to run it on.")
    accepted = list(
        (
            await session.scalars(
                select(Minion.id).where(Minion.key_state == "accepted").order_by(Minion.id)
            )
        ).all()
    )
    if body.target_type == "glob":
        return [m for m in accepted if fnmatchcase(m, target)], [], False
    if body.target_type == "list":
        wanted = [t.strip() for t in target.split(",") if t.strip()]
        known = set(accepted)
        return [m for m in wanted if m in known], [m for m in wanted if m not in known], False
    if body.target_type == "pcre":
        try:
            pattern = re.compile(target)
        except re.error as exc:
            raise HTTPException(422, f"That isn't a valid regular expression: {exc}.") from exc
        return [m for m in accepted if pattern.match(m)], [], False
    # Grain, compound and nodegroup targets match against the master's minion data cache.
    try:
        cached = await runtime.client.runner("cache.grains", tgt=target, tgt_type=body.target_type)
    except SaltApiError as exc:
        raise HTTPException(502, f"salt-api: {exc}") from exc
    return sorted(cached) if isinstance(cached, dict) else [], [], True


@router.post("/preview", response_model=CommandPreview)
async def preview(
    body: CommandRequest, runtime: RuntimeDep, session: SessionDep, user: CurrentUser
) -> CommandPreview:
    command = _command(body, user, runtime)
    minions: list[str] = []
    unknown: list[str] = []
    offline: list[str] = []
    from_cache = False
    if command.client == "local":
        minions, unknown, from_cache = await _resolve(runtime, session, body)
        _, skipped = await reachable(runtime, session)
        offline = [m for m in minions if m in set(skipped)]
    return CommandPreview(
        client=command.client,
        fun=command.fun,
        qualified=command.qualified,
        args=command.args,
        minions=minions,
        offline=offline,
        unknown=unknown,
        from_cache=from_cache,
    )


@router.post("/run", response_model=CommandResult)
async def run(
    body: CommandRequest, runtime: RuntimeDep, session: SessionDep, user: CurrentUser
) -> CommandResult:
    command = _command(body, user, runtime)
    if command.client == "local":
        return await _run_on_minions(command, body, runtime, session, user)
    try:
        answer = await runtime.client.run(
            {"client": command.client, "fun": command.fun, "arg": command.args},
            wait_seconds=COMMAND_WAIT_SECONDS,
        )
    except SaltApiError as exc:
        raise _salt_error(exc) from exc

    # Wheel answers {"tag", "data": {"return", "success"}}; runners with their return value.
    value, success = answer, None
    data = answer.get("data") if isinstance(answer, dict) else None
    if command.client == "wheel" and isinstance(data, dict):
        value, success = data.get("return"), data.get("success")
    await record(
        runtime.sessions,
        actor=user.email,
        action="command.run",
        target="master",
        detail={"command": command.qualified, "args": command.args, "success": success},
    )
    return CommandResult(client=command.client, result=value, success=success)


async def _run_on_minions(
    command: Command, body: CommandRequest, runtime: Runtime, session: AsyncSession, user: User
) -> CommandResult:
    target = body.target.strip()
    minions, _, _ = await _resolve(runtime, session, body)
    if not minions:
        raise HTTPException(422, "No minions match that target.")
    if body.expect is None or set(body.expect) != set(minions):
        raise HTTPException(
            409,
            f"That target matches {len(minions)} minion(s) now, not the ones you previewed. "
            "Preview it again.",
        )
    try:
        jid, sent_to = await runtime.client.start_job(
            target,
            command.fun,
            arg=command.args,
            tgt_type=body.target_type,
            metadata=command_metadata(user.email),
        )
    except SaltApiError as exc:
        raise _salt_error(exc) from exc
    if jid is None:
        raise HTTPException(409, "Salt found no minions for that target.")
    sent_to = sent_to or minions
    runtime.bus.publish_changes(
        await runtime.ingest.command_started(
            jid=jid,
            fun=command.fun,
            args=command.args,
            target=target,
            target_type=body.target_type,
            actor=user.email,
            minions=sent_to,
            at=datetime.now(UTC),
        )
    )
    await record(
        runtime.sessions,
        actor=user.email,
        action="command.run",
        target=target,
        detail={
            "command": command.qualified,
            "args": command.args,
            "target_type": body.target_type,
            "minions": len(sent_to),
            "jid": jid,
        },
    )
    return CommandResult(client="local", jid=jid, minions=sent_to)


def _salt_error(exc: SaltApiError) -> HTTPException:
    if isinstance(exc, SaltApiForbidden):
        return HTTPException(
            403,
            f"{exc}. Add it to external_auth for that account "
            "(see docs/permissions-and-salt-acl.md).",
        )
    return HTTPException(502, f"salt-api: {exc}")

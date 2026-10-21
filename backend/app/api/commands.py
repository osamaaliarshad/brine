"""The command box: preview a command and exactly which minions it reaches, then run it.

Who may run what comes from `commands:` in the config (see app/commands.py); brine's Salt
account's external_auth limits it further. Every run is in the audit log, and minion jobs are
recorded under the person who ran them.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime, timedelta
from fnmatch import fnmatchcase
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RuntimeDep, SessionDep
from app.api.errors import salt_http_error
from app.api.fleet import reachable
from app.api.schemas import (
    CatchUpRun,
    CommandPreview,
    CommandRequest,
    CommandResult,
    CommandTemplate,
)
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
from app.config import TemplateConfig
from app.ingest import Changes
from app.masking import HIDDEN, reveals_pillar
from app.models import Minion, PendingRun
from app.runtime import Runtime
from app.salt.client import SaltApiError, SaltApiUnavailable
from app.salt.collector import import_job
from app.states import ORCHESTRATE_FUNCTIONS, parse_state_return, unwrap_orchestration

log = logging.getLogger(__name__)

router = APIRouter(prefix="/commands")

# Runner and wheel calls answer when they're done; give slow ones (orchestrations) time.
COMMAND_WAIT_SECONDS = 300
MAX_REGEX = 200
REGEX_SECONDS = 2.0


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
        if len(target) > MAX_REGEX:
            raise HTTPException(422, f"Keep regular expressions under {MAX_REGEX} characters.")
        try:
            pattern = re.compile(target)
        except re.error as exc:
            raise HTTPException(422, f"That isn't a valid regular expression: {exc}.") from exc
        # Off the event loop, with a time limit: a pathological pattern mustn't freeze brine.
        try:
            matched = await asyncio.wait_for(
                asyncio.to_thread(lambda: [m for m in accepted if pattern.match(m)]),
                REGEX_SECONDS,
            )
        except TimeoutError as exc:
            raise HTTPException(422, "That regular expression takes too long to match.") from exc
        return matched, [], False
    # Grain, compound and nodegroup targets match against the master's minion data cache.
    try:
        cached = await runtime.client.runner("cache.grains", tgt=target, tgt_type=body.target_type)
    except SaltApiError as exc:
        raise HTTPException(502, f"salt-api: {exc}") from exc
    return sorted(cached) if isinstance(cached, dict) else [], [], True


def _may_run(text: str, patterns: list[str]) -> bool:
    try:
        return is_allowed(parse_command(text), patterns)
    except CommandError:
        return False


# SaltGUI's template fields brine understands (it also has `key`, a keyboard shortcut).
TEMPLATE_FIELDS = {*TemplateConfig.model_fields, "targettype"}


@router.get("/templates", response_model=list[CommandTemplate])
async def templates(runtime: RuntimeDep, user: CurrentUser) -> list[CommandTemplate]:
    """Ready-made commands: brine's `templates:` and SaltGUI's `saltgui_templates` from the
    master config (so a team moving from SaltGUI keeps theirs). brine's win on a name clash."""
    found: dict[str, tuple[TemplateConfig, Literal["brine", "master"]]] = {}
    try:
        values = await runtime.client.wheel("config.values")
    except SaltApiError as exc:
        log.info("no master templates: %s", exc)
        values = {}
    master = values.get("saltgui_templates") if isinstance(values, dict) else None
    for name, spec in master.items() if isinstance(master, dict) else []:
        if not isinstance(spec, dict):
            continue
        try:
            known = {k: v for k, v in spec.items() if k in TEMPLATE_FIELDS}
            found[str(name)] = (TemplateConfig.model_validate(known), "master")
        except ValidationError:
            continue  # like SaltGUI, skip what can't be used
    for name, template in runtime.settings.templates.items():
        found[name] = (template, "brine")

    patterns = allowed_patterns(user.role, runtime.settings.commands)
    return [
        CommandTemplate(
            name=name,
            description=spec.description,
            target=spec.target,
            target_type=spec.target_type,
            command=spec.command,
            categories=list(dict.fromkeys([*filter(None, [spec.category]), *spec.categories])),
            source=source,
            # One with no command only fills in the target: usable by anyone who runs things.
            allowed=_may_run(spec.command, patterns) if spec.command.strip() else bool(patterns),
        )
        for name, (spec, source) in sorted(found.items())
    ]


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
        catch_up_days=runtime.settings.commands.catch_up_days,
    )


@router.post("/catch-up/{run_id}/cancel", response_model=CatchUpRun)
async def cancel_catch_up(run_id: int, runtime: RuntimeDep, user: CurrentUser) -> CatchUpRun:
    """Drop a waiting catch-up run: the person who queued it, or an admin."""
    async with runtime.sessions() as s:
        run = await s.get(PendingRun, run_id)
    if run is None:
        raise HTTPException(404, f"no catch-up run {run_id}")
    if user.email != run.actor and user.role != "admin":
        raise HTTPException(403, "Only the person who queued it, or an admin, can cancel it.")
    if run.state != "waiting":
        raise HTTPException(409, f"It's {run.state}, not waiting.")
    changes = await runtime.ingest.catch_up_close(
        run_id, state="cancelled", reason=f"cancelled by {user.email}"
    )
    if not changes:
        raise HTTPException(409, "It stopped waiting just now (it's being sent).")
    runtime.bus.publish_changes(changes)
    await record(
        runtime.sessions,
        actor=user.email,
        action="command.catch_up_cancelled",
        target=run.minion_id,
        detail={"command": " ".join([run.fun, *map(str, run.args)]), "of": run.source_jid},
    )
    async with runtime.sessions() as s:
        return CatchUpRun.model_validate(await s.get(PendingRun, run_id))


@router.post("/run", response_model=CommandResult)
async def run(
    body: CommandRequest, runtime: RuntimeDep, session: SessionDep, user: CurrentUser
) -> CommandResult:
    command = _command(body, user, runtime)
    if command.client == "local":
        return await _run_on_minions(command, body, runtime, session, user)
    lowstate: dict[str, Any] = {"client": command.client, "fun": command.fun, "arg": command.args}
    if command.client == "runner":
        lowstate["full_return"] = True  # the runner's own jid, to record it as a job
    try:
        answer = await runtime.client.run(
            lowstate, wait_seconds=COMMAND_WAIT_SECONDS, repeatable=False
        )
    except SaltApiError as exc:
        raise await _failed(runtime, user, command, "", exc) from exc

    value, success, jid = _master_answer(answer)
    orchestration = command.client == "runner" and command.fun in ORCHESTRATE_FUNCTIONS
    steps = (parse_state_return(unwrap_orchestration(value)) or []) if orchestration else []
    if any(step.result is False for step in steps):
        success = False
    if command.client != "runner":
        jid = None  # wheel calls aren't jobs brine keeps
    if jid:
        changes = await runtime.ingest.master_command(
            jid=jid,
            fun=command.fun,
            args=command.args,
            actor=user.email,
            at=datetime.now(UTC),
            data=value,
            success=success,
        )
        changes.merge(await _import_steps(runtime, [s.jid for s in steps if s.jid], user.email))
        runtime.bus.publish_changes(changes)
    await record(
        runtime.sessions,
        actor=user.email,
        action="command.run",
        target="master",
        detail={"command": command.qualified, "args": command.args, "success": success, "jid": jid},
    )
    hidden = user.role != "admin" and reveals_pillar(command.fun)
    return CommandResult(
        client=command.client, jid=jid, result=HIDDEN if hidden else value, success=success
    )


def _master_answer(answer: Any) -> tuple[Any, bool | None, str | None]:
    """(return value, success, jid). Wheel calls, and runners asked for `full_return`, answer
    {"tag": "salt/run/<jid>/ret", "data": {"return", "success", "jid"}}; a Salt that ignores
    full_return answers with the return value alone."""
    if not isinstance(answer, dict):
        return answer, None, None
    tag, data = answer.get("tag"), answer.get("data")
    if not (isinstance(tag, str) and tag.startswith(("salt/run/", "salt/wheel/"))):
        return answer, None, None
    if not isinstance(data, dict):
        return answer, None, None
    success = data.get("success")
    jid = data.get("jid")
    return (
        data.get("return"),
        success if isinstance(success, bool) else None,
        str(jid or "") or None,
    )


async def _import_steps(runtime: Runtime, jids: list[str], actor: str) -> Changes:
    """An orchestration's steps run as Salt's own "salt" user: fetch each step's job from the
    job cache and record it under the person who ran the orchestration."""
    changes = Changes()
    for jid in jids:
        try:
            changes.merge(
                await import_job(
                    runtime.client, runtime.ingest, jid, user=actor, now=datetime.now(UTC)
                )
            )
        except SaltApiError as exc:
            log.warning("couldn't import orchestration step %s: %s", jid, exc)
    if jids:
        changes.merge(await runtime.ingest.job_owner(jids, actor))
    return changes


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
        # Exactly the minions the preview showed: Salt doesn't get to work the target out
        # again (from a grains cache that may have moved on). The job still shows the
        # target as typed.
        jid, sent_to = await runtime.client.start_job(
            ",".join(minions),
            command.fun,
            arg=command.args,
            tgt_type="list",
            metadata=command_metadata(user.email),
        )
    except SaltApiError as exc:
        raise await _failed(runtime, user, command, target, exc) from exc
    if jid is None:
        raise HTTPException(409, "Salt found no minions for that target.")
    sent_to = sent_to or minions
    now = datetime.now(UTC)
    changes = await runtime.ingest.command_started(
        jid=jid,
        fun=command.fun,
        args=command.args,
        target=target,
        target_type=body.target_type,
        actor=user.email,
        minions=sent_to,
        at=now,
    )
    waiting: list[str] = []
    if body.catch_up:
        # Only minions a fresh presence check says are offline: the rest got it now.
        _, skipped = await reachable(runtime, session)
        waiting = [m for m in minions if m in set(skipped)]
        changes.merge(
            await runtime.ingest.catch_up_queue(
                source_jid=jid,
                fun=command.fun,
                args=command.args,
                actor=user.email,
                minions=waiting,
                at=now,
                expires_at=now + timedelta(days=runtime.settings.commands.catch_up_days),
            )
        )
    runtime.bus.publish_changes(changes)
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
            "catch_up": waiting or None,
        },
    )
    return CommandResult(client="local", jid=jid, minions=sent_to, waiting=waiting)


async def _failed(
    runtime: Runtime, user: User, command: Command, target: str, exc: SaltApiError
) -> HTTPException:
    """Audit a run that failed (or may have: a timeout), and the error to show for it."""
    await record(
        runtime.sessions,
        actor=user.email,
        action="command.failed",
        target=target or "master",
        detail={"command": command.qualified, "args": command.args, "error": str(exc)},
    )
    error = salt_http_error(exc)
    if isinstance(exc, SaltApiUnavailable) and exc.sent:
        error.detail = (
            f"{error.detail}. Salt may still be running it: check Jobs before running it again."
        )
    return error

"""Catch-up runs: a command someone ran from brine, delivered later to minions that were offline.

On the Run page, a person can tick "also run on the offline minions when they're back". brine
keeps those runs in its database (PendingRun) and, every few seconds, sends each minion that's
connected again the oldest command it missed, one at a time. Identical commands collapse into the
latest; runs expire after `commands.catch_up_days`; the person's allowlist is checked again at
delivery.

All of it lives in brine: nothing changes on the master or minions, and only runs someone opted
into are ever repeated. The jobs carry Salt metadata naming the person and the job they catch up
on, so they're recognisable from the salt CLI too.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.api.fleet import presence_info
from app.audit import record
from app.auth.roles import current_role
from app.commands import Command, allowed_patterns, is_allowed
from app.ingest import Changes
from app.models import JobReturn, Minion, PendingRun
from app.runtime import Runtime
from app.salt.client import SaltApiError

log = logging.getLogger(__name__)

SWEEP_SECONDS = 15
# A delivered run that hasn't answered after this long no longer holds up the minion's next one.
ANSWER_WAIT = timedelta(minutes=10)


async def sweep(runtime: Runtime, now: datetime | None = None) -> None:
    """Expire old runs, then send each minion that's back the oldest command it missed."""
    now = now or datetime.now(UTC)
    changes = await runtime.ingest.catch_up_expire(now)
    stale_after = timedelta(minutes=runtime.settings.fleet.stale_after_minutes)
    async with runtime.sessions() as s:
        presence = await presence_info(s)
        # Only trust "connected" from a fresh presence check.
        fresh = presence.checked_at is not None and now - presence.checked_at <= stale_after
        waiting = (
            (
                await s.scalars(
                    select(PendingRun)
                    .join(Minion, Minion.id == PendingRun.minion_id)
                    .where(
                        PendingRun.state == "waiting",
                        Minion.connected.is_(True),
                        Minion.key_state == "accepted",
                    )
                    .order_by(PendingRun.created_at, PendingRun.id)
                )
            ).all()
            if fresh
            else []
        )
        # Minions still running a delivered catch-up: their next one waits for its answer.
        busy: set[str] = set()
        in_flight = await s.scalars(
            select(PendingRun).where(
                PendingRun.state == "sent", PendingRun.sent_at > now - ANSWER_WAIT
            )
        )
        for run in in_flight:
            if await s.get(JobReturn, (run.sent_jid, run.minion_id)) is None:
                busy.add(run.minion_id)
    for run in waiting:
        if run.minion_id in busy:
            continue
        busy.add(run.minion_id)
        changes.merge(await deliver(runtime, run, now))
    if changes:
        runtime.bus.publish_changes(changes)


async def deliver(runtime: Runtime, run: PendingRun, now: datetime) -> Changes:
    command = Command("local", run.fun, list(run.args))
    role = current_role(run.actor, runtime.settings)
    if role is None or not is_allowed(command, allowed_patterns(role, runtime.settings.commands)):
        return await runtime.ingest.catch_up_close(
            run.id, state="refused", reason=f"{run.actor} may no longer run {command.qualified}"
        )
    try:
        jid, sent_to = await runtime.client.start_job(
            run.minion_id,
            run.fun,
            arg=list(run.args),
            tgt_type="list",
            metadata={"brine": {"actor": run.actor, "catch_up_of": run.source_jid}},
        )
    except SaltApiError as exc:
        log.warning("catch-up run %s for %s: %s; trying again later", run.id, run.minion_id, exc)
        return Changes()
    if jid is None:
        return await runtime.ingest.catch_up_close(
            run.id, state="refused", reason="Salt no longer knows that minion"
        )
    changes = await runtime.ingest.command_started(
        jid=jid,
        fun=run.fun,
        args=list(run.args),
        target=run.minion_id,
        target_type="list",
        actor=run.actor,
        minions=sent_to or [run.minion_id],
        at=now,
    )
    changes.merge(await runtime.ingest.catch_up_sent(run.id, jid=jid, at=now))
    await record(
        runtime.sessions,
        actor=run.actor,
        action="command.catch_up",
        target=run.minion_id,
        detail={
            "command": command.qualified,
            "args": list(run.args),
            "jid": jid,
            "of": run.source_jid,
        },
    )
    log.info("caught %s up on job %s (job %s)", run.minion_id, run.source_jid, jid)
    return changes


async def run_forever(runtime: Runtime) -> None:
    while True:
        try:
            await sweep(runtime)
        except Exception:  # a bad sweep mustn't stop the next one
            log.exception("catch-up sweep failed")
        await asyncio.sleep(SWEEP_SECONDS)

"""Things in the fleet that need a human: SaltGUI's Issues detectors plus brine's own.

Computed on request from what brine already knows; nothing here calls minions.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter
from sqlalchemy import and_, case, func, select

from app import inventory
from app.api.deps import RuntimeDep, SessionDep
from app.api.fleet import grain_value, presence_blind, presence_info
from app.api.inventory import refused_sources
from app.api.jobs import NONE_LATE, caught_up, latest_state_runs
from app.api.schemas import Issue
from app.models import Job, JobReturn, Minion
from app.status import Status, minion_status

router = APIRouter()

RECENT = timedelta(hours=24)
NO_RETURN_AFTER = timedelta(minutes=10)
SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}

Severity = Literal["critical", "warning", "info"]


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _issue(
    key: str,
    severity: Severity,
    title: str,
    detail: str = "",
    *,
    since: datetime | None = None,
    minion_id: str | None = None,
    jid: str | None = None,
) -> Issue:
    return Issue(
        key=key,
        severity=severity,
        title=title,
        detail=detail,
        since=since,
        minion_id=minion_id,
        jid=jid,
    )


@router.get("/issues", response_model=list[Issue])
async def issues(runtime: RuntimeDep, session: SessionDep) -> list[Issue]:
    now = datetime.now(UTC)
    found: list[Issue] = []
    stale_minutes = runtime.settings.fleet.stale_after_minutes
    stale_after = timedelta(minutes=stale_minutes)

    # --- brine's own connection --------------------------------------------------------------
    collector = runtime.collector.status
    if not collector.connected:
        found.append(
            _issue(
                "salt-api",
                "critical",
                "brine can't reach salt-api",
                collector.error or "Statuses will turn stale until it's back.",
                since=collector.since,
            )
        )
    presence = await presence_info(session)
    if presence.checked_at is None:
        found.append(
            _issue(
                "presence",
                "warning",
                "No presence information yet",
                "Turn on presence_events on the master, or check that presence polling works.",
            )
        )
    elif now - presence.checked_at > stale_after:
        found.append(
            _issue(
                "presence",
                "warning",
                "Presence information is stale",
                f"The last presence check was over {stale_minutes} minutes ago, "
                "so online/offline can't be trusted.",
                since=presence.checked_at,
            )
        )
    for source, why in (await refused_sources(session, runtime.settings)).items():
        what = "packages" if source == inventory.PACKAGES else f"the {source} check"
        found.append(
            _issue(
                f"inventory:{source}",
                "warning",
                f"brine can't read {what}",
                f"{why}. Settings › Packages and checks has the lines "  # noqa: RUF001 (the UI's separator)
                "to add to brine's Salt account.",
            )
        )

    # --- keys and minions --------------------------------------------------------------------
    blind = await presence_blind(session)
    minions = (await session.scalars(select(Minion).order_by(Minion.id))).all()
    accepted = [m for m in minions if m.key_state == "accepted"]
    for m in minions:
        if m.key_state == "pending":
            found.append(
                _issue(
                    f"key:{m.id}",
                    "warning",
                    f"{m.id} is waiting for key approval",
                    "Check its fingerprint on the Keys page, then accept or reject it there "
                    "(admins) or on the master.",
                    since=m.first_seen_at,
                    minion_id=m.id,
                )
            )
    for m in accepted:
        status = minion_status(
            connected=m.connected,
            last_seen_at=m.last_seen_at,
            presence_at=presence.checked_at,
            now=now,
            stale_after=stale_after,
            observable=m.id not in blind,
        )
        if m.id in blind and not m.connected:
            found.append(
                _issue(
                    f"blind:{m.id}",
                    "warning",
                    f"Presence detection can't see {m.id}",
                    "The master has no cached IP addresses for it, so presence events and "
                    "minions.connected miss it even when it's up. Restarting its salt-minion "
                    "(or a saltutil.refresh_pillar) refreshes the master's cache.",
                    since=m.last_seen_at,
                    minion_id=m.id,
                )
            )
        elif m.last_seen_at is None and not m.connected:
            found.append(
                _issue(
                    f"never:{m.id}",
                    "info",
                    f"brine has never seen {m.id}",
                    "Its key is accepted, but it hasn't connected since brine started watching.",
                    minion_id=m.id,
                )
            )
        elif status is Status.OFFLINE:
            found.append(
                _issue(
                    f"offline:{m.id}",
                    "warning",
                    f"{m.id} is offline",
                    "Not connected to the master in the latest presence check.",
                    since=m.last_seen_at,
                    minion_id=m.id,
                )
            )
        if m.grains_source == "master_cache":
            found.append(
                _issue(
                    f"cached-grains:{m.id}",
                    "info",
                    f"{m.id}'s grains come from the master's cache",
                    "Their age is unknown; they'll refresh next time the minion answers.",
                    minion_id=m.id,
                )
            )

    # --- Salt versions -----------------------------------------------------------------------
    versions = {m.id: grain_value(m.grains, "saltversion") for m in accepted if m.grains}
    counts = Counter(v for v in versions.values() if v)
    if len(counts) > 1:
        common, _ = counts.most_common(1)[0]
        for mid, version in sorted(versions.items()):
            if version and version != common:
                found.append(
                    _issue(
                        f"version:{mid}",
                        "info",
                        f"{mid} runs Salt {version}",
                        f"Most of the fleet runs {common}.",
                        minion_id=mid,
                    )
                )

    # --- state runs and jobs -----------------------------------------------------------------
    runs = await latest_state_runs(session)
    for run in runs.runs:
        if run.failed:
            found.append(
                _issue(
                    f"state:{run.minion_id}",
                    "critical",
                    f"{run.minion_id}: {_plural(run.failed, 'state')} failed",
                    f"In its latest {run.fun}.",
                    since=run.returned_at,
                    minion_id=run.minion_id,
                    jid=run.jid,
                )
            )

    failed = func.sum(case((JobReturn.success.is_(False), 1), else_=0))
    returned = func.count(JobReturn.minion_id)
    is_recent = and_(Job.kind == "local", Job.started_at >= now - RECENT)
    recent = (
        await session.execute(
            select(Job, returned, failed)
            .outerjoin(JobReturn, JobReturn.jid == Job.jid)
            .where(is_recent)
            .group_by(Job.jid)
            .order_by(Job.started_at.desc())
        )
    ).all()
    # Minions that missed a job and have answered a catch-up run of it since aren't missing.
    late = await caught_up(session, select(Job.jid).where(is_recent))
    state_jids = {run.jid for run in runs.runs}
    for job, n_returned, n_failed in recent:
        if n_failed and job.jid not in state_jids:
            found.append(
                _issue(
                    f"job-failed:{job.jid}",
                    "warning",
                    f"{job.fun} failed on {_plural(n_failed, 'minion')}",
                    f"Target {job.target or '?'}, started by {job.user or 'unknown'}.",
                    since=job.started_at,
                    jid=job.jid,
                )
            )
        missing = len(job.minions) - n_returned - late.get(job.jid, NONE_LATE).minions
        if missing > 0 and now - job.started_at > NO_RETURN_AFTER:
            found.append(
                _issue(
                    f"job-missing:{job.jid}",
                    "info",
                    f"{job.fun}: no return from {_plural(missing, 'minion')}",
                    "They may have been offline when it ran.",
                    since=job.started_at,
                    jid=job.jid,
                )
            )

    return sorted(
        found,
        key=lambda i: (SEVERITY_ORDER[i.severity], -(i.since or now).timestamp(), i.key),
    )

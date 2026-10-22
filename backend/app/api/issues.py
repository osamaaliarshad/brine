"""Things in the fleet that need a human: SaltGUI's Issues detectors plus brine's own.

Computed on request from what brine already knows; nothing here calls minions. Each person can
mark issues as read, which hides them from that person until they change; a mark goes with its
issue.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import Response
from sqlalchemy import and_, case, func, select

from app import inventory
from app.api.deps import RuntimeDep, SessionDep
from app.api.fleet import grain_value, presence_blind, presence_info
from app.api.inventory import refused_sources
from app.api.jobs import NO_CATCH_UPS, catch_ups, latest_state_runs
from app.api.schemas import Issue, MarkRead, MarkReadResult, MarkUnread
from app.auth.users import CurrentUser
from app.models import IssueRead, Job, JobReturn, Minion, PresenceChange
from app.states import STATE_FUNCTIONS
from app.status import Status, minion_status

router = APIRouter()

RECENT = timedelta(hours=24)
NO_RETURN_AFTER = timedelta(minutes=10)
SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}
# While one of these is up, brine can't see the fleet properly: other issues can vanish without
# being fixed (an offline minion, once presence is stale).
BLINDING = {"salt-api", "presence"}

Severity = Literal["critical", "warning", "info"]


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _fingerprint(*parts: object) -> str:
    return hashlib.sha256("\0".join(map(str, parts)).encode()).hexdigest()


# Marking an issue as read hides it from that person until it changes, that is until its
# fingerprint does. By default the fingerprint goes by the issue's `since`, when it began
# (presence gone stale again comes back), or without one, by its title and detail (a minion on
# another Salt version, a new reason salt-api refuses a read). A job's issues are one per job,
# and new wording alone doesn't bring one back (failing on one more minion). Some kinds go by
# what best says it's still the same trouble:
# - salt-api: when brine lost it, so a new error while it's still down doesn't count.
# - offline: when presence saw the minion go, not when it was last seen, which a start event or
#   a job's answer moves before presence sees it back.
# - a failed state run: which states failed, and the minion's latest clean state run, so a
#   schedule failing the same ones again stays read, and different ones, or the same ones after
#   a clean run, come back.
# - a pending key: the key's fingerprint too, so a new key under the same name comes back.
# - a minion presence can't see: nothing, so it never comes back, as its `since` (when it was
#   last seen) moves whenever it answers a job.
def _issue(
    key: str,
    severity: Severity,
    title: str,
    detail: str = "",
    *,
    since: datetime | None = None,
    minion_id: str | None = None,
    jid: str | None = None,
    changes_with: tuple[object, ...] | None = None,  # what the fingerprint goes by instead
) -> Issue:
    if changes_with is None:
        changes_with = (since,) if since else (title, detail)
    return Issue(
        key=key,
        severity=severity,
        title=title,
        detail=detail,
        since=since,
        minion_id=minion_id,
        jid=jid,
        fingerprint=_fingerprint(*changes_with),
    )


@router.get("/issues", response_model=list[Issue])
async def issues(runtime: RuntimeDep, session: SessionDep, user: CurrentUser) -> list[Issue]:
    found = await current_issues(runtime, session)
    await forget_gone(runtime, session, found)
    mine = select(IssueRead.key, IssueRead.fingerprint).where(IssueRead.user == user.email)
    read = {key: fingerprint for key, fingerprint in await session.execute(mine)}
    for issue in found:
        issue.read = read.get(issue.key) == issue.fingerprint
    return found


@router.post("/issues/read", response_model=MarkReadResult)
async def mark_read(
    body: MarkRead, runtime: RuntimeDep, session: SessionDep, user: CurrentUser
) -> MarkReadResult:
    """Hide these issues from the signed-in person until they change. Only those still as the
    page showed them are kept; the rest have changed (or gone) already. Not audited: like the
    fleet's columns, it's their own view."""
    now = {i.key: i.fingerprint for i in await current_issues(runtime, session)}
    marked = {i.key: i.fingerprint for i in body.issues if now.get(i.key) == i.fingerprint}
    await runtime.ingest.issues_read(user.email, marked)
    changed = [i.key for i in body.issues if i.key in now and i.key not in marked]
    return MarkReadResult(marked=list(marked), changed=changed)


async def forget_gone(runtime: RuntimeDep, session: SessionDep, found: list[Issue]) -> None:
    """Drop everyone's marks on issues that have gone: fixed, nothing of them is kept, and one that
    comes back is new. Not while brine can't see the fleet, when an issue can vanish unfixed."""
    current = {issue.key for issue in found}
    if current & BLINDING:
        return
    marked = set(await session.scalars(select(IssueRead.key).distinct()))
    if gone := marked - current:
        await runtime.ingest.issues_forget(gone)


@router.post("/issues/unread", status_code=204)
async def mark_unread(body: MarkUnread, runtime: RuntimeDep, user: CurrentUser) -> Response:
    await runtime.ingest.issues_unread(user.email, body.keys)
    return Response(status_code=204)


async def current_issues(runtime: RuntimeDep, session: SessionDep) -> list[Issue]:
    """The fleet's issues, the same for everyone: most serious first, then newest first."""
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
                changes_with=(collector.down_since,),
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
                    changes_with=(m.first_seen_at, m.key_fingerprint),
                )
            )
    statuses = {
        m.id: minion_status(
            connected=m.connected,
            last_seen_at=m.last_seen_at,
            presence_at=presence.checked_at,
            now=now,
            stale_after=stale_after,
            observable=m.id not in blind,
        )
        for m in accepted
    }
    # When presence last saw each offline minion go: unlike when it was last seen, that stays put
    # while it's offline (a start event or a job's answer can come before presence sees it back).
    offline = [mid for mid, status in statuses.items() if status is Status.OFFLINE]
    offline_at = (
        select(PresenceChange.minion_id, func.max(PresenceChange.at))
        .where(PresenceChange.minion_id.in_(offline), PresenceChange.connected.is_(False))
        .group_by(PresenceChange.minion_id)
    )
    went_offline = {mid: at for mid, at in await session.execute(offline_at)} if offline else {}
    for m in accepted:
        status = statuses[m.id]
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
                    changes_with=(),
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
                    changes_with=(went_offline.get(m.id),),
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
    # Each failing minion's latest clean state run: one since means it was fixed, then broke again.
    failing = [run.minion_id for run in runs.runs if run.failed]
    clean_at = (
        select(JobReturn.minion_id, func.max(JobReturn.returned_at))
        .join(Job, Job.jid == JobReturn.jid)
        .where(
            JobReturn.minion_id.in_(failing),
            Job.kind == "local",
            Job.fun.in_(STATE_FUNCTIONS),
            JobReturn.retcode == 0,
        )
        .group_by(JobReturn.minion_id)
    )
    last_clean = {mid: at for mid, at in await session.execute(clean_at)} if failing else {}
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
                    changes_with=(
                        last_clean.get(run.minion_id),
                        *sorted({(s.function, s.id) for s in run.states if s.result is False}),
                    ),
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
    # Minions that missed a job and have answered a catch-up run of it since aren't missing,
    # nor are those whose catch-up run may still bring their answer.
    late = await catch_ups(session, select(Job.jid).where(is_recent))
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
        later = late.get(job.jid, NO_CATCH_UPS)
        missing = len(job.minions) - n_returned - later.caught_up - later.catching_up
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

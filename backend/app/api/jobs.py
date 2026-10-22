from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Literal, NamedTuple

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import Row, Select, and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.deps import SessionDep
from app.api.schemas import (
    CatchUpRun,
    CaughtUp,
    JobDetail,
    JobPage,
    JobResult,
    JobSummary,
    StateDot,
    StateRun,
    StateRuns,
)
from app.auth.users import CurrentUser
from app.masking import HIDDEN, reveals_pillar
from app.models import Job, JobReturn, Minion, PendingRun
from app.states import (
    ORCHESTRATE_FUNCTIONS,
    STATE_FUNCTIONS,
    StateResult,
    parse_state_return,
    unwrap_orchestration,
)

router = APIRouter()

_returned = func.count(JobReturn.minion_id)
_succeeded = func.sum(case((JobReturn.success.is_(True), 1), else_=0))
_failed = func.sum(case((JobReturn.success.is_(False), 1), else_=0))
_finished = func.max(JobReturn.returned_at)


def _with_counts() -> Select[Job, int, Any, Any, Any]:
    return (
        select(Job, _returned, _succeeded, _failed, _finished)
        .outerjoin(JobReturn, JobReturn.jid == Job.jid)
        .group_by(Job.jid)
    )


class Late(NamedTuple):
    """A job's minions that missed it and answered a catch-up run of it later."""

    minions: int = 0
    succeeded: int = 0
    failed: int = 0


NONE_LATE = Late()


def _summary(row: Row[Job, int, Any, Any, Any], late: Late = NONE_LATE) -> JobSummary:
    job, returned, succeeded, failed, finished = row
    return JobSummary(
        jid=job.jid,
        kind=job.kind,
        fun=job.fun,
        target=job.target,
        target_type=job.target_type,
        user=job.user,
        started_at=job.started_at,
        # The job's own returns: a catch-up's answer can come days later.
        finished_at=finished,
        expected=len(job.minions),
        returned=returned,
        succeeded=(succeeded or 0) + late.succeeded,
        failed=(failed or 0) + late.failed,
        caught_up=late.minions,
    )


async def caught_up(session: AsyncSession, jids: Iterable[str] | Select[str]) -> dict[str, Late]:
    """For each of these jobs (a list, or a query of jids) that has any: its minions that
    missed it and have answered a catch-up run of it since. One that answered the job itself
    after all isn't counted twice."""
    answer, own = aliased(JobReturn), aliased(JobReturn)
    rows = await session.execute(
        select(
            PendingRun.source_jid,
            func.count(),
            func.sum(case((answer.success.is_(True), 1), else_=0)),
            func.sum(case((answer.success.is_(False), 1), else_=0)),
        )
        .join(
            answer,
            and_(answer.jid == PendingRun.sent_jid, answer.minion_id == PendingRun.minion_id),
        )
        .where(
            PendingRun.state == "sent",
            PendingRun.source_jid.in_(jids),
            ~select(own.jid)
            .where(own.jid == PendingRun.source_jid, own.minion_id == PendingRun.minion_id)
            .exists(),
        )
        .group_by(PendingRun.source_jid)
    )
    return {jid: Late(count, ok or 0, bad or 0) for jid, count, ok, bad in rows}


@router.get("/jobs", response_model=JobPage)
async def list_jobs(
    session: SessionDep,
    limit: int = Query(50, ge=1, le=200),
    before: str | None = Query(None, description="jid from the previous page's next_before"),
    minion: str | None = Query(None, description="only jobs this minion returned for"),
    fun: str | None = Query(None, description="only this function, e.g. state.apply"),
    q: str | None = Query(None, description="search function, target, user, or jid"),
    kind: Literal["local", "runner"] | None = Query(None),
) -> JobPage:
    query = _with_counts()
    if fun:
        query = query.where(Job.fun == fun)
    if kind:
        query = query.where(Job.kind == kind)
    if q and q.strip():
        like = f"%{q.strip()}%"
        query = query.where(
            or_(
                Job.fun.ilike(like),
                Job.target.ilike(like),
                Job.user.ilike(like),
                Job.jid.like(like),
            )
        )
    if minion:
        query = query.where(Job.jid.in_(select(JobReturn.jid).where(JobReturn.minion_id == minion)))
    if before:
        cursor = await session.get(Job, before)
        if cursor is None:
            raise HTTPException(400, f"unknown cursor {before!r}")
        query = query.where(
            or_(
                Job.started_at < cursor.started_at,
                and_(Job.started_at == cursor.started_at, Job.jid < cursor.jid),
            )
        )
    rows = (
        await session.execute(
            query.order_by(Job.started_at.desc(), Job.jid.desc()).limit(limit + 1)
        )
    ).all()
    page = rows[:limit]
    late = await caught_up(session, [row[0].jid for row in page])
    jobs = [_summary(row, late.get(row[0].jid, NONE_LATE)) for row in page]
    return JobPage(jobs=jobs, next_before=jobs[-1].jid if len(rows) > limit else None)


@router.get("/jobs/state-runs", response_model=StateRuns)
async def state_runs(session: SessionDep) -> StateRuns:
    """Each accepted minion's most recent state run (SaltGUI's Highstate page)."""
    return await latest_state_runs(session)


async def latest_state_runs(session: AsyncSession) -> StateRuns:
    # Each minion's latest state-run return, picked in SQL: only those rows (and their
    # possibly large state output) are loaded.
    state_runs = and_(Job.kind == "local", Job.fun.in_(STATE_FUNCTIONS))
    latest_at = (
        select(JobReturn.minion_id, func.max(JobReturn.returned_at).label("at"))
        .join(Job, Job.jid == JobReturn.jid)
        .where(state_runs)
        .group_by(JobReturn.minion_id)
        .subquery()
    )
    rows = (
        await session.execute(
            select(JobReturn, Job.fun, Job.started_at)
            .join(Job, Job.jid == JobReturn.jid)
            .join(
                latest_at,
                and_(
                    latest_at.c.minion_id == JobReturn.minion_id,
                    latest_at.c.at == JobReturn.returned_at,
                ),
            )
            .where(state_runs)
        )
    ).all()
    accepted = set(
        (await session.scalars(select(Minion.id).where(Minion.key_state == "accepted"))).all()
    )
    latest: dict[str, StateRun] = {}
    for ret, fun, started_at in rows:
        if ret.minion_id in latest or ret.minion_id not in accepted:
            continue
        states = parse_state_return(ret.data) or []
        latest[ret.minion_id] = StateRun(
            minion_id=ret.minion_id,
            jid=ret.jid,
            fun=fun,
            started_at=started_at,
            returned_at=ret.returned_at,
            success=ret.success,
            total=len(states),
            succeeded=sum(1 for s in states if s.result is True),
            failed=sum(1 for s in states if s.result is False),
            changed=sum(1 for s in states if s.changed),
            states=[
                StateDot(id=s.id, function=s.function, result=s.result, changed=s.changed)
                for s in states
            ],
        )
    return StateRuns(
        runs=sorted(latest.values(), key=lambda r: r.minion_id),
        never=sorted(accepted - latest.keys()),
    )


@router.get("/jobs/{jid}", response_model=JobDetail)
async def job_detail(jid: str, session: SessionDep, user: CurrentUser) -> JobDetail:
    row = (await session.execute(_with_counts().where(Job.jid == jid))).first()
    if row is None:
        raise HTTPException(404, f"no job {jid!r}")
    job = row[0]
    returns = (
        await session.scalars(
            select(JobReturn).where(JobReturn.jid == jid).order_by(JobReturn.minion_id)
        )
    ).all()
    is_orchestration = job.kind == "runner" and job.fun in ORCHESTRATE_FUNCTIONS
    is_state = job.fun in STATE_FUNCTIONS or is_orchestration

    def states(data: Any) -> list[StateResult] | None:
        if not is_state:
            return None
        return parse_state_return(unwrap_orchestration(data) if is_orchestration else data)

    # Pillar values (pillar.items and friends) are for admins only.
    hidden = user.role != "admin" and reveals_pillar(job.fun)

    def result(r: JobReturn, late_in: CaughtUp | None = None) -> JobResult:
        return JobResult(
            minion_id=r.minion_id,
            returned_at=r.returned_at,
            success=r.success,
            retcode=r.retcode,
            data=HIDDEN if hidden else r.data,
            states=states(r.data),
            caught_up=late_in,
        )

    runs = (
        await session.scalars(
            select(PendingRun).where(PendingRun.source_jid == jid).order_by(PendingRun.minion_id)
        )
    ).all()
    # The answers to its catch-up runs: a minion that missed the job and has answered one is
    # caught up, its result shown here with the others.
    answers = {
        (r.jid, r.minion_id): r
        for r in await session.scalars(
            select(JobReturn).join(
                PendingRun,
                and_(
                    PendingRun.sent_jid == JobReturn.jid,
                    PendingRun.minion_id == JobReturn.minion_id,
                    PendingRun.source_jid == jid,
                    PendingRun.state == "sent",
                ),
            )
        )
    }
    results = {r.minion_id: result(r) for r in returns}
    catch_up: list[CatchUpRun] = []
    late = NONE_LATE
    for run in runs:
        answer = answers.get((run.sent_jid or "", run.minion_id)) if run.state == "sent" else None
        catch_up.append(
            CatchUpRun.model_validate(run).model_copy(
                update={"answered_at": answer.returned_at if answer else None}
            )
        )
        if answer is not None and run.minion_id not in results:
            at = run.sent_at or answer.returned_at
            results[run.minion_id] = result(answer, CaughtUp(jid=answer.jid, at=at))
            late = Late(
                late.minions + 1,
                late.succeeded + (answer.success is True),
                late.failed + (answer.success is False),
            )
    caught_up_from = await session.scalar(
        select(PendingRun.source_jid).where(PendingRun.sent_jid == jid).limit(1)
    )
    return JobDetail(
        **_summary(row, late).model_dump(),
        catch_up=catch_up,
        catch_up_of=caught_up_from,
        args=job.args,
        minions=job.minions,
        missing=sorted(set(job.minions) - results.keys()),
        results=[results[mid] for mid in sorted(results)],
    )

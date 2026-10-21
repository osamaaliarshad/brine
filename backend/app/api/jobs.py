from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import Select, and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep
from app.api.schemas import (
    CatchUpRun,
    JobDetail,
    JobPage,
    JobResult,
    JobSummary,
    StateDot,
    StateRun,
    StateRuns,
)
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

# How many recent state-run returns to scan for each minion's latest run.
STATE_RUN_SCAN_LIMIT = 5000


def _with_counts() -> Select[Job, int, Any, Any, Any]:
    return (
        select(Job, _returned, _succeeded, _failed, _finished)
        .outerjoin(JobReturn, JobReturn.jid == Job.jid)
        .group_by(Job.jid)
    )


def _summary(
    job: Job, returned: int, succeeded: int | None, failed: int | None, finished: Any
) -> JobSummary:
    return JobSummary(
        jid=job.jid,
        kind=job.kind,
        fun=job.fun,
        target=job.target,
        target_type=job.target_type,
        user=job.user,
        started_at=job.started_at,
        finished_at=finished,
        expected=len(job.minions),
        returned=returned,
        succeeded=succeeded or 0,
        failed=failed or 0,
    )


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
    jobs = [_summary(*row) for row in rows[:limit]]
    return JobPage(jobs=jobs, next_before=jobs[-1].jid if len(rows) > limit else None)


@router.get("/jobs/state-runs", response_model=StateRuns)
async def state_runs(session: SessionDep) -> StateRuns:
    """Each accepted minion's most recent state run (SaltGUI's Highstate page)."""
    return await latest_state_runs(session)


async def latest_state_runs(session: AsyncSession) -> StateRuns:
    rows = (
        await session.execute(
            select(JobReturn, Job.fun, Job.started_at)
            .join(Job, Job.jid == JobReturn.jid)
            .where(Job.kind == "local", Job.fun.in_(STATE_FUNCTIONS))
            .order_by(JobReturn.returned_at.desc())
            .limit(STATE_RUN_SCAN_LIMIT)
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
async def job_detail(jid: str, session: SessionDep) -> JobDetail:
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

    catch_up = await session.scalars(
        select(PendingRun).where(PendingRun.source_jid == jid).order_by(PendingRun.minion_id)
    )
    caught_up_from = await session.scalar(
        select(PendingRun.source_jid).where(PendingRun.sent_jid == jid).limit(1)
    )
    return JobDetail(
        **_summary(*row).model_dump(),
        catch_up=[CatchUpRun.model_validate(r) for r in catch_up],
        catch_up_of=caught_up_from,
        args=job.args,
        minions=job.minions,
        missing=sorted(set(job.minions) - {r.minion_id for r in returns}),
        results=[
            JobResult(
                minion_id=r.minion_id,
                returned_at=r.returned_at,
                success=r.success,
                retcode=r.retcode,
                data=r.data,
                states=states(r.data),
            )
            for r in returns
        ],
    )

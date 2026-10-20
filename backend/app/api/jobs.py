from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import Select, and_, case, func, or_, select

from app.api.deps import SessionDep
from app.api.schemas import JobDetail, JobPage, JobResult, JobSummary
from app.models import Job, JobReturn

router = APIRouter()

_returned = func.count(JobReturn.minion_id)
_succeeded = func.sum(case((JobReturn.success.is_(True), 1), else_=0))
_failed = func.sum(case((JobReturn.success.is_(False), 1), else_=0))


def _with_counts() -> Select[Job, int, Any, Any]:
    return (
        select(Job, _returned, _succeeded, _failed)
        .outerjoin(JobReturn, JobReturn.jid == Job.jid)
        .group_by(Job.jid)
    )


def _summary(job: Job, returned: int, succeeded: int | None, failed: int | None) -> JobSummary:
    return JobSummary(
        jid=job.jid,
        kind=job.kind,
        fun=job.fun,
        target=job.target,
        target_type=job.target_type,
        user=job.user,
        started_at=job.started_at,
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
) -> JobPage:
    query = _with_counts()
    if fun:
        query = query.where(Job.fun == fun)
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


@router.get("/jobs/{jid}", response_model=JobDetail)
async def job_detail(jid: str, session: SessionDep) -> JobDetail:
    row = (await session.execute(_with_counts().where(Job.jid == jid))).first()
    if row is None:
        raise HTTPException(404, f"no job {jid!r}")
    job = row[0]
    results = (
        await session.scalars(
            select(JobReturn).where(JobReturn.jid == jid).order_by(JobReturn.minion_id)
        )
    ).all()
    returned = {r.minion_id for r in results}
    return JobDetail(
        **_summary(*row).model_dump(),
        args=job.args,
        minions=job.minions,
        missing=sorted(set(job.minions) - returned),
        results=[JobResult.model_validate(r, from_attributes=True) for r in results],
    )

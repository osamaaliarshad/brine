"""Retention: old history is pruned per `retention:`; recent history and waiting runs stay."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import retention
from app.config import parse_config
from app.main import create_app
from app.models import (
    AuditEntry,
    GrainsSnapshot,
    IssueRead,
    Job,
    JobReturn,
    PendingRun,
    PresenceChange,
)
from tests.test_api import Api

NOW = datetime.now(UTC)
OLD = NOW - timedelta(days=400)  # past every default: jobs 90, history 90, audit 365
RECENT = NOW - timedelta(days=1)


def make(tmp_path: Path, keep: str = "") -> Any:
    settings = parse_config(
        "salt_api: {url: 'https://salt.test:8000', username: brine, password: x}\n"
        "auth: {provider: none}\n"
        f"{keep}"
        f"database: 'sqlite:///{(tmp_path / 'brine.db').as_posix()}'\n",
        {},
    )
    return TestClient(create_app(settings, frontend_dist=Path("/nonexistent"), run_collector=False))


def seed(api: Api) -> None:
    ingest = api.ingest
    for jid, at in (("old", OLD), ("new", RECENT)):
        api.seed(ingest.job_new, jid=jid, kind="local", fun="test.ping", at=at, user="root")
        api.seed(
            ingest.job_return,
            jid=jid,
            kind="local",
            minion_id="m1",
            fun="test.ping",
            at=at,
            data=True,
            success=True,
            retcode=0,
            user="root",
        )
        api.seed(ingest.presence, ["m1"] if jid == "old" else [], at=at, method="events")
        api.seed(ingest.grains, "m1", {"os": jid}, at=at, source="minion")
    # A finished catch-up run and one still waiting, both old.
    for state in ("sent", "waiting"):
        api.seed(
            ingest.catch_up_queue,
            source_jid=f"src-{state}",
            fun=f"test.{state}",
            args=[],
            actor="a",
            minions=["m1"],
            at=OLD,
            expires_at=OLD,
        )

    async def finish_one_and_audit() -> None:
        async with api.client.app.state.runtime.sessions() as s, s.begin():  # type: ignore[attr-defined]
            run = await s.scalar(select(PendingRun).where(PendingRun.fun == "test.sent"))
            assert run is not None
            run.state = "sent"
            s.add(AuditEntry(at=OLD, actor="a", action="auth.login"))
            s.add(AuditEntry(at=RECENT, actor="a", action="auth.login"))

    api.seed(finish_one_and_audit)


def counts(api: Api) -> dict[str, int]:
    async def count() -> dict[str, int]:
        async with api.client.app.state.runtime.sessions() as s:  # type: ignore[attr-defined]
            models = {
                "jobs": Job,
                "returns": JobReturn,
                "presence": PresenceChange,
                "grains": GrainsSnapshot,
                "audit": AuditEntry,
                "catch_up": PendingRun,
            }
            return {
                name: int(await s.scalar(select(func.count()).select_from(model)) or 0)
                for name, model in models.items()
            }

    return api.seed(count)  # type: ignore[no-any-return]


def test_old_history_goes_recent_stays(tmp_path: Path) -> None:
    with make(tmp_path) as client:
        api = Api(client)
        seed(api)
        before = counts(api)
        deleted = api.seed(retention.prune, client.app.state.runtime, NOW)
        after = counts(api)
    assert deleted["jobs"] == 1 and deleted["audit"] == 1 and deleted["catch_up_runs"] == 1
    assert after["jobs"] == 1 and after["returns"] == 1  # a job's returns go with it
    assert after["audit"] == 1
    assert after["catch_up"] == 1  # the waiting one stays, however old
    assert after["presence"] < before["presence"] and after["grains"] < before["grains"]
    assert api.get("/api/jobs/new")["returned"] == 1


def test_zero_keeps_everything(tmp_path: Path) -> None:
    keep = "retention: {jobs_days: 0, history_days: 0, audit_days: 0}\n"
    with make(tmp_path, keep) as client:
        api = Api(client)
        seed(api)
        before = counts(api)
        deleted = api.seed(retention.prune, client.app.state.runtime, NOW)
        assert counts(api) == before and not any(deleted.values())


def test_marks_on_job_issues_go_after_two_days_whatever_is_kept(tmp_path: Path) -> None:
    keep = "retention: {jobs_days: 0, history_days: 0, audit_days: 0}\n"
    with make(tmp_path, keep) as client:
        api = Api(client)
        runtime = client.app.state.runtime

        async def mark() -> None:
            async with runtime.sessions() as s, s.begin():
                for key, at in [
                    ("job-failed:1", NOW - timedelta(days=3)),
                    ("job-failed:2", RECENT),
                    ("offline:m1", OLD),
                ]:
                    s.add(IssueRead(user="local", key=key, fingerprint="f", read_at=at))

        async def marked() -> list[str]:
            async with runtime.sessions() as s:
                return sorted((await s.scalars(select(IssueRead.key))).all())

        api.seed(mark)
        api.seed(retention.prune, runtime, NOW)
        assert api.seed(marked) == ["job-failed:2", "offline:m1"]

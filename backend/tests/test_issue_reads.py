"""Marking issues as read: each person's own, until the issue changes."""

from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.schemas import MAX_ISSUES_AT_ONCE
from app.config import parse_config
from app.ingest import Ingest
from app.main import create_app
from app.models import IssueRead
from tests.conftest import FakeClock
from tests.test_api import NOW, Api
from tests.test_auth import CSRF, FakeIdP, settings_for, sign_in


@pytest.fixture
def api(tmp_path: Path) -> Iterator[Api]:
    # Viewers may mark issues read too: it's their own view.
    settings = parse_config(
        "salt_api: {url: 'https://salt.test:8000', username: brine, password: x}\n"
        "auth: {provider: none, anonymous_role: viewer}\n"
        f"database: 'sqlite:///{(tmp_path / 'brine.db').as_posix()}'\n",
        {},
    )
    app = create_app(settings, frontend_dist=Path("/nonexistent"), run_collector=False)
    with TestClient(app) as client:
        yield Api(client)


def seed(api: Api) -> None:
    """a and c online, b offline since two minutes ago, c on an older Salt, "new" waiting."""
    api.seed(api.ingest.keys, {"minions": ["a", "b", "c"], "minions_pre": ["new"]})
    api.seed(api.ingest.fingerprints, {"minions_pre": {"new": "aa:aa"}})
    for mid, version in [("a", "3006.28"), ("b", "3006.28"), ("c", "3006.9")]:
        at = NOW - timedelta(minutes=3)
        api.seed(api.ingest.grains, mid, {"saltversion": version}, at=at, source="minion")
    api.seed(api.ingest.presence, ["a", "b", "c"], at=NOW - timedelta(minutes=2), method="events")
    api.seed(api.ingest.presence, ["a", "c"], at=NOW - timedelta(minutes=1), method="events")


def issues(c: TestClient) -> dict[str, Any]:
    resp = c.get("/api/issues")
    assert resp.status_code == 200, resp.text
    return {i["key"]: i for i in resp.json()}


def mark(c: TestClient, *keys: str, fingerprint: str | None = None) -> Any:
    shown = issues(c)
    body = {
        "issues": [{"key": k, "fingerprint": fingerprint or shown[k]["fingerprint"]} for k in keys]
    }
    resp = c.post("/api/issues/read", json=body, headers=CSRF)
    assert resp.status_code == 200, resp.text
    return resp.json()


def unmark(c: TestClient, *keys: str) -> None:
    resp = c.post("/api/issues/unread", json={"keys": list(keys)}, headers=CSRF)
    assert resp.status_code == 204


def read_keys(c: TestClient) -> set[str]:
    return {key for key, issue in issues(c).items() if issue["read"]}


def back_and_offline_again(api: Api, mid: str) -> None:
    api.seed(api.ingest.presence, ["a", "b", "c"], at=NOW - timedelta(seconds=30), method="events")
    api.seed(api.ingest.presence, sorted({"a", "b", "c"} - {mid}), at=NOW, method="events")


def state_run(api: Api, jid: str, failing: list[str], at: datetime) -> None:
    """A state.apply on a where these states fail and one more passes; none failing: clean."""
    data = {
        f"cmd_|-{s}_|-false_|-run": {"result": False, "comment": "", "changes": {}} for s in failing
    }
    data["cmd_|-ok_|-true_|-run"] = {"result": True, "comment": "", "changes": {}}
    run = {"jid": jid, "kind": "local", "fun": "state.apply", "at": at}
    clean = not failing
    api.seed(api.ingest.job_new, **run, user="root", minions=["a"])
    api.seed(
        api.ingest.job_return,
        **run,
        minion_id="a",
        data=data,
        success=clean,
        retcode=0 if clean else 2,
    )


def test_marked_read_until_marked_unread(api: Api) -> None:
    seed(api)
    c = api.client
    assert {"offline:b", "version:c", "key:new"} <= set(issues(c)) and read_keys(c) == set()
    assert mark(c, "offline:b") == {"marked": ["offline:b"], "changed": []}
    assert read_keys(c) == {"offline:b"}  # still listed, so the page can show it on request
    unmark(c, "offline:b")
    assert read_keys(c) == set()


def test_mark_all_as_read(api: Api) -> None:
    seed(api)
    c = api.client
    every = set(issues(c))
    mark(c, *every)
    assert read_keys(c) == every


def test_read_issues_stay_read_while_nothing_changes(api: Api) -> None:
    seed(api)
    c = api.client
    mark(c, "offline:b", "version:c", "key:new")
    # Another presence check: b is still offline since the same time.
    api.seed(api.ingest.presence, ["a", "c"], at=NOW, method="events")
    assert read_keys(c) == {"offline:b", "version:c", "key:new"}


def test_an_offline_minion_stays_read_while_it_stays_offline(api: Api) -> None:
    # A start event, job answers and fresh grains say when it was last seen, but presence still
    # says it's offline: the same time offline, so it stays read.
    seed(api)
    c = api.client
    mark(c, "offline:b")
    before = issues(c)["offline:b"]["since"]
    api.seed(api.ingest.minion_seen, "b", at=NOW - timedelta(seconds=50))
    for i in range(3):
        api.seed(
            api.ingest.job_return,
            jid=f"j{i}",
            kind="local",
            minion_id="b",
            fun="test.ping",
            at=NOW - timedelta(seconds=40 - i * 10),
            data=True,
            success=True,
            retcode=0,
            user="someone",
        )
    at = NOW - timedelta(seconds=5)
    api.seed(api.ingest.grains, "b", {"saltversion": "3006.28"}, at=at, source="minion")
    after = issues(c)["offline:b"]
    assert after["since"] != before and after["read"] is True


def test_an_offline_minion_comes_back_when_it_goes_offline_again(api: Api) -> None:
    seed(api)
    c = api.client
    mark(c, "offline:b")
    api.seed(api.ingest.presence, ["a", "b", "c"], at=NOW - timedelta(seconds=30), method="events")
    assert "offline:b" not in issues(c)
    api.seed(api.ingest.presence, ["a", "c"], at=NOW, method="events")
    assert issues(c)["offline:b"]["read"] is False


def test_salt_api_comes_back_only_after_it_was_connected(api: Api) -> None:
    collector = api.client.app.state.runtime.collector  # type: ignore[attr-defined]

    async def connection(ok: bool, error: str | None = None) -> None:
        collector._set_connected(ok, error=error)

    c = api.client
    mark(c, "salt-api")
    api.seed(connection, False, "connection refused")  # a new error, the same outage
    assert read_keys(c) == {"salt-api"}
    api.seed(connection, True)
    assert "salt-api" not in issues(c)
    api.seed(connection, False, "connection refused")
    assert read_keys(c) == set()


def test_a_failing_state_run_comes_back_only_when_other_states_fail(api: Api) -> None:
    seed(api)
    c = api.client
    state_run(api, "s1", ["calibrate"], NOW - timedelta(minutes=30))
    mark(c, "state:a")
    state_run(api, "s2", ["calibrate"], NOW - timedelta(minutes=20))  # the schedule, again
    assert issues(c)["state:a"]["jid"] == "s2" and read_keys(c) == {"state:a"}
    state_run(api, "s3", ["calibrate", "mount"], NOW - timedelta(minutes=10))
    assert read_keys(c) == set()


def test_a_failed_state_comes_back_when_it_fails_again_after_a_clean_run(api: Api) -> None:
    seed(api)
    c = api.client
    state_run(api, "s1", ["calibrate"], NOW - timedelta(minutes=30))
    mark(c, "state:a")
    state_run(api, "s2", [], NOW - timedelta(minutes=20))  # fixed
    assert "state:a" not in issues(c)
    state_run(api, "s3", ["calibrate"], NOW - timedelta(minutes=10))  # broken again, the same way
    assert issues(c)["state:a"]["read"] is False


def test_an_issue_without_a_since_comes_back_when_it_reads_differently(api: Api) -> None:
    seed(api)
    c = api.client
    mark(c, "version:c")
    at = NOW - timedelta(seconds=30)
    api.seed(api.ingest.grains, "c", {"saltversion": "3006.10"}, at=at, source="minion")
    assert issues(c)["version:c"]["title"] == "c runs Salt 3006.10"
    assert read_keys(c) == set()


def test_a_new_key_under_the_same_name_comes_back(api: Api) -> None:
    seed(api)
    c = api.client
    mark(c, "key:new")
    api.seed(api.ingest.fingerprints, {"minions_pre": {"new": "bb:bb"}})
    assert read_keys(c) == set()


def test_a_minion_presence_cant_see_stays_read_when_it_answers_a_job(api: Api) -> None:
    seed(api)
    c = api.client
    api.seed(api.ingest.presence_blind, {"a": {"ipv4": ["10.0.0.1"]}, "c": {"ipv4": ["10.0.0.3"]}})
    mark(c, "blind:b")
    before = issues(c)["blind:b"]["since"]
    api.seed(
        api.ingest.job_return,
        jid="j1",
        kind="local",
        minion_id="b",
        fun="grains.items",
        at=NOW,
        data={"saltversion": "3006.28"},
        success=True,
        retcode=0,
        user="brine",
    )
    after = issues(c)["blind:b"]
    assert after["since"] != before and after["read"] is True


def test_only_issues_as_they_still_are_are_marked(api: Api) -> None:
    seed(api)
    c = api.client
    shown = issues(c)
    back_and_offline_again(api, "b")
    body = {
        "issues": [
            {"key": "offline:b", "fingerprint": shown["offline:b"]["fingerprint"]},
            {"key": "version:c", "fingerprint": shown["version:c"]["fingerprint"]},
            {"key": "gone:x/y:z", "fingerprint": "f"},  # not an issue (any more)
        ]
    }
    resp = c.post("/api/issues/read", json=body, headers=CSRF)
    assert resp.json() == {"marked": ["version:c"], "changed": ["offline:b"]}
    assert read_keys(c) == {"version:c"}

    async def stored() -> list[str]:
        async with api.client.app.state.runtime.sessions() as s:  # type: ignore[attr-defined]
            return list((await s.scalars(select(IssueRead.key))).all())

    assert api.seed(stored) == ["version:c"]


def test_writes_need_the_csrf_header_and_stay_within_limits(api: Api) -> None:
    c = api.client
    body = {"issues": [{"key": "salt-api", "fingerprint": "f"}]}
    assert c.post("/api/issues/read", json=body).status_code == 403
    assert c.post("/api/issues/unread", json={"keys": ["salt-api"]}).status_code == 403
    too_long = {"issues": [{"key": "x" * 513, "fingerprint": "f"}]}
    assert c.post("/api/issues/read", json=too_long, headers=CSRF).status_code == 422
    too_many = {
        "issues": [{"key": f"k{i}", "fingerprint": "f"} for i in range(MAX_ISSUES_AT_ONCE + 1)]
    }
    assert c.post("/api/issues/read", json=too_many, headers=CSRF).status_code == 422
    keys = {"keys": [f"k{i}" for i in range(MAX_ISSUES_AT_ONCE + 1)]}
    assert c.post("/api/issues/unread", json=keys, headers=CSRF).status_code == 422


def test_each_person_reads_their_own(tmp_path: Path) -> None:
    idp = FakeIdP()
    app = create_app(
        settings_for(tmp_path), frontend_dist=Path("/nonexistent"), run_collector=False
    )
    with TestClient(app) as c:
        c.app.state.runtime.oidc = idp  # type: ignore[attr-defined]
        assert c.get("/api/issues").status_code == 401
        # The collector isn't running in tests, so salt-api shows as unreachable.
        sign_in(c, idp, "alice@example.com")
        mark(c, "salt-api")
        assert read_keys(c) == {"salt-api"}
        sign_in(c, idp, "bob@example.com")
        assert read_keys(c) == set()
        mark(c, "salt-api")
        unmark(c, "salt-api")
        sign_in(c, idp, "alice@example.com")
        assert read_keys(c) == {"salt-api"}


async def test_old_read_marks_are_pruned(
    ingest: Ingest, clock: FakeClock, sessions: async_sessionmaker[AsyncSession]
) -> None:
    async def kept() -> list[str]:
        async with sessions() as s:
            return sorted((await s.scalars(select(IssueRead.key))).all())

    await ingest.issues_read("alice", {"job-failed:1": "f1", "offline:b": "f2"})
    clock.advance(days=3)
    await ingest.issues_read("alice", {"job-missing:2": "f3"})
    await ingest.issues_read("alice", {"job-missing:2": "f3"})  # again: unchanged
    # A job's issues last a day, so their marks go after two, whatever the history keeps.
    deleted = await ingest.prune(
        jobs_before=None,
        history_before=None,
        audit_before=None,
        job_marks_before=clock.now - timedelta(days=2),
    )
    assert deleted["issue_reads"] == 1
    assert await kept() == ["job-missing:2", "offline:b"]
    # The rest go with the history.
    deleted = await ingest.prune(
        jobs_before=None, history_before=clock.now - timedelta(days=1), audit_before=None
    )
    assert deleted["issue_reads"] == 1
    assert await kept() == ["job-missing:2"]

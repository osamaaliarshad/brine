"""Marking issues as read: each person's own, until the issue changes."""

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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


def mark(c: TestClient, *keys: str, fingerprint: str | None = None) -> None:
    shown = issues(c)
    body = {
        "issues": [{"key": k, "fingerprint": fingerprint or shown[k]["fingerprint"]} for k in keys]
    }
    assert c.post("/api/issues/read", json=body, headers=CSRF).status_code == 204


def unmark(c: TestClient, *keys: str) -> None:
    resp = c.post("/api/issues/unread", json={"keys": list(keys)}, headers=CSRF)
    assert resp.status_code == 204


def read_keys(c: TestClient) -> set[str]:
    return {key for key, issue in issues(c).items() if issue["read"]}


def test_marked_read_until_marked_unread(api: Api) -> None:
    seed(api)
    c = api.client
    assert {"offline:b", "version:c", "key:new"} <= set(issues(c)) and read_keys(c) == set()
    mark(c, "offline:b")
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


def test_an_issue_comes_back_when_it_happens_again(api: Api) -> None:
    seed(api)
    c = api.client
    mark(c, "offline:b")
    before = issues(c)["offline:b"]["since"]
    api.seed(api.ingest.presence, ["a", "b", "c"], at=NOW - timedelta(seconds=30), method="events")
    assert "offline:b" not in issues(c)
    api.seed(api.ingest.presence, ["a", "c"], at=NOW, method="events")  # offline again
    again = issues(c)["offline:b"]
    assert again["since"] != before and again["read"] is False


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


def test_what_changed_since_the_page_showed_it_stays_unread(api: Api) -> None:
    seed(api)
    c = api.client
    shown = issues(c)["offline:b"]["fingerprint"]
    api.seed(api.ingest.presence, ["a", "b", "c"], at=NOW - timedelta(seconds=30), method="events")
    api.seed(api.ingest.presence, ["a", "c"], at=NOW, method="events")
    mark(c, "offline:b", fingerprint=shown)
    assert read_keys(c) == set()


def test_keys_are_any_text_and_writes_need_the_csrf_header(api: Api) -> None:
    c = api.client
    body = {"issues": [{"key": "inventory:x/y:z", "fingerprint": "f"}]}
    assert c.post("/api/issues/read", json=body).status_code == 403
    assert c.post("/api/issues/unread", json={"keys": ["x"]}).status_code == 403
    assert c.post("/api/issues/read", json=body, headers=CSRF).status_code == 204
    too_long = {"issues": [{"key": "x" * 513, "fingerprint": "f"}]}
    assert c.post("/api/issues/read", json=too_long, headers=CSRF).status_code == 422
    unmark(c, "inventory:x/y:z")


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


async def test_old_read_marks_are_pruned_with_the_history(
    ingest: Ingest, clock: FakeClock, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await ingest.issues_read("alice", {"job-failed:1": "f1"})
    clock.advance(days=100)
    await ingest.issues_read("alice", {"job-failed:2": "f2"})
    await ingest.issues_read("alice", {"job-failed:2": "f2"})  # again: unchanged
    deleted = await ingest.prune(
        jobs_before=None, history_before=clock.now - timedelta(days=90), audit_before=None
    )
    assert deleted["issue_reads"] == 1
    async with sessions() as s:
        assert (await s.scalars(select(IssueRead.key))).all() == ["job-failed:2"]

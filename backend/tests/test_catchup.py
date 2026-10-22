"""Catch-up runs: commands that wait for offline minions and run when they're back."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from app import catchup
from app.config import CommandsConfig
from app.models import AuditEntry, PendingRun
from app.salt.client import SaltApiUnavailable
from tests.test_api import Api
from tests.test_commands import CSRF, JID, FakeSalt, audit_rows, make_api

ROVERS = ["rover-01", "rover-02", "rover-03"]


@pytest.fixture
def setup(tmp_path: Path) -> Iterator[tuple[Api, FakeSalt]]:
    # Operators may run test.*; rover-03 is offline (fresh presence), the rest online.
    yield from make_api(tmp_path, "operator")


def runtime(api: Api) -> Any:
    return api.client.app.state.runtime  # type: ignore[attr-defined]


def run(api: Api, command: str = "test.ping", **extra: Any) -> Any:
    body = {"command": command, "target": "rover-0*", "expect": ROVERS, **extra}
    resp = api.client.post("/api/commands/run", json=body, headers=CSRF)
    assert resp.status_code == 200, resp.text
    return resp.json()


def sweep(api: Api, now: datetime | None = None) -> None:
    api.seed(catchup.sweep, runtime(api), now)


def comes_back(api: Api, minion: str = "rover-03") -> None:
    online = ["rover-01", "rover-02", "dock-01", minion]
    api.seed(api.ingest.presence, online, at=datetime.now(UTC), method="events")


def sent(salt: FakeSalt) -> list[dict[str, Any]]:
    """Catch-up deliveries (they name the job they catch up on)."""
    return [kw for kw in salt.started() if "catch_up_of" in kw["metadata"]["brine"]]


def test_offline_minions_wait_when_asked(setup: tuple[Api, FakeSalt]) -> None:
    api, _ = setup
    assert run(api, catch_up=True)["waiting"] == ["rover-03"]
    (waiting,) = api.get(f"/api/jobs/{JID}")["catch_up"]
    assert (waiting["minion_id"], waiting["state"], waiting["actor"]) == (
        "rover-03",
        "waiting",
        "local",
    )
    created = datetime.fromisoformat(waiting["created_at"])
    assert datetime.fromisoformat(waiting["expires_at"]) - created == timedelta(days=7)
    assert [r["fun"] for r in api.get("/api/minions/rover-03")["waiting_runs"]] == ["test.ping"]
    assert audit_rows(api)[0].detail["catch_up"] == ["rover-03"]  # type: ignore[index]


def test_nothing_waits_unless_asked(setup: tuple[Api, FakeSalt]) -> None:
    api, _ = setup
    assert run(api)["waiting"] == []
    assert api.get(f"/api/jobs/{JID}")["catch_up"] == []


def test_a_minion_back_online_gets_what_it_missed(setup: tuple[Api, FakeSalt]) -> None:
    api, salt = setup
    run(api, command="test.echo hello", catch_up=True)
    sweep(api)
    assert sent(salt) == []  # still offline

    comes_back(api)
    sweep(api)
    (delivery,) = sent(salt)
    assert delivery == {
        "tgt": "rover-03",
        "arg": ["hello"],
        "tgt_type": "list",
        "metadata": {"brine": {"actor": "local", "catch_up_of": JID}},
    }
    (done,) = api.get(f"/api/jobs/{JID}")["catch_up"]
    assert done["state"] == "sent" and done["sent_jid"] is not None
    caught_up = api.get(f"/api/jobs/{done['sent_jid']}")
    assert caught_up["catch_up_of"] == JID and caught_up["user"] == "local"
    assert caught_up["target"] == "rover-03" and caught_up["fun"] == "test.echo"
    assert api.get("/api/minions/rover-03")["waiting_runs"] == []
    assert [e.action for e in audit_rows(api)] == ["command.run", "command.catch_up"]

    sweep(api)
    assert len(sent(salt)) == 1  # never twice


def test_one_at_a_time_and_in_order(setup: tuple[Api, FakeSalt]) -> None:
    api, salt = setup
    run(api, command="test.ping", catch_up=True)
    run(api, command="test.version", catch_up=True)
    comes_back(api)
    sweep(api)
    sweep(api)
    assert [kw["tgt"] for kw in sent(salt)] == ["rover-03"]  # the second waits for an answer
    first = api.get(f"/api/jobs/{JID}")["catch_up"][0]["sent_jid"]

    api.seed(
        api.ingest.job_return,
        jid=first,
        kind="local",
        minion_id="rover-03",
        fun="test.ping",
        at=datetime.now(UTC),
        data=True,
        success=True,
        retcode=0,
        user="local",
    )
    sweep(api)
    assert len(sent(salt)) == 2


def test_only_the_latest_identical_command_runs(setup: tuple[Api, FakeSalt]) -> None:
    api, salt = setup
    run(api, command="test.ping", catch_up=True)
    second = run(api, command="test.ping", catch_up=True)["jid"]
    (replaced,) = api.get(f"/api/jobs/{JID}")["catch_up"]
    assert replaced["state"] == "replaced" and second in replaced["reason"]
    comes_back(api)
    sweep(api)
    sweep(api)
    assert [kw["metadata"]["brine"]["catch_up_of"] for kw in sent(salt)] == [second]


def test_runs_expire(setup: tuple[Api, FakeSalt]) -> None:
    api, salt = setup
    run(api, catch_up=True)
    comes_back(api)
    sweep(api, datetime.now(UTC) + timedelta(days=8))
    (expired,) = api.get(f"/api/jobs/{JID}")["catch_up"]
    assert expired["state"] == "expired" and sent(salt) == []


def test_nothing_is_sent_on_stale_presence(setup: tuple[Api, FakeSalt]) -> None:
    api, salt = setup
    run(api, catch_up=True)
    comes_back(api)
    sweep(api, datetime.now(UTC) + timedelta(hours=1))  # no presence check for an hour
    assert sent(salt) == []


def test_the_allowlist_is_checked_again_at_delivery(setup: tuple[Api, FakeSalt]) -> None:
    api, salt = setup
    run(api, catch_up=True)
    rt = runtime(api)
    rt.settings = rt.settings.model_copy(
        update={"commands": CommandsConfig(operator=["state.apply"])}
    )
    comes_back(api)
    sweep(api)
    (refused,) = api.get(f"/api/jobs/{JID}")["catch_up"]
    assert refused["state"] == "refused" and "may no longer run test.ping" in refused["reason"]
    assert sent(salt) == []


def test_cancelling(setup: tuple[Api, FakeSalt]) -> None:
    api, salt = setup
    run(api, catch_up=True)
    (waiting,) = api.get(f"/api/jobs/{JID}")["catch_up"]
    url = f"/api/commands/catch-up/{waiting['id']}/cancel"
    resp = api.client.post(url, headers=CSRF)
    assert resp.status_code == 200 and resp.json()["state"] == "cancelled"
    assert api.client.post(url, headers=CSRF).status_code == 409
    comes_back(api)
    sweep(api)
    assert sent(salt) == []

    async def cancelled() -> list[str]:
        async with runtime(api).sessions() as s:
            rows = await s.scalars(select(AuditEntry.action).order_by(AuditEntry.id))
            return list(rows)

    assert api.seed(cancelled)[-1] == "command.catch_up_cancelled"


def test_a_run_cancelled_while_the_sweep_runs_is_never_sent(setup: tuple[Api, FakeSalt]) -> None:
    api, salt = setup
    run(api, catch_up=True)
    comes_back(api)

    async def stale_copy() -> Any:
        async with runtime(api).sessions() as s:
            return await s.scalar(select(PendingRun))

    snapshot = api.seed(stale_copy)  # what the sweep saw: waiting
    (waiting,) = api.get(f"/api/jobs/{JID}")["catch_up"]
    api.client.post(f"/api/commands/catch-up/{waiting['id']}/cancel", headers=CSRF)
    api.seed(catchup.deliver, runtime(api), snapshot, datetime.now(UTC))
    assert sent(salt) == []
    assert api.get(f"/api/jobs/{JID}")["catch_up"][0]["state"] == "cancelled"


def test_retries_only_what_certainly_did_not_go_out(setup: tuple[Api, FakeSalt]) -> None:
    api, salt = setup
    run(api, catch_up=True)
    comes_back(api)
    salt.start_error = SaltApiUnavailable("can't reach salt-api")  # never got there
    sweep(api)
    assert api.get(f"/api/jobs/{JID}")["catch_up"][0]["state"] == "waiting"

    salt.start_error = SaltApiUnavailable("salt-api didn't answer", sent=True)  # it may have
    sweep(api)
    (failed,) = api.get(f"/api/jobs/{JID}")["catch_up"]
    assert failed["state"] == "failed" and "check Jobs" in failed["reason"]
    salt.start_error = None
    sweep(api)
    assert len(sent(salt)) == 2  # the two attempts above; a failed one is never retried


# --- the original job, once its minions catch up ----------------------------------------------


def returns(api: Api, jid: str, minion: str, *, success: bool = True) -> None:
    api.seed(
        api.ingest.job_return,
        jid=jid,
        kind="local",
        minion_id=minion,
        fun="test.echo",
        at=datetime.now(UTC),
        data="hello" if success else "boom",
        success=success,
        retcode=0 if success else 1,
        user="local",
    )


def summary(api: Api, jid: str) -> Any:
    (found,) = [j for j in api.get("/api/jobs")["jobs"] if j["jid"] == jid]
    return found


def counts(job: Any) -> tuple[int, int, int, int, int]:
    return (job["expected"], job["returned"], job["caught_up"], job["succeeded"], job["failed"])


def test_a_minion_that_caught_up_is_no_longer_missing(setup: tuple[Api, FakeSalt]) -> None:
    api, _ = setup
    run(api, command="test.echo hello", catch_up=True)
    returns(api, JID, "rover-01")
    returns(api, JID, "rover-02")
    comes_back(api)
    sweep(api)
    (run_,) = api.get(f"/api/jobs/{JID}")["catch_up"]
    late_jid = run_["sent_jid"]

    # Sent, no answer yet: still missing, waiting on the catch-up.
    job = api.get(f"/api/jobs/{JID}")
    assert job["missing"] == ["rover-03"] and job["catch_up"][0]["answered_at"] is None
    assert [r["minion_id"] for r in job["results"]] == ["rover-01", "rover-02"]
    assert counts(job) == counts(summary(api, JID)) == (3, 2, 0, 2, 0)

    returns(api, late_jid, "rover-03", success=False)
    job = api.get(f"/api/jobs/{JID}")
    assert job["missing"] == []
    assert [(r["minion_id"], r["caught_up"]) for r in job["results"]] == [
        ("rover-01", None),
        ("rover-02", None),
        ("rover-03", {"jid": late_jid, "at": run_["sent_at"]}),
    ]
    assert job["results"][2]["data"] == "boom"
    assert job["catch_up"][0]["answered_at"] == job["results"][2]["returned_at"]
    # Two returned on time and one caught up; its failure counts.
    assert counts(job) == counts(summary(api, JID)) == (3, 2, 1, 2, 1)
    assert job["finished_at"] < job["results"][2]["returned_at"]  # how long the job took

    # The catch-up run's own job is as it was.
    late = api.get(f"/api/jobs/{late_jid}")
    assert late["catch_up_of"] == JID and late["missing"] == []
    assert [r["caught_up"] for r in late["results"]] == [None]
    assert counts(late) == (1, 1, 0, 0, 1)


def test_a_minion_that_answered_both_counts_once(setup: tuple[Api, FakeSalt]) -> None:
    api, _ = setup
    run(api, command="test.echo hello", catch_up=True)
    comes_back(api)
    sweep(api)
    late_jid = api.get(f"/api/jobs/{JID}")["catch_up"][0]["sent_jid"]
    returns(api, late_jid, "rover-03")
    returns(api, JID, "rover-03")  # it had the job after all
    job = api.get(f"/api/jobs/{JID}")
    assert [(r["minion_id"], r["caught_up"]) for r in job["results"]] == [("rover-03", None)]
    assert counts(job) == counts(summary(api, JID)) == (3, 1, 0, 1, 0)


@pytest.mark.parametrize("cancel", [False, True])
def test_a_minion_still_to_catch_up_is_missing(setup: tuple[Api, FakeSalt], cancel: bool) -> None:
    api, _ = setup
    run(api, command="test.echo hello", catch_up=True)
    returns(api, JID, "rover-01")
    returns(api, JID, "rover-02")
    if cancel:
        run_id = api.get(f"/api/jobs/{JID}")["catch_up"][0]["id"]
        api.client.post(f"/api/commands/catch-up/{run_id}/cancel", headers=CSRF)
    job = api.get(f"/api/jobs/{JID}")
    assert job["missing"] == ["rover-03"]
    assert [r["state"] for r in job["catch_up"]] == ["cancelled" if cancel else "waiting"]
    assert counts(job) == counts(summary(api, JID)) == (3, 2, 0, 2, 0)


def test_issues_dont_count_minions_that_caught_up(
    setup: tuple[Api, FakeSalt], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import issues

    monkeypatch.setattr(issues, "NO_RETURN_AFTER", timedelta(0))
    api, _ = setup
    run(api, command="test.echo hello", catch_up=True)
    returns(api, JID, "rover-01")
    returns(api, JID, "rover-02")
    comes_back(api)
    sweep(api)
    late_jid = api.get(f"/api/jobs/{JID}")["catch_up"][0]["sent_jid"]

    def missing() -> dict[str, str]:
        return {
            i["key"]: i["title"]
            for i in api.get("/api/issues")
            if i["key"].startswith("job-missing:")
        }

    assert missing() == {
        f"job-missing:{JID}": "test.echo: no return from 1 minion",
        f"job-missing:{late_jid}": "test.echo: no return from 1 minion",
    }
    returns(api, late_jid, "rover-03")
    assert missing() == {}

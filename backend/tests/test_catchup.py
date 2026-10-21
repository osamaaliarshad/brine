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

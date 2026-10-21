"""Pillar values stay with admins: job results, the event stream, and Run page answers."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.events import event_stream
from app.auth.users import User
from app.config import parse_config
from app.main import create_app
from app.masking import HIDDEN, mask_event, reveals_pillar
from app.salt.events import SaltEvent
from tests.test_api import Api

SECRET = {"db": {"password": "hunter2"}}


def make_api(tmp_path: Path, role: str) -> Iterator[Api]:
    settings = parse_config(
        "salt_api: {url: 'https://salt.test:8000', username: brine, password: x}\n"
        f"auth: {{provider: none, anonymous_role: {role}}}\n"
        f"database: 'sqlite:///{(tmp_path / 'brine.db').as_posix()}'\n",
        {},
    )
    app = create_app(settings, frontend_dist=Path("/nonexistent"), run_collector=False)
    with TestClient(app) as client:
        api = Api(client)
        now = datetime.now(UTC)
        api.seed(
            api.ingest.job_new,
            jid="j1",
            kind="local",
            fun="pillar.items",
            at=now,
            user="root",
            minions=["m1"],
        )
        api.seed(
            api.ingest.job_return,
            jid="j1",
            kind="local",
            minion_id="m1",
            fun="pillar.items",
            at=now,
            data=SECRET,
            success=True,
            retcode=0,
            user="root",
        )
        yield api


@pytest.mark.parametrize(
    ("fun", "secret"),
    [
        ("pillar.items", True),
        ("pillar.get", True),
        ("runner.pillar.show_pillar", True),
        ("pillar.obfuscate", False),  # values already replaced by their types
        ("grains.items", False),
        (None, False),
    ],
)
def test_which_functions_reveal_pillar(fun: Any, secret: bool) -> None:
    assert reveals_pillar(fun) is secret


def test_job_results_hide_pillar_from_non_admins(tmp_path: Path) -> None:
    for api in make_api(tmp_path, "operator"):
        (result,) = api.get("/api/jobs/j1")["results"]
        assert result["data"] == HIDDEN


def test_admins_see_pillar(tmp_path: Path) -> None:
    for api in make_api(tmp_path, "admin"):
        (result,) = api.get("/api/jobs/j1")["results"]
        assert result["data"] == SECRET


def test_events_hide_pillar_returns() -> None:
    ret: dict[str, Any] = {
        "tag": "salt/job/j1/ret/m1",
        "data": {"fun": "pillar.items", "return": SECRET},
    }
    run = {"tag": "salt/run/r1/ret", "data": {"fun": "runner.pillar.show_pillar", "return": SECRET}}
    other = {"tag": "salt/job/j2/ret/m1", "data": {"fun": "test.ping", "return": True}}
    assert mask_event(ret)["data"] == {"fun": "pillar.items", "return": HIDDEN}
    assert mask_event(run)["data"]["return"] == HIDDEN
    assert mask_event(other) is other
    assert ret["data"]["return"] == SECRET  # the log's own copy is untouched


class Gone:
    """A request whose browser has already left: the stream sends its backlog and stops."""

    async def is_disconnected(self) -> bool:
        return True


@pytest.mark.parametrize(("role", "hidden"), [("viewer", True), ("admin", False)])
def test_the_event_stream_masks_per_person(tmp_path: Path, role: str, hidden: bool) -> None:
    for api in make_api(tmp_path, "admin"):
        runtime = api.client.app.state.runtime  # type: ignore[attr-defined]
        runtime.collector.event_log.append(
            SaltEvent("salt/job/j1/ret/m1", {"fun": "pillar.items", "return": SECRET})
        )
        user = User.model_validate(
            {"email": "x", "name": "x", "picture": None, "role": role, "provider": "none"}
        )

        async def first(rt: Any, who: User) -> str:
            response = await event_stream(Gone(), rt, who)  # type: ignore[arg-type]
            chunks = [chunk async for chunk in response.body_iterator]
            return "".join(str(c) for c in chunks)

        body = api.seed(first, runtime, user)
        assert ("hunter2" not in body) is hidden

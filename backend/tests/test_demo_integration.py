"""End-to-end test against the demo Salt fleet (docker-compose.demo.yml).

Skipped unless BRINE_DEMO_SALT_API is set, e.g.:

    docker compose -f docker-compose.demo.yml up -d --build --wait
    BRINE_DEMO_SALT_API=http://127.0.0.1:8001 uv run pytest tests/test_demo_integration.py -v

It stops/starts a minion and restarts the salt-master container, so don't point it at anything
but the demo stack.
"""

import os
import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, parse_config
from app.main import create_app

SALT_API = os.environ.get("BRINE_DEMO_SALT_API")
REPO = Path(__file__).resolve().parents[2]
ACCEPTED = {"rover-01", "rover-02", "rover-03", "dock-01"}

pytestmark = pytest.mark.skipif(not SALT_API, reason="set BRINE_DEMO_SALT_API to run")


def compose(*args: str) -> None:
    docker = shutil.which("docker")
    assert docker, "docker not on PATH"
    subprocess.run(
        [docker, "compose", "-f", str(REPO / "docker-compose.demo.yml"), *args],
        check=True,
        capture_output=True,
    )


def wait_until(what: str, check: Callable[[], bool], timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(1)
    pytest.fail(f"timed out after {timeout:.0f}s waiting for {what}")


def get(c: TestClient, path: str, **params: Any) -> Any:
    resp = c.get(path, params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def statuses(c: TestClient) -> dict[str, str]:
    return {m["id"]: m["status"] for m in get(c, "/api/fleet")["minions"]}


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return parse_config(
        f"salt_api: {{url: '{SALT_API}', username: brine, password: brine-demo, eauth: pam}}\n"
        f"database: 'sqlite:///{(tmp_path / 'brine.db').as_posix()}'\n"
        "fleet: {columns: [{grain: site}, {grain: app_version}]}\n"
        "presence: {method: auto, poll_seconds: 10}\n",
        {},
    )


def test_demo_fleet_end_to_end(settings: Settings) -> None:
    app = create_app(settings, frontend_dist=Path("/nonexistent"))
    with TestClient(app) as c:
        # Connects, syncs, and sees the whole fleet online with grains.
        wait_until(
            "all accepted minions online",
            lambda: {m for m, s in statuses(c).items() if s == "online"} == ACCEPTED,
            90,
        )
        # The master's cached grains show first; fresh ones follow from the minions.
        wait_until(
            "fresh grains from every minion",
            lambda: all(m["grains_source"] == "minion" for m in get(c, "/api/fleet")["minions"]),
            60,
        )
        fleet = get(c, "/api/fleet")
        assert fleet["summary"]["pending_keys"] == 1
        assert {m["id"] for m in fleet["minions"]} == ACCEPTED
        rover = next(m for m in fleet["minions"] if m["id"] == "rover-01")
        assert rover["columns"] == {"site": "site-a", "app_version": "2.4.1"}
        assert rover["salt_version"] and rover["ip"] and rover["grains_source"] == "minion"
        assert get(c, "/api/status")["salt_api"]["connected"] is True

        # A job started on the master's own CLI is recorded with its return.
        compose("exec", "-T", "salt-master", "salt", "rover-01", "test.ping")
        wait_until(
            "the CLI job to be recorded",
            lambda: any(
                j["fun"] == "test.ping" and j["user"] == "root" and j["returned"] == 1
                for j in get(c, "/api/jobs")["jobs"]
            ),
            30,
        )

        # A minion going away and coming back.
        compose("stop", "rover-03")
        wait_until("rover-03 offline", lambda: statuses(c)["rover-03"] == "offline", 60)
        compose("start", "rover-03")
        wait_until("rover-03 online", lambda: statuses(c)["rover-03"] == "online", 90)
        history = get(c, "/api/minions/rover-03")["presence_history"]
        assert [p["connected"] for p in history[:2]] == [True, False]

        # The master restarting: brine notices, reconnects, and keeps observing presence.
        before = get(c, "/api/status")["presence"]["checked_at"]
        compose("restart", "salt-master")
        wait_until(
            "presence observed again after the master restart",
            lambda: (
                get(c, "/api/status")["salt_api"]["connected"]
                and get(c, "/api/status")["presence"]["checked_at"] != before
                and set(statuses(c).values()) == {"online"}
            ),
            180,
        )

    # brine restarting: everything it recorded is still there before it even reconnects.
    with TestClient(create_app(settings, frontend_dist=Path("/nonexistent"))) as c:
        assert {m["id"] for m in get(c, "/api/fleet")["minions"]} == ACCEPTED
        assert any(j["fun"] == "test.ping" for j in get(c, "/api/jobs")["jobs"])
        assert get(c, "/api/minions/rover-03")["presence_history"]

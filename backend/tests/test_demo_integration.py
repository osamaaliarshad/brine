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
        "auth: {provider: none, anonymous_role: admin}\n"
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
        keys = {k["id"]: k for k in get(c, "/api/keys")}
        assert keys["rover-04"]["key_state"] == "pending"
        assert all(k["fingerprint"] for k in keys.values())

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


def test_demo_key_lifecycle(settings: Settings) -> None:
    """rover-04 waits for approval: reject it, accept it after all, delete it, and see it ask
    again once restarted. Leaves rover-04 pending, as the demo expects."""
    csrf = {"X-Requested-With": "brine"}

    def key(c: TestClient) -> dict[str, Any] | None:
        return next((k for k in get(c, "/api/keys") if k["id"] == "rover-04"), None)

    def act(c: TestClient, action: str, **body: Any) -> Any:
        resp = c.post(f"/api/keys/rover-04/{action}", json=body, headers=csrf)
        assert resp.status_code == 200, resp.text
        return resp.json()["key_state"]

    app = create_app(settings, frontend_dist=Path("/nonexistent"))
    try:
        with TestClient(app) as c:
            assert get(c, "/api/capabilities")["manage_keys"]["allowed"] is True
            wait_until("rover-04's key", lambda: bool((key(c) or {}).get("fingerprint")), 60)
            fingerprint = key(c)["fingerprint"]  # type: ignore[index]

            assert act(c, "reject", state="pending") == "rejected"
            assert act(c, "accept", state="rejected", fingerprint=fingerprint) == "accepted"
            assert (key(c) or {})["key_state"] == "accepted"
            assert act(c, "delete", state="accepted", confirm="rover-04") in ("deleted", "pending")

            # A running minion whose key is deleted stays quiet until it restarts.
            compose("restart", "rover-04")
            wait_until(
                "rover-04 to ask again", lambda: (key(c) or {}).get("key_state") == "pending", 60
            )
            actions = [
                (e["action"], e["target"]) for e in get(c, "/api/audit", action="key.")["entries"]
            ]
            assert actions == [
                ("key.delete", "rover-04"),
                ("key.accept", "rover-04"),
                ("key.reject", "rover-04"),
            ]
    finally:
        # Whatever happened, put rover-04 back to pending for the rest of the demo.
        compose("exec", "-T", "salt-master", "salt-key", "-y", "-d", "rover-04")
        compose("restart", "rover-04")


def test_demo_command_box(settings: Settings) -> None:
    """Preview and run a command on the real master; its results are recorded under the
    person who ran it (here the anonymous admin, "local"), not brine's service account."""
    csrf = {"X-Requested-With": "brine"}
    with TestClient(create_app(settings, frontend_dist=Path("/nonexistent"))) as c:
        wait_until(
            "the rovers online",
            lambda: (
                {m: s for m, s in statuses(c).items() if m.startswith("rover")}
                == {"rover-01": "online", "rover-02": "online", "rover-03": "online"}
            ),
            90,
        )
        body = {"command": "test.echo hello", "target": "rover-0*"}
        preview = c.post("/api/commands/preview", json=body, headers=csrf).json()
        assert preview["minions"] == ["rover-01", "rover-02", "rover-03"]
        run = c.post("/api/commands/run", json={**body, "expect": preview["minions"]}, headers=csrf)
        assert run.status_code == 200, run.text
        jid = run.json()["jid"]
        wait_until(
            "every rover to answer",
            lambda: get(c, f"/api/jobs/{jid}")["returned"] == 3,
            30,
        )
        job = get(c, f"/api/jobs/{jid}")
        assert job["user"] == "local" and job["fun"] == "test.echo"
        assert {r["minion_id"]: r["data"] for r in job["results"]} == {
            "rover-01": "hello",
            "rover-02": "hello",
            "rover-03": "hello",
        }

        versions = c.post(
            "/api/commands/run", json={"command": "runners.manage.versions"}, headers=csrf
        )
        assert versions.status_code == 200, versions.text
        assert "Master" in versions.json()["result"]


def test_demo_orchestrations_and_templates(settings: Settings) -> None:
    """The demo's orchestrations and SaltGUI-style templates, read from the real master; running
    an orchestration records it and every step's job under the person who ran it."""
    csrf = {"X-Requested-With": "brine"}
    with TestClient(create_app(settings, frontend_dist=Path("/nonexistent"))) as c:
        orchestrations = get(c, "/api/orchestrations")["orchestrations"]
        assert {o["sls"]: [s["id"] for s in o["steps"]] for o in orchestrations} == {
            "orch.health": ["everyone-answers", "salt-versions"],
            "orch.rollout": ["rovers-answer", "rovers-motd", "dock-calibration"],
        }
        templates = {t["name"]: t for t in get(c, "/api/commands/templates")}
        assert templates["ping-rovers"]["target"] == "rover-*"
        assert templates["refresh-grains"]["categories"] == ["Maintenance", "Health"]

        run = c.post(
            "/api/commands/run",
            json={"command": "runners.state.orchestrate orch.health"},
            headers=csrf,
        )
        assert run.status_code == 200, run.text
        assert run.json()["success"] is True
        job = get(c, f"/api/jobs/{run.json()['jid']}")
        assert (job["kind"], job["fun"], job["user"]) == ("runner", "state.orchestrate", "local")
        steps = job["results"][0]["states"]
        assert [s["id"] for s in steps] == ["everyone-answers", "salt-versions"]
        for step in steps:
            step_job = get(c, f"/api/jobs/{step['jid']}")
            assert step_job["user"] == "local" and step_job["returned"] >= 1


def test_demo_catch_up_runs(settings: Settings) -> None:
    """rover-03 is off when a command goes out with catch-up on; when it's back, brine sends it
    the command and records the answer under the person who ran it."""
    csrf = {"X-Requested-With": "brine"}
    with TestClient(create_app(settings, frontend_dist=Path("/nonexistent"))) as c:
        wait_until("rover-03 online", lambda: statuses(c).get("rover-03") == "online", 90)
        compose("stop", "rover-03")
        try:
            wait_until("rover-03 offline", lambda: statuses(c)["rover-03"] == "offline", 60)
            body = {"command": "test.echo caught-up", "target": "rover-0*"}
            preview = c.post("/api/commands/preview", json=body, headers=csrf).json()
            assert preview["offline"] == ["rover-03"]
            run = c.post(
                "/api/commands/run",
                json={**body, "expect": preview["minions"], "catch_up": True},
                headers=csrf,
            )
            assert run.status_code == 200, run.text
            assert run.json()["waiting"] == ["rover-03"]
            jid = run.json()["jid"]
        finally:
            compose("start", "rover-03")

        def delivered() -> str | None:
            (entry,) = get(c, f"/api/jobs/{jid}")["catch_up"]
            return entry["sent_jid"] if entry["state"] == "sent" else None

        wait_until("the catch-up run to be sent", lambda: delivered() is not None, 120)
        caught_up = delivered()
        wait_until(
            "rover-03 to answer it",
            lambda: get(c, f"/api/jobs/{caught_up}")["returned"] == 1,
            60,
        )
        job = get(c, f"/api/jobs/{caught_up}")
        assert job["catch_up_of"] == jid and job["user"] == "local"
        assert job["results"][0]["data"] == "caught-up"

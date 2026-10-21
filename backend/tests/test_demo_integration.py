"""End-to-end test against the demo Salt fleet (docker-compose.demo.yml).

Skipped unless BRINE_DEMO_SALT_API is set, e.g.:

    docker compose -f docker-compose.demo.yml up -d --build --wait
    BRINE_DEMO_SALT_API=http://127.0.0.1:8001 uv run pytest tests/test_demo_integration.py -v

It stops/starts a minion, restarts the salt-master container, and changes rover-03's rover-agent
package (putting it back after), so don't point it at anything but the demo stack.
"""

import json
import os
import shutil
import subprocess
import time
import warnings
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, load_config, parse_config
from app.inventory import CLOCK_MARGIN
from app.main import create_app

SALT_API = os.environ.get("BRINE_DEMO_SALT_API")
REPO = Path(__file__).resolve().parents[2]
ACCEPTED = {"rover-01", "rover-02", "rover-03", "dock-01"}
# Minions recreated start as docker-compose.demo.yml says (their keys are kept in volumes).
RESET_DEMO = (
    "to reset the demo's minions: docker compose -f docker-compose.demo.yml up -d "
    "--force-recreate rover-01 rover-02 rover-03 dock-01"
)

pytestmark = pytest.mark.skipif(not SALT_API, reason="set BRINE_DEMO_SALT_API to run")


def compose(*args: str, timeout: float | None = None) -> None:
    docker = shutil.which("docker")
    assert docker, "docker not on PATH"
    subprocess.run(
        [docker, "compose", "-f", str(REPO / "docker-compose.demo.yml"), *args],
        check=True,
        capture_output=True,
        timeout=timeout,
    )


def wait_until(
    what: str,
    check: Callable[[], bool],
    timeout: float,
    explain: Callable[[], object] | None = None,
) -> None:
    """Wait for `check`; on a timeout, fail saying what for (and `explain()`, if given)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(1)
    found = f"; found {explain()}" if explain else ""
    pytest.fail(f"timed out after {timeout:.0f}s waiting for {what}{found}")


def get(c: TestClient, path: str, **params: Any) -> Any:
    resp = c.get(path, params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def statuses(c: TestClient) -> dict[str, str]:
    return {m["id"]: m["status"] for m in get(c, "/api/fleet")["minions"]}


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    # The demo's checks (the rover-cli one), which brine's demo Salt account allows.
    checks = load_config(REPO / "demo" / "brine.yaml", {}).inventory.checks
    return parse_config(
        f"salt_api: {{url: '{SALT_API}', username: brine, password: brine-demo, eauth: pam}}\n"
        "auth: {provider: none, anonymous_role: admin}\n"
        f"database: 'sqlite:///{(tmp_path / 'brine.db').as_posix()}'\n"
        "fleet: {columns: [{grain: site}, {grain: app_version}]}\n"
        "presence: {method: auto, poll_seconds: 10}\n"
        f"inventory: {json.dumps({'checks': checks})}\n",
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


def put_back_rover_agent() -> str | None:
    """rover-03's rover-agent to 2.3.0, as the demo starts, through the master's CLI (no change
    if it's there already). Returns why it couldn't, or None."""
    pillar = json.dumps({"agent_version": "2.3.0"})
    try:
        compose(
            *("exec", "-T", "salt-master", "salt", "rover-03", "state.apply", "agent"),
            f"pillar={pillar}",
            timeout=120,
        )
    except subprocess.CalledProcessError as exc:
        output = (exc.stderr or b"") + (exc.stdout or b"")
        return output.decode(errors="replace").strip()[-500:] or str(exc)
    except subprocess.TimeoutExpired as exc:
        return str(exc)
    return None


def test_demo_packages_and_checks(settings: Settings) -> None:
    """brine reads every minion's packages and the rover-cli check. rover-03's rover-agent,
    upgraded from the command box, is found by brine's next read and credited to that run and
    the person who ran it; put back, brine finds that by itself. Leaves rover-03 on 2.3.0, as
    the demo expects."""
    csrf = {"X-Requested-With": "brine"}
    agent, cli = "@packages:rover-agent", "@rover-cli"

    def values(c: TestClient, key: str) -> dict[str, list[str]]:
        found = get(c, "/api/inventory/values", key=key)["values"]
        return {v["text"]: v["minions"] for v in found}

    def answered(c: TestClient) -> bool:
        """Every accepted minion has answered for both the package and the check."""
        found = [get(c, "/api/inventory/values", key=key) for key in (agent, cli)]
        return all(d["total"] == len(ACCEPTED) and not d["unknown"] for d in found)

    def install(c: TestClient, version: str) -> str:
        """Put rover-agent `version` on rover-03 from the command box; returns the run's jid."""
        pillar = json.dumps({"agent_version": version})
        body = {
            "command": f"state.apply agent pillar='{pillar}'",
            "target": "rover-03",
            "target_type": "list",
            "expect": ["rover-03"],
        }
        run = c.post("/api/commands/run", json=body, headers=csrf)
        assert run.status_code == 200, run.text
        jid = str(run.json()["jid"])
        wait_until("rover-03 to run it", lambda: get(c, f"/api/jobs/{jid}")["returned"] == 1, 60)
        assert get(c, f"/api/jobs/{jid}")["results"][0]["success"] is True
        return jid

    # As the demo starts, even if an earlier run stopped halfway.
    if (why := put_back_rover_agent()) is not None:
        pytest.fail(f"couldn't put rover-03 on rover-agent 2.3.0: {why}")
    upgraded = False
    try:
        with TestClient(create_app(settings, frontend_dist=Path("/nonexistent"))) as c:
            wait_until("every minion's packages and rover-cli check", lambda: answered(c), 120)
            # A package some have (one at an older version), and software no package manager
            # knows about; dock-01 has neither.
            untouched = f"the demo's minions have changed since they started; {RESET_DEMO}"
            assert values(c, agent) == {
                "2.4.1": ["rover-01", "rover-02"],
                "2.3.0": ["rover-03"],
            }, untouched
            assert get(c, "/api/inventory/values", key=agent)["missing"] == ["dock-01"], untouched
            assert values(c, cli) == {
                "rover-cli 1.2.0": ["rover-01", "rover-02"],
                "rover-cli 1.1.0": ["rover-03"],
            }, untouched
            assert get(c, "/api/inventory/values", key=cli)["missing"] == ["dock-01"], untouched

            # The fleet against rover-01. Exact counts assume an untouched demo: the minions
            # share one image, so only rover-agent and rover-cli differ.
            compared = get(c, "/api/inventory/compare", reference="rover-01")
            assert compared["reference_sources"] == ["packages", "rover-cli"]
            counts = {
                m["minion_id"]: (m["different"], m["only_reference"], m["only_minion"])
                for m in compared["minions"]
            }
            assert counts == {
                "rover-02": (0, 0, 0),
                "rover-03": (2, 0, 0),
                "dock-01": (0, 2, 0),
            }, untouched

            upgraded = True
            jid = install(c, "2.4.1")

            def changes() -> Any:
                return get(c, "/api/inventory/changes", key=agent)

            def credited() -> dict[str, Any] | None:
                return next(
                    (ch for ch in changes() if ch["minion_id"] == "rover-03" and ch["jid"] == jid),
                    None,
                )

            # brine reads rover-03 again by itself a minute after the run. So does any other
            # brine reading the demo fleet (one on :8080, a dev backend), and an answer to
            # another's read is stored but never credited. So Read now, as soon as a read counts
            # as after the run (CLOCK_MARGIN after its return, by the master's clock), to be
            # first. Docker keeps the containers' clock and this one together.
            returned = get(c, f"/api/jobs/{jid}")["results"][0]["returned_at"]
            ready = datetime.fromisoformat(returned) + CLOCK_MARGIN + timedelta(seconds=5)
            wait_until("a read to count as after the run", lambda: datetime.now(UTC) >= ready, 60)
            asked = c.post("/api/inventory/ask", json={"minion": "rover-03"}, headers=csrf)
            assert asked.status_code == 200, asked.text
            assert asked.json()["asked"] == ["rover-03"]
            wait_until(
                "the upgrade, credited to the run", lambda: credited() is not None, 60, changes
            )
            change = credited()
            assert change is not None
            assert (change["old"], change["new"], change["user"]) == ("2.3.0", "2.4.1", "local")
            assert values(c, agent) == {"2.4.1": ["rover-01", "rover-02", "rover-03"]}

            # Back to the demo as documented, found without asking: brine's read a minute
            # after the run (or another brine's).
            install(c, "2.3.0")
            wait_until(
                "rover-03 read again at 2.3.0",
                lambda: values(c, agent).get("2.3.0") == ["rover-03"],
                180,
                changes,
            )
            upgraded = False
    finally:
        # Whatever happened, put rover-03 back for the rest of the demo, without hiding why
        # the test failed.
        if upgraded and (why := put_back_rover_agent()) is not None:
            warnings.warn(
                f"couldn't put rover-03 back on rover-agent 2.3.0: {why}; {RESET_DEMO}",
                stacklevel=1,
            )

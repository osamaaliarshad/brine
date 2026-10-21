"""The command box: parsing, who may run what, previews, and runs."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.commands import (
    Command,
    CommandError,
    actor_of,
    allowed_patterns,
    is_allowed,
    parse_command,
)
from app.config import CommandsConfig, parse_config
from app.main import create_app
from app.models import AuditEntry
from app.salt.client import SaltApiForbidden
from tests.test_api import Api

CSRF = {"X-Requested-With": "brine"}
JID = "20261020120000000001"


class FakeSalt:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.forbidden: set[str] = set()
        self.grain_matches = ["rover-01"]
        self.answers: dict[str, Any] = {}
        self.job_cache: dict[str, Any] = {}
        self.master_config: dict[str, Any] = {}

    async def permissions(self) -> list[Any]:
        return []

    async def runner(self, fun: str, **kwargs: Any) -> Any:
        self.calls.append(("runner", fun, kwargs))
        if fun == "jobs.list_job":
            return self.job_cache[kwargs["jid"]]
        assert fun == "cache.grains"
        return {m: {"os": "Debian"} for m in self.grain_matches}

    async def wheel(self, fun: str, **kwargs: Any) -> Any:
        self.calls.append(("wheel", fun, kwargs))
        if fun in self.forbidden:
            raise SaltApiForbidden(f"brine's Salt account isn't allowed to run wheel {fun}", 403)
        assert fun == "config.values"
        return self.master_config

    async def start_job(self, tgt: str, fun: str, **kwargs: Any) -> tuple[str | None, list[str]]:
        self.calls.append(("start_job", fun, {"tgt": tgt, **kwargs}))
        if fun in self.forbidden:
            raise SaltApiForbidden(f"brine's Salt account isn't allowed to run {fun}", 403)
        return JID, ["rover-01", "rover-02", "rover-03"]

    async def run(self, lowstate: dict[str, Any], **kwargs: Any) -> Any:
        self.calls.append(("run", lowstate["fun"], {**lowstate, **kwargs}))
        return self.answers[lowstate["fun"]]

    def started(self) -> list[dict[str, Any]]:
        return [kw for kind, _, kw in self.calls if kind == "start_job"]

    async def close(self) -> None:
        pass


def make_api(tmp_path: Path, role: str) -> Iterator[tuple[Api, FakeSalt]]:
    settings = parse_config(
        "salt_api: {url: 'https://salt.test:8000', username: brine, password: x}\n"
        f"auth: {{provider: none, anonymous_role: {role}}}\n"
        "commands: {operator: ['test.*', 'runners.manage.*']}\n"
        f"database: 'sqlite:///{(tmp_path / 'brine.db').as_posix()}'\n",
        {},
    )
    app = create_app(settings, frontend_dist=Path("/nonexistent"), run_collector=False)
    salt = FakeSalt()
    with TestClient(app) as client:
        client.app.state.runtime.client = salt  # type: ignore[attr-defined]
        api = Api(client)
        api.seed(
            api.ingest.keys,
            {
                "minions": ["rover-01", "rover-02", "rover-03", "dock-01"],
                "minions_pre": ["rover-04"],
            },
        )
        now = datetime.now(UTC)
        api.seed(api.ingest.presence, ["rover-01", "rover-02", "dock-01"], at=now, method="events")
        yield api, salt


@pytest.fixture
def operator(tmp_path: Path) -> Iterator[tuple[Api, FakeSalt]]:
    yield from make_api(tmp_path, "operator")


@pytest.fixture
def admin(tmp_path: Path) -> Iterator[tuple[Api, FakeSalt]]:
    yield from make_api(tmp_path, "admin")


def post(api: Api, path: str, **body: Any) -> Any:
    return api.client.post(f"/api/commands/{path}", json=body, headers=CSRF)


def audit_rows(api: Api) -> list[AuditEntry]:
    async def rows() -> list[AuditEntry]:
        async with api.client.app.state.runtime.sessions() as s:  # type: ignore[attr-defined]
            return list((await s.scalars(select(AuditEntry).order_by(AuditEntry.id))).all())

    return api.seed(rows)  # type: ignore[no-any-return]


# --- parsing and policy ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("test.ping", Command("local", "test.ping", [])),
        (
            "state.apply webserver test=True",
            Command("local", "state.apply", ["webserver", "test=True"]),
        ),
        ('cmd.run "ls -l /tmp"', Command("local", "cmd.run", ["ls -l /tmp"])),
        (
            'pkg.install pkgs=\'["vim", "git"]\'',
            Command("local", "pkg.install", ['pkgs=["vim", "git"]']),
        ),
        ("runners.manage.status", Command("runner", "manage.status", [])),
        (
            "runner.jobs.list_jobs search_function=test.*",
            Command("runner", "jobs.list_jobs", ["search_function=test.*"]),
        ),
        ("wheel.key.list_all", Command("wheel", "key.list_all", [])),
    ],
)
def test_commands_split_like_a_shell(text: str, expected: Command) -> None:
    assert parse_command(text) == expected


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "Type a Salt function"),
        ("   ", "Type a Salt function"),
        ("cmd.run 'unclosed", "No closing quotation"),
        ("ping", "isn't a Salt function name"),
        ("rm -rf /", "isn't a Salt function name"),
        ("test.ping;reboot", "isn't a Salt function name"),
    ],
)
def test_commands_that_cant_be_read(text: str, message: str) -> None:
    with pytest.raises(CommandError, match=message):
        parse_command(text)


def test_allowlists_by_role() -> None:
    config = CommandsConfig(operator=["test.*", "state.apply", "runners.manage.*"])
    operator = allowed_patterns("operator", config)
    assert is_allowed(parse_command("test.version"), operator)
    assert is_allowed(parse_command("state.apply"), operator)
    assert not is_allowed(parse_command("state.sls"), operator)
    assert not is_allowed(parse_command("cmd.run ls"), operator)
    assert is_allowed(parse_command("runners.manage.status"), operator)
    # A minion function's name doesn't unlock the runner with the same name, or vice versa.
    assert not is_allowed(parse_command("runners.test.ping"), operator)
    assert not is_allowed(parse_command("wheel.key.delete"), operator)
    assert is_allowed(parse_command("wheel.key.delete"), allowed_patterns("admin", config))
    assert allowed_patterns("viewer", config) == []


def test_actor_comes_only_from_brine_metadata() -> None:
    assert actor_of({"brine": {"actor": "a@example.com"}}) == "a@example.com"
    assert actor_of({"brine": {}}) is None
    assert actor_of({"other": "x"}) is None
    assert actor_of(None) is None
    assert actor_of("brine") is None


# --- previews and runs ----------------------------------------------------------------------


def test_preview_shows_exactly_what_runs_where(operator: tuple[Api, FakeSalt]) -> None:
    api, salt = operator
    resp = post(api, "preview", command="test.ping", target="rover-0*")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "client": "local",
        "fun": "test.ping",
        "qualified": "test.ping",
        "args": [],
        "minions": ["rover-01", "rover-02", "rover-03"],
        "offline": ["rover-03"],
        "unknown": [],
        "from_cache": False,
    }
    assert salt.calls == []  # a preview never runs anything


def test_running_records_the_job_under_the_person(operator: tuple[Api, FakeSalt]) -> None:
    api, salt = operator
    expect = ["rover-01", "rover-02", "rover-03"]
    resp = post(api, "run", command="test.ping", target="rover-0*", expect=expect)
    assert resp.json() == {
        "client": "local",
        "jid": JID,
        "minions": expect,
        "result": None,
        "success": None,
    }
    assert salt.started() == [
        {
            "tgt": "rover-0*",
            "arg": [],
            "tgt_type": "glob",
            "metadata": {"brine": {"actor": "local"}},
        }
    ]
    job = api.get(f"/api/jobs/{JID}")
    assert job["user"] == "local" and job["target"] == "rover-0*"
    assert sorted(job["minions"]) == expect
    (entry,) = audit_rows(api)
    assert (entry.actor, entry.action, entry.target) == ("local", "command.run", "rover-0*")
    assert entry.detail == {
        "command": "test.ping",
        "args": [],
        "target_type": "glob",
        "minions": 3,
        "jid": JID,
    }


def test_runs_only_on_what_was_previewed(operator: tuple[Api, FakeSalt]) -> None:
    api, salt = operator
    assert post(api, "run", command="test.ping", target="rover-0*").status_code == 409
    resp = post(api, "run", command="test.ping", target="rover-0*", expect=["rover-01"])
    assert resp.status_code == 409 and "Preview it again" in resp.json()["detail"]
    resp = post(api, "run", command="test.ping", target="nothing-*", expect=[])
    assert resp.status_code == 422
    assert salt.started() == []


def test_operators_run_only_their_allowlist(operator: tuple[Api, FakeSalt]) -> None:
    api, salt = operator
    resp = post(api, "preview", command="cmd.run reboot", target="*")
    assert resp.status_code == 403
    assert resp.json()["detail"] == (
        "The operator role can't run cmd.run. It may run: test.*, runners.manage.*."
    )
    resp = post(api, "run", command="cmd.run reboot", target="*", expect=["rover-01"])
    assert resp.status_code == 403 and salt.started() == []


def test_viewers_run_nothing(tmp_path: Path) -> None:
    for api, salt in make_api(tmp_path, "viewer"):
        resp = post(api, "preview", command="test.ping", target="*")
        assert resp.status_code == 403
        assert resp.json()["detail"] == "The viewer role can't run commands in brine."
        assert api.get("/api/capabilities")["commands"] == []
        assert salt.calls == []


def test_capabilities_list_what_you_may_run(operator: tuple[Api, FakeSalt]) -> None:
    api, _ = operator
    assert api.get("/api/capabilities")["commands"] == ["test.*", "runners.manage.*"]


def test_admins_pass_arguments_through(admin: tuple[Api, FakeSalt]) -> None:
    api, salt = admin
    preview = post(api, "preview", command="state.apply webserver test=True", target="rover-01")
    assert preview.json()["args"] == ["webserver", "test=True"]
    expect = preview.json()["minions"]
    post(api, "run", command="state.apply webserver test=True", target="rover-01", expect=expect)
    assert salt.started()[0]["arg"] == ["webserver", "test=True"]


def test_list_targets_point_out_unknown_minions(operator: tuple[Api, FakeSalt]) -> None:
    api, _ = operator
    body = post(
        api, "preview", command="test.ping", target="rover-01, rover-04,ghost", target_type="list"
    ).json()
    assert body["minions"] == ["rover-01"]
    assert body["unknown"] == ["rover-04", "ghost"]  # pending keys aren't targetable


def test_regex_targets(operator: tuple[Api, FakeSalt]) -> None:
    api, _ = operator
    ok = post(api, "preview", command="test.ping", target="(rover|dock)-0[12]", target_type="pcre")
    assert ok.json()["minions"] == ["dock-01", "rover-01", "rover-02"]
    bad = post(api, "preview", command="test.ping", target="rover-(", target_type="pcre")
    assert bad.status_code == 422 and "regular expression" in bad.json()["detail"]


@pytest.mark.parametrize("target_type", ["grain", "compound", "nodegroup"])
def test_cache_targets_ask_the_master(operator: tuple[Api, FakeSalt], target_type: str) -> None:
    api, salt = operator
    body = post(
        api, "preview", command="test.ping", target="role:rover", target_type=target_type
    ).json()
    assert body["minions"] == ["rover-01"] and body["from_cache"] is True
    assert salt.calls == [
        ("runner", "cache.grains", {"tgt": "role:rover", "tgt_type": target_type})
    ]


def test_runner_commands_answer_directly(operator: tuple[Api, FakeSalt]) -> None:
    api, salt = operator
    salt.answers["manage.status"] = {"up": ["rover-01"], "down": ["rover-03"]}  # no full_return
    preview = post(api, "preview", command="runners.manage.status").json()
    assert preview["client"] == "runner" and preview["minions"] == []
    resp = post(api, "run", command="runners.manage.status")
    assert resp.json()["result"] == {"up": ["rover-01"], "down": ["rover-03"]}
    (_, _, sent) = salt.calls[-1]
    assert sent["client"] == "runner" and sent["arg"] == [] and sent["wait_seconds"] == 300
    (entry,) = audit_rows(api)
    assert entry.target == "master" and entry.detail is not None
    assert entry.detail["command"] == "runners.manage.status"


def test_wheel_commands_unwrap_the_answer(admin: tuple[Api, FakeSalt]) -> None:
    api, salt = admin
    salt.answers["key.list_all"] = {
        "tag": "salt/wheel/20261020120000000009",
        "data": {"return": {"minions": ["a"]}, "success": True, "jid": "20261020120000000009"},
    }
    resp = post(api, "run", command="wheel.key.list_all")
    assert resp.json()["result"] == {"minions": ["a"]} and resp.json()["success"] is True
    assert resp.json()["jid"] is None  # wheel calls aren't kept as jobs


RUNNER_JID = "20261020120000000100"


def full_return(value: Any, success: bool = True) -> dict[str, Any]:
    """What salt-api answers a runner asked for full_return."""
    data = {"jid": RUNNER_JID, "return": value, "success": success, "user": "brine"}
    return {"tag": f"salt/run/{RUNNER_JID}/ret", "data": data}


def test_runner_commands_are_kept_as_jobs_under_the_person(
    operator: tuple[Api, FakeSalt],
) -> None:
    api, salt = operator
    salt.answers["manage.status"] = full_return({"up": ["rover-01"], "down": []})
    resp = post(api, "run", command="runners.manage.status").json()
    assert resp["jid"] == RUNNER_JID and resp["result"] == {"up": ["rover-01"], "down": []}
    assert salt.calls[-1][2]["full_return"] is True
    job = api.get(f"/api/jobs/{RUNNER_JID}")
    assert (job["kind"], job["fun"], job["user"]) == ("runner", "manage.status", "local")
    assert job["results"][0]["minion_id"] == "master"


def orchestration_return() -> dict[str, Any]:
    step = {"changes": {}, "duration": 120.5, "__sls__": "orch.rollout"}
    return {
        "data": {
            "salt-master_master": {
                "salt_|-rovers-answer_|-test.ping_|-function": {
                    **step,
                    "name": "test.ping",
                    "result": True,
                    "comment": "Function ran successfully.",
                    "__jid__": "20261020120000000201",
                    "__run_num__": 0,
                    "__id__": "rovers-answer",
                },
                "salt_|-dock-calibration_|-dock-calibration_|-state": {
                    **step,
                    "name": "dock-calibration",
                    "result": False,
                    "comment": "Run failed on minions: dock-01",
                    "__jid__": "20261020120000000202",
                    "__run_num__": 1,
                    "__id__": "dock-calibration",
                },
            }
        },
        "outputter": "highstate",
        "retcode": 1,
    }


def test_orchestrations_and_their_steps_belong_to_the_person(
    admin: tuple[Api, FakeSalt],
) -> None:
    api, salt = admin
    salt.answers["state.orchestrate"] = full_return(orchestration_return())
    started = "2026, Oct 20 12:00:00.000000"
    salt.job_cache = {
        "20261020120000000201": {
            "Function": "test.ping",
            "Arguments": [],
            "Target": "rover-*",
            "Target-type": "glob",
            "User": "salt",
            "StartTime": started,
            "Minions": ["rover-01"],
            "Result": {"rover-01": {"return": True, "retcode": 0, "success": True}},
        },
        "20261020120000000202": {
            "Function": "state.sls",
            "Arguments": ["dock"],
            "Target": "dock-01",
            "Target-type": "glob",
            "User": "salt",
            "StartTime": started,
            "Minions": ["dock-01"],
            "Result": {"dock-01": {"return": ["boom"], "retcode": 1, "success": False}},
        },
    }
    resp = post(api, "run", command="runners.state.orchestrate orch.rollout").json()
    # Salt calls the runner a success; a failed step says otherwise.
    assert resp["jid"] == RUNNER_JID and resp["success"] is False

    job = api.get(f"/api/jobs/{RUNNER_JID}")
    steps = job["results"][0]["states"]
    assert [(s["id"], s["result"], s["jid"]) for s in steps] == [
        ("rovers-answer", True, "20261020120000000201"),
        ("dock-calibration", False, "20261020120000000202"),
    ]
    for jid in ("20261020120000000201", "20261020120000000202"):
        step_job = api.get(f"/api/jobs/{jid}")
        assert step_job["user"] == "local" and step_job["returned"] == 1


def test_templates_from_brine_and_the_master(tmp_path: Path) -> None:
    settings = parse_config(
        "salt_api: {url: 'https://salt.test:8000', username: brine, password: x}\n"
        "auth: {provider: none, anonymous_role: operator}\n"
        "commands: {operator: ['test.*']}\n"
        "templates:\n"
        "  ping-docks: {description: 'Docks answering?', target: 'dock-*', command: test.ping}\n"
        "  versions: {description: brine's own, command: runners.manage.versions}\n"
        f"database: 'sqlite:///{(tmp_path / 'brine.db').as_posix()}'\n",
        {},
    )
    app = create_app(settings, frontend_dist=Path("/nonexistent"), run_collector=False)
    salt = FakeSalt()
    salt.master_config = {
        "saltgui_templates": {
            "versions": {"command": "runners.manage.versions", "description": "master's"},
            "fib": {
                "description": "First template",
                "target": "*",
                "command": "test.fib num=10",
                "key": "f",  # SaltGUI's keyboard shortcut: ignored, not an error
                "category": "cat1",
                "categories": ["cat1", "cat2"],
            },
            "only-target": {"targettype": "list", "target": "rover-01,rover-02"},
            "broken": {"targettype": "nonsense", "command": "test.ping"},
        }
    }
    with TestClient(app) as client:
        client.app.state.runtime.client = salt  # type: ignore[attr-defined]
        body = Api(client).get("/api/commands/templates")
    by_name = {t["name"]: t for t in body}
    assert list(by_name) == ["fib", "only-target", "ping-docks", "versions"]
    assert by_name["fib"]["categories"] == ["cat1", "cat2"]
    assert by_name["fib"]["source"] == "master" and by_name["fib"]["allowed"] is True
    assert by_name["only-target"]["target_type"] == "list"
    assert by_name["only-target"]["allowed"] is True  # it only fills in the target
    # brine's own template wins a name clash; operators may not run runners here.
    assert by_name["versions"]["description"] == "brine's own"
    assert by_name["versions"]["source"] == "brine" and by_name["versions"]["allowed"] is False
    assert by_name["ping-docks"]["target"] == "dock-*"


def test_templates_without_master_access_still_list_brines(operator: tuple[Api, FakeSalt]) -> None:
    api, salt = operator
    salt.forbidden.add("config.values")
    assert api.get("/api/commands/templates") == []


def test_salt_refusing_says_what_to_add(admin: tuple[Api, FakeSalt]) -> None:
    api, salt = admin
    salt.forbidden.add("cmd.run")
    resp = post(api, "run", command="cmd.run uptime", target="rover-01", expect=["rover-01"])
    assert resp.status_code == 403
    assert "cmd.run" in resp.json()["detail"] and "external_auth" in resp.json()["detail"]
    assert audit_rows(api) == []


def test_unreadable_commands_are_422(operator: tuple[Api, FakeSalt]) -> None:
    api, _ = operator
    resp = post(api, "preview", command="test.ping 'oops", target="*")
    assert resp.status_code == 422 and "No closing quotation" in resp.json()["detail"]
    assert post(api, "preview", command="test.ping", target=" ").status_code == 422

"""Orchestrations: finding them on the master and reading their steps."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.orchestrations import parse_steps, sls_name
from app.config import parse_config
from app.main import create_app
from app.salt.client import SaltApiForbidden
from tests.test_api import Api

# What state.orchestrate_show_sls answered for demo/states/orch/rollout.sls (trimmed).
ROLLOUT = {
    "salt-master_master": {
        "rovers-answer": {
            "salt": [{"name": "test.ping"}, {"tgt": "rover-*"}, "function", {"order": 10000}],
            "__sls__": "orch.rollout",
            "__env__": "base",
        },
        "dock-calibration": {
            "salt": [
                {"tgt": "dock-01"},
                {"sls": "dock"},
                {"require": [{"salt": "rovers-motd"}]},
                {"onfail": [{"salt": "rovers-answer"}]},
                {"pillar": {"speed": "slow"}},
                "state",
                {"order": 10002},
            ],
            "__sls__": "orch.rollout",
            "__env__": "base",
        },
        "rovers-motd": {
            "salt": [
                {"tgt": "rover-*"},
                {"tgt_type": "glob"},
                {"sls": "motd"},
                {"require": [{"salt": "rovers-answer"}]},
                "state",
                {"order": 10001},
            ],
            "__sls__": "orch.rollout",
            "__env__": "base",
        },
    }
}

FILES = {
    "top.sls": "base:\n  '*':\n    - motd\n",
    "motd.sls": "/etc/motd:\n  file.managed:\n    - contents: hi\n",
    "orch/rollout.sls": "rovers-answer:\n  salt.function:\n    - name: test.ping\n",
    "orch/broken.sls": "{% if %}\nstep:\n  salt.state:\n    - sls: x\n",
    # Inputs given as pillar at run time, the way a reactor passes them.
    "orch/restart.sls": (
        "{% set who = pillar['minion_id'] %}\n"
        "{% set why = salt['pillar.get']('reason', 'asked') %}\n"
        "restart:\n  salt.function:\n    - name: service.restart\n    - tgt: {{ who }}\n"
        '    - arg: [{{ pillar["service"] }}]\n'
    ),
}

# What the master renders orch.restart to, given placeholder pillar.
RESTART = {
    "salt-master_master": {
        "restart": {
            "salt": [{"name": "service.restart"}, {"tgt": "<minion_id>"}, "function", {"order": 1}],
            "__sls__": "orch.restart",
            "__env__": "base",
        }
    }
}


class FakeMaster:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.forbidden: set[str] = set()

    async def wheel(self, fun: str, **kwargs: Any) -> Any:
        self.calls.append((fun, kwargs))
        if fun == "file_roots.list_env":
            return {
                "/srv/salt": {
                    "top.sls": "f",
                    "motd.sls": "f",
                    "orch": {
                        "rollout.sls": "f",
                        "broken.sls": "f",
                        "restart.sls": "f",
                        "README.md": "f",
                    },
                }
            }
        assert fun == "file_roots.read"
        return [{f"/srv/salt/{kwargs['path']}": FILES[kwargs["path"]]}]

    async def runner(self, fun: str, **kwargs: Any) -> Any:
        self.calls.append((fun, kwargs))
        if fun in self.forbidden:
            raise SaltApiForbidden(f"brine's Salt account isn't allowed to run runner {fun}", 403)
        if kwargs["mods"] == "orch.broken":
            return ["Rendering SLS 'base:orch.broken' failed: Jinja syntax error"]
        if kwargs["mods"] == "orch.restart":
            return RESTART
        return ROLLOUT

    async def close(self) -> None:
        pass


def make_api(tmp_path: Path, role: str) -> Iterator[tuple[Api, FakeMaster]]:
    settings = parse_config(
        "salt_api: {url: 'https://salt.test:8000', username: brine, password: x}\n"
        f"auth: {{provider: none, anonymous_role: {role}}}\n"
        "commands: {operator: ['test.*']}\n"
        f"database: 'sqlite:///{(tmp_path / 'brine.db').as_posix()}'\n",
        {},
    )
    app = create_app(settings, frontend_dist=Path("/nonexistent"), run_collector=False)
    master = FakeMaster()
    with TestClient(app) as client:
        client.app.state.runtime.client = master  # type: ignore[attr-defined]
        yield Api(client), master


@pytest.fixture
def admin(tmp_path: Path) -> Iterator[tuple[Api, FakeMaster]]:
    yield from make_api(tmp_path, "admin")


def test_steps_come_in_run_order_with_what_they_do() -> None:
    steps, error = parse_steps(ROLLOUT)
    assert error is None
    assert [(s.id, s.function, s.what, s.target) for s in steps] == [
        ("rovers-answer", "salt.function", "test.ping", "rover-*"),
        ("rovers-motd", "salt.state", "motd", "rover-*"),
        ("dock-calibration", "salt.state", "dock", "dock-01"),
    ]
    motd, dock = steps[1], steps[2]
    assert motd.target_type == "glob" and motd.needs == ["rovers-answer"]
    assert dock.needs == ["rovers-motd", "onfail rovers-answer"]
    assert dock.details == {"pillar": {"speed": "slow"}}


def test_render_errors_are_kept() -> None:
    assert parse_steps(["Jinja syntax error"]) == ([], "Jinja syntax error")


@pytest.mark.parametrize(
    ("path", "name"),
    [("orch/rollout.sls", "orch.rollout"), ("orch/init.sls", "orch"), ("deploy.sls", "deploy")],
)
def test_sls_names(path: str, name: str) -> None:
    assert sls_name(path) == name


def test_only_orchestration_files_are_listed(admin: tuple[Api, FakeMaster]) -> None:
    api, master = admin
    body = api.get("/api/orchestrations")
    assert [(o["sls"], o["error"]) for o in body["orchestrations"]] == [
        ("orch.broken", "Rendering SLS 'base:orch.broken' failed: Jinja syntax error"),
        ("orch.restart", None),
        ("orch.rollout", None),
    ]
    assert body["can_run"] is True and body["truncated"] is False
    rendered = [kw["mods"] for fun, kw in master.calls if fun == "state.orchestrate_show_sls"]
    assert sorted(rendered) == ["orch.broken", "orch.restart", "orch.rollout"]  # not motd/top


def test_pillar_inputs_are_found_and_rendered_with_placeholders(
    admin: tuple[Api, FakeMaster],
) -> None:
    api, master = admin
    restart = next(
        o for o in api.get("/api/orchestrations")["orchestrations"] if o["sls"] == "orch.restart"
    )
    assert restart["inputs"] == [
        {"name": "minion_id", "required": True},
        {"name": "service", "required": True},
        {"name": "reason", "required": False},
    ]
    (call,) = [kw for fun, kw in master.calls if kw.get("mods") == "orch.restart"]
    assert call["pillar"] == {"minion_id": "<minion_id>", "service": "<service>"}
    assert restart["steps"][0]["target"] == "<minion_id>"


def test_the_listing_is_kept_for_a_minute(admin: tuple[Api, FakeMaster]) -> None:
    api, master = admin
    api.get("/api/orchestrations")
    reads = len(master.calls)
    api.get("/api/orchestrations")
    assert len(master.calls) == reads  # from the last minute's listing
    api.get("/api/orchestrations", refresh="true")
    assert len(master.calls) == 2 * reads


def test_running_them_depends_on_the_role(tmp_path: Path) -> None:
    for api, _ in make_api(tmp_path, "operator"):
        assert api.get("/api/orchestrations")["can_run"] is False


def test_salt_refusing_says_what_to_add(admin: tuple[Api, FakeMaster]) -> None:
    api, master = admin
    master.forbidden.add("state.orchestrate_show_sls")
    resp = api.client.get("/api/orchestrations")
    assert resp.status_code == 403 and "state.orchestrate_show_sls" in resp.json()["detail"]

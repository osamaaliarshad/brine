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
                    "orch": {"rollout.sls": "f", "broken.sls": "f", "README.md": "f"},
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
        ("orch.rollout", None),
    ]
    assert body["can_run"] is True and body["truncated"] is False
    rendered = [kw["mods"] for fun, kw in master.calls if fun == "state.orchestrate_show_sls"]
    assert sorted(rendered) == ["orch.broken", "orch.rollout"]  # never motd.sls or top.sls


def test_running_them_depends_on_the_role(tmp_path: Path) -> None:
    for api, _ in make_api(tmp_path, "operator"):
        assert api.get("/api/orchestrations")["can_run"] is False


def test_salt_refusing_says_what_to_add(admin: tuple[Api, FakeMaster]) -> None:
    api, master = admin
    master.forbidden.add("state.orchestrate_show_sls")
    resp = api.client.get("/api/orchestrations")
    assert resp.status_code == 403 and "state.orchestrate_show_sls" in resp.json()["detail"]

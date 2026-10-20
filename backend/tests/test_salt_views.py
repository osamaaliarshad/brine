"""Nodegroups, states and automation: views that ask Salt live."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import parse_config
from app.main import create_app
from app.salt.client import SaltApiUnavailable
from tests.test_api import Api


class ScriptedSalt:
    """Answers wheel/runner/local calls from a table keyed by function name."""

    def __init__(self, answers: dict[str, Any]) -> None:
        self.answers = answers
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def _answer(self, client: str, fun: str, kwargs: dict[str, Any]) -> Any:
        self.calls.append((client, fun, kwargs))
        answer = self.answers[fun]
        if isinstance(answer, Exception):
            raise answer
        return answer(**kwargs) if callable(answer) else answer

    async def wheel(self, fun: str, **kwargs: Any) -> Any:
        return self._answer("wheel", fun, kwargs)

    async def runner(self, fun: str, **kwargs: Any) -> Any:
        return self._answer("runner", fun, kwargs)

    async def local(self, tgt: str, fun: str, **kwargs: Any) -> Any:
        return self._answer("local", fun, {"tgt": tgt, **kwargs})

    async def close(self) -> None:
        pass


@pytest.fixture
def api(tmp_path: Path) -> Iterator[Api]:
    settings = parse_config(
        "salt_api: {url: 'https://salt.test:8000', username: brine, password: x}\n"
        "auth: {provider: none, anonymous_role: admin}\n"
        f"database: 'sqlite:///{(tmp_path / 'brine.db').as_posix()}'\n",
        {},
    )
    app = create_app(settings, frontend_dist=Path("/nonexistent"), run_collector=False)
    with TestClient(app) as client:
        a = Api(client)
        a.seed(a.ingest.keys, {"minions": ["rover-01", "rover-02", "dock-01", "lonely"]})
        yield a


def use(api: Api, salt: ScriptedSalt) -> ScriptedSalt:
    api.client.app.state.runtime.client = salt  # type: ignore[attr-defined]
    return salt


def test_nodegroups_resolve_members_from_the_master_cache(api: Api) -> None:
    members: dict[str, dict[str, Any]] = {
        "rovers": {"rover-01": {}, "rover-02": {}},
        "docks": {"dock-01": {}},
    }
    salt = use(
        api,
        ScriptedSalt(
            {
                "config.values": {
                    "nodegroups": {"rovers": "G@role:rover", "docks": ["dock-01"]},
                    "external_auth": {"pam": {"secret": True}},
                },
                "cache.grains": lambda tgt, tgt_type: members[tgt],
            }
        ),
    )
    resp = api.client.get("/api/nodegroups")
    body = resp.json()
    assert body["groups"] == [
        {"name": "docks", "expression": "dock-01", "members": ["dock-01"]},
        {"name": "rovers", "expression": "G@role:rover", "members": ["rover-01", "rover-02"]},
    ]
    assert body["ungrouped"] == ["lonely"]
    assert "secret" not in resp.text
    assert ("runner", "cache.grains", {"tgt": "rovers", "tgt_type": "nodegroup"}) in salt.calls


def test_no_nodegroups_configured(api: Api) -> None:
    use(api, ScriptedSalt({"config.values": {}}))
    body = api.get("/api/nodegroups")
    assert body["groups"] == [] and len(body["ungrouped"]) == 4


def test_state_top_lists_states_per_minion(api: Api) -> None:
    use(
        api,
        ScriptedSalt(
            {
                "state.show_top": {
                    "rover-01": {"base": ["motd"]},
                    "dock-01": {"base": ["motd", "dock"]},
                    "rover-02": "Minion did not return",
                }
            }
        ),
    )
    top = api.get("/api/states/top")
    assert top["minions"] == {"dock-01": {"base": ["motd", "dock"]}, "rover-01": {"base": ["motd"]}}
    assert top["missing"] == ["lonely", "rover-02"]


def test_state_files_flattens_the_tree(api: Api) -> None:
    tree = {
        "/srv/salt": {"top.sls": "f", "motd.sls": "f", "web": {"init.sls": "f", "files": {}}},
        "/srv/spm/salt": {},
    }
    use(api, ScriptedSalt({"file_roots.list_env": tree}))
    files = api.get("/api/states/files")
    assert [(f["root"], f["path"]) for f in files] == [
        ("/srv/salt", "motd.sls"),
        ("/srv/salt", "top.sls"),
        ("/srv/salt", "web/init.sls"),
    ]


def test_state_file_reads_content_and_refuses_escapes(api: Api) -> None:
    salt = use(
        api,
        ScriptedSalt({"file_roots.read": [{"/srv/salt/motd.sls": "/etc/motd:\n  file.managed"}]}),
    )
    f = api.client.get("/api/states/file", params={"path": "motd.sls"}).json()
    assert f["full_path"] == "/srv/salt/motd.sls" and f["content"].startswith("/etc/motd")
    for bad in ["../etc/shadow", "/etc/shadow", "web/../../x"]:
        assert api.client.get("/api/states/file", params={"path": bad}).status_code == 400
    assert len(salt.calls) == 1  # refused paths never reach salt-api

    use(api, ScriptedSalt({"file_roots.read": []}))
    assert api.client.get("/api/states/file", params={"path": "nope.sls"}).status_code == 404


def test_automation_asks_every_minion(api: Api) -> None:
    salt = use(
        api,
        ScriptedSalt(
            {
                "schedule.list": {
                    "rover-01": {"refresh": {"function": "saltutil.refresh_grains", "minutes": 30}},
                    "dock-01": {},
                }
            }
        ),
    )
    view = api.get("/api/automation/schedules")
    assert view["function"] == "schedule.list"
    assert set(view["results"]) == {"rover-01", "dock-01"}
    assert view["missing"] == ["lonely", "rover-02"]
    assert salt.calls[0][2]["kwarg"] == {"return_yaml": False}
    assert api.client.get("/api/automation/pillar").status_code == 422


def test_salt_views_report_salt_api_errors(api: Api) -> None:
    down = SaltApiUnavailable("down")
    use(
        api,
        ScriptedSalt(
            {
                "config.values": down,
                "state.show_top": down,
                "file_roots.list_env": down,
                "beacons.list": down,
            }
        ),
    )
    for path in [
        "/api/nodegroups",
        "/api/states/top",
        "/api/states/files",
        "/api/automation/beacons",
    ]:
        assert api.client.get(path).status_code == 502, path


def test_live_views_skip_minions_presence_says_are_offline(api: Api) -> None:
    from tests.test_api import NOW

    api.seed(api.ingest.presence, ["rover-01", "dock-01"], at=NOW, method="events")
    salt = use(api, ScriptedSalt({"schedule.list": {"rover-01": {}, "dock-01": {}}}))
    view = api.get("/api/automation/schedules")
    # Asking offline minions would only wait out Salt's timeout.
    assert salt.calls[0][2]["tgt"] == "dock-01,rover-01"
    assert salt.calls[0][2]["tgt_type"] == "list"
    assert view["skipped"] == ["lonely", "rover-02"] and view["missing"] == []


def test_single_minion_live_view_skips_an_offline_minion(api: Api) -> None:
    from tests.test_api import NOW

    api.seed(api.ingest.presence, ["rover-01"], at=NOW, method="events")
    salt = use(api, ScriptedSalt({"pillar.obfuscate": {"rover-02": {}}}))
    view = api.get("/api/minions/rover-02/live/pillar")
    assert view == {**view, "answered": False, "offline": True, "data": None}
    assert salt.calls == []


def test_without_fresh_presence_everyone_is_asked(api: Api) -> None:
    salt = use(api, ScriptedSalt({"state.show_top": {}}))
    top = api.get("/api/states/top")
    assert salt.calls[0][2]["tgt"] == "dock-01,lonely,rover-01,rover-02"
    assert top["skipped"] == [] and len(top["missing"]) == 4

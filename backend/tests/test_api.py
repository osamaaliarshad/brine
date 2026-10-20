from collections.abc import Awaitable, Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import parse_config
from app.ingest import Ingest
from app.main import create_app
from app.salt.client import SaltApiUnavailable

NOW = datetime.now(UTC)

GRAINS = {
    "os": "Debian",
    "osrelease": "12",
    "osfinger": "Debian-12",
    "saltversion": "3006.28",
    "ipv4": ["127.0.0.1", "172.18.0.3"],
    "fqdn_ip4": ["172.18.0.3"],
    "app_version": "2.4.1",
    "hw": {"model": "R2"},
}


class Api:
    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.ingest: Ingest = client.app.state.runtime.ingest  # type: ignore[attr-defined]

    def seed(self, fn: Callable[..., Awaitable[Any]], *args: Any, **kwargs: Any) -> Any:
        assert self.client.portal is not None
        return self.client.portal.call(lambda: fn(*args, **kwargs))

    def get(self, path: str, **params: Any) -> Any:
        resp = self.client.get(path, params=params)
        assert resp.status_code == 200, resp.text
        return resp.json()


@pytest.fixture
def api(tmp_path: Path) -> Iterator[Api]:
    settings = parse_config(
        "salt_api: {url: 'https://salt.test:8000', username: brine, password: x}\n"
        f"database: 'sqlite:///{(tmp_path / 'brine.db').as_posix()}'\n"
        "fleet:\n"
        "  columns:\n"
        "    - {grain: app_version, label: App version}\n"
        "    - {grain: 'hw:model'}\n",
        {},
    )
    app = create_app(settings, frontend_dist=Path("/nonexistent"), run_collector=False)
    with TestClient(app) as client:
        yield Api(client)


def seed_fleet(api: Api, presence_at: datetime = NOW) -> None:
    api.seed(api.ingest.keys, {"minions": ["a", "b"], "minions_pre": ["c"]})
    api.seed(
        api.ingest.presence, ["a", "b"], at=presence_at - timedelta(minutes=1), method="events"
    )
    api.seed(api.ingest.presence, ["a"], at=presence_at, method="events")
    api.seed(api.ingest.grains, "a", GRAINS, at=presence_at, source="minion")


def test_fleet_lists_accepted_minions_with_status(api: Api) -> None:
    seed_fleet(api)
    fleet = api.get("/api/fleet")

    assert fleet["summary"] == {
        "total": 2,
        "online": 1,
        "offline": 1,
        "stale": 0,
        "unknown": 0,
        "pending_keys": 1,
    }
    assert fleet["columns"] == [
        {"grain": "app_version", "label": "App version"},
        {"grain": "hw:model", "label": "hw:model"},
    ]
    assert fleet["presence"]["method"] == "events"
    a, b = fleet["minions"]
    assert a["id"] == "a" and a["status"] == "online"
    assert a["os"] == "Debian 12" and a["salt_version"] == "3006.28" and a["ip"] == "172.18.0.3"
    assert a["columns"] == {"app_version": "2.4.1", "hw:model": "R2"}
    assert a["grains_source"] == "minion" and a["grains_at"] is not None
    assert b["status"] == "offline" and b["last_seen_at"] is not None
    assert b["os"] is None and b["columns"] == {"app_version": None, "hw:model": None}


def test_old_presence_makes_everyone_stale(api: Api) -> None:
    seed_fleet(api, presence_at=NOW - timedelta(minutes=30))
    summary = api.get("/api/fleet")["summary"]
    assert summary["stale"] == 2 and summary["online"] == 0


def test_minion_detail(api: Api) -> None:
    seed_fleet(api)
    api.seed(
        api.ingest.job_new,
        jid="j1",
        kind="local",
        fun="state.apply",
        at=NOW,
        user="alice",
        minions=["a"],
    )
    api.seed(
        api.ingest.job_return,
        jid="j1",
        kind="local",
        minion_id="a",
        fun="state.apply",
        at=NOW,
        data={},
        success=True,
        retcode=0,
    )
    api.seed(
        api.ingest.job_return,
        jid="internal",
        kind="local",
        minion_id="a",
        fun="test.ping",
        at=NOW,
        data=True,
        success=True,
        retcode=0,
        user="brine",
    )

    a = api.get("/api/minions/a")
    assert a["grains"] == GRAINS
    assert [p["connected"] for p in a["presence_history"]] == [True]
    assert [j["jid"] for j in a["recent_jobs"]] == ["j1"]  # brine's own job not recorded

    b = api.get("/api/minions/b")
    assert [p["connected"] for p in b["presence_history"]] == [False, True]  # newest first


def test_unknown_minion_is_404(api: Api) -> None:
    assert api.client.get("/api/minions/nope").status_code == 404
    assert api.client.get("/api/minions/nope/grains/history").status_code == 404


def test_grains_history_diffs(api: Api) -> None:
    v1 = {"os": "Debian", "app_version": "1.0", "old": 1}
    v2 = {"os": "Debian", "app_version": "1.1", "new": 2}
    api.seed(api.ingest.grains, "a", v1, at=NOW - timedelta(hours=1), source="minion")
    api.seed(api.ingest.grains, "a", v2, at=NOW, source="minion")

    newest, oldest = api.get("/api/minions/a/grains/history")
    assert newest["added"] == {"new": 2}
    assert newest["removed"] == {"old": 1}
    assert newest["changed"] == {"app_version": {"from": "1.0", "to": "1.1"}}
    assert oldest["added"] == v1


def seed_jobs(api: Api) -> None:
    for i, (jid, user) in enumerate(
        [("j1", "alice"), ("j2", "brine"), ("j3", "bob"), ("j4", "bob")]
    ):
        api.seed(
            api.ingest.job_new,
            jid=jid,
            kind="local",
            fun="state.apply",
            at=NOW + timedelta(seconds=i),
            user=user,
            minions=["a", "b"],
        )
    api.seed(
        api.ingest.job_return,
        jid="j3",
        kind="local",
        minion_id="a",
        fun="state.apply",
        at=NOW,
        data={},
        success=True,
        retcode=0,
    )
    api.seed(
        api.ingest.job_return,
        jid="j3",
        kind="local",
        minion_id="b",
        fun="state.apply",
        at=NOW,
        data={},
        success=False,
        retcode=2,
    )


def test_jobs_list_paginates_newest_first(api: Api) -> None:
    seed_jobs(api)
    page1 = api.get("/api/jobs", limit=2)
    assert [j["jid"] for j in page1["jobs"]] == ["j4", "j3"]
    assert page1["next_before"] == "j3"
    page2 = api.get("/api/jobs", limit=2, before="j3")
    assert [j["jid"] for j in page2["jobs"]] == ["j1"]  # j2 was brine's own: not recorded
    assert page2["next_before"] is None

    j3 = page1["jobs"][1]
    assert (j3["expected"], j3["returned"], j3["succeeded"], j3["failed"]) == (2, 2, 1, 1)


def test_jobs_filters(api: Api) -> None:
    seed_jobs(api)
    assert len(api.get("/api/jobs")["jobs"]) == 3
    assert [j["jid"] for j in api.get("/api/jobs", minion="b")["jobs"]] == ["j3"]
    assert api.get("/api/jobs", fun="test.ping")["jobs"] == []
    assert api.client.get("/api/jobs", params={"before": "nope"}).status_code == 400


def test_job_detail(api: Api) -> None:
    seed_jobs(api)
    api.seed(
        api.ingest.job_new,
        jid="j5",
        kind="local",
        fun="test.ping",
        at=NOW,
        user="bob",
        minions=["a", "b"],
    )
    api.seed(
        api.ingest.job_return,
        jid="j5",
        kind="local",
        minion_id="a",
        fun="test.ping",
        at=NOW,
        data=True,
        success=True,
        retcode=0,
    )
    job = api.get("/api/jobs/j5")
    assert job["missing"] == ["b"]
    assert [r["minion_id"] for r in job["results"]] == ["a"]
    assert job["results"][0]["data"] is True
    assert api.client.get("/api/jobs/nope").status_code == 404


def test_keys(api: Api) -> None:
    api.seed(api.ingest.keys, {"minions": ["a", "gone"], "minions_pre": ["c"]})
    api.seed(api.ingest.keys, {"minions": ["a"], "minions_pre": ["c"]})
    keys = api.get("/api/keys")
    assert [(k["id"], k["key_state"]) for k in keys] == [("a", "accepted"), ("c", "pending")]


def test_status_reports_collector_and_presence(api: Api) -> None:
    seed_fleet(api)
    status = api.get("/api/status")
    assert status["salt_api"]["connected"] is False
    assert status["salt_api"]["url"] == "https://salt.test:8000/"
    assert status["presence_method_configured"] == "auto"
    assert status["presence"]["method"] == "events"
    assert status["stale_after_minutes"] == 15


def test_fleet_columns_can_be_chosen_per_request(api: Api) -> None:
    seed_fleet(api)
    fleet = api.client.get("/api/fleet", params=[("column", "osfinger"), ("column", "app_version")])
    body = fleet.json()
    assert body["columns"] == [
        {"grain": "osfinger", "label": "osfinger"},
        {"grain": "app_version", "label": "App version"},  # configured label reused
    ]
    assert body["default_columns"][0] == {"grain": "app_version", "label": "App version"}
    a = next(m for m in body["minions"] if m["id"] == "a")
    assert a["columns"] == {"osfinger": "Debian-12", "app_version": "2.4.1"}


def test_fleet_columns_are_deduplicated_and_capped(api: Api) -> None:
    seed_fleet(api)
    params = [("column", "os"), ("column", " os "), ("column", "")]
    assert [c["grain"] for c in api.client.get("/api/fleet", params=params).json()["columns"]] == [
        "os"
    ]
    too_many = [("column", f"g{i}") for i in range(31)]
    assert api.client.get("/api/fleet", params=too_many).status_code == 422


def test_grain_keys_lists_top_level_and_nested(api: Api) -> None:
    seed_fleet(api)
    api.seed(
        api.ingest.grains, "b", {"os": "Debian", "hw": {"model": "R1"}}, at=NOW, source="minion"
    )
    keys = {k["key"]: k["minions"] for k in api.get("/api/grains/keys")}
    assert keys["os"] == 2
    assert keys["hw:model"] == 2
    assert keys["app_version"] == 1
    assert "hw" in keys


class FakeLiveClient:
    def __init__(self, result: dict[str, Any] | Exception) -> None:
        self.result = result
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def close(self) -> None:
        pass

    async def local(self, tgt: str, fun: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append((tgt, fun, kwargs))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def use_live_client(api: Api, fake: FakeLiveClient) -> None:
    api.client.app.state.runtime.client = fake  # type: ignore[attr-defined]


def test_live_view_returns_what_the_minion_answered(api: Api) -> None:
    seed_fleet(api)
    fake = FakeLiveClient({"a": {"db": {"password": "<str>"}}})
    use_live_client(api, fake)
    view = api.get("/api/minions/a/live/pillar")
    assert view["answered"] is True and view["function"] == "pillar.obfuscate"
    assert view["data"] == {"db": {"password": "<str>"}}
    assert fake.calls == [
        ("a", "pillar.obfuscate", {"kwarg": {}, "tgt_type": "list", "salt_timeout": 10})
    ]


def test_live_view_passes_return_yaml_false(api: Api) -> None:
    seed_fleet(api)
    fake = FakeLiveClient({"a": {}})
    use_live_client(api, fake)
    api.get("/api/minions/a/live/beacons")
    assert fake.calls[0][1:] == (
        "beacons.list",
        {"kwarg": {"return_yaml": False}, "tgt_type": "list", "salt_timeout": 10},
    )


def test_live_view_reports_no_answer(api: Api) -> None:
    seed_fleet(api)
    use_live_client(api, FakeLiveClient({}))
    view = api.get("/api/minions/b/live/schedules")
    assert view["answered"] is False and view["data"] is None


def test_live_view_errors(api: Api) -> None:
    seed_fleet(api)
    assert api.client.get("/api/minions/nope/live/mine").status_code == 404
    assert api.client.get("/api/minions/a/live/secrets").status_code == 422
    use_live_client(api, FakeLiveClient(SaltApiUnavailable("down")))
    resp = api.client.get("/api/minions/a/live/mine")
    assert resp.status_code == 502 and "down" in resp.json()["detail"]


def test_jobs_search_and_kind_filter(api: Api) -> None:
    seed_jobs(api)
    api.seed(api.ingest.job_new, jid="r1", kind="runner", fun="manage.up", at=NOW, user="alice")
    api.seed(
        api.ingest.job_new,
        jid="c1",
        kind="local",
        fun="cmd.run",
        at=NOW,
        user="carol",
        target="rover-*",
    )
    assert [j["jid"] for j in api.get("/api/jobs", kind="runner")["jobs"]] == ["r1"]
    assert [j["jid"] for j in api.get("/api/jobs", q="ROVER")["jobs"]] == ["c1"]  # target
    assert [j["jid"] for j in api.get("/api/jobs", q="carol")["jobs"]] == ["c1"]  # user
    assert {j["jid"] for j in api.get("/api/jobs", q="state.")["jobs"]} == {"j1", "j3", "j4"}


def test_job_detail_parses_state_results(api: Api) -> None:
    out = {
        "file_|-motd_|-/etc/motd_|-managed": {"result": True, "comment": "ok", "changes": {"x": 1}}
    }
    api.seed(
        api.ingest.job_new,
        jid="s1",
        kind="local",
        fun="state.apply",
        at=NOW,
        user="alice",
        minions=["a"],
    )
    api.seed(
        api.ingest.job_return,
        jid="s1",
        kind="local",
        minion_id="a",
        fun="state.apply",
        at=NOW + timedelta(seconds=9),
        data=out,
        success=True,
        retcode=0,
    )
    job = api.get("/api/jobs/s1")
    assert job["finished_at"] is not None
    (result,) = job["results"]
    assert result["states"][0]["function"] == "file.managed" and result["states"][0]["changed"]


def test_state_runs_shows_each_minions_latest(api: Api) -> None:
    api.seed(api.ingest.keys, {"minions": ["a", "b", "c"]})
    ok = {"file_|-motd_|-/etc/motd_|-managed": {"result": True, "comment": "", "changes": {}}}
    bad = {"pkg_|-curl_|-curl_|-installed": {"result": False, "comment": "no", "changes": {}}}
    for jid, minion, data, offset in [
        ("old", "a", bad, 0),
        ("new", "a", ok, 60),
        ("b1", "b", bad, 30),
    ]:
        api.seed(
            api.ingest.job_new,
            jid=jid,
            kind="local",
            fun="state.apply",
            at=NOW + timedelta(seconds=offset),
            user="alice",
            minions=[minion],
        )
        api.seed(
            api.ingest.job_return,
            jid=jid,
            kind="local",
            minion_id=minion,
            fun="state.apply",
            at=NOW + timedelta(seconds=offset + 5),
            data=data,
            success=data is ok,
            retcode=0 if data is ok else 2,
        )
    runs = api.get("/api/jobs/state-runs")
    by_minion = {r["minion_id"]: r for r in runs["runs"]}
    assert by_minion["a"]["jid"] == "new" and by_minion["a"]["succeeded"] == 1
    assert (
        by_minion["b"]["failed"] == 1 and by_minion["b"]["states"][0]["function"] == "pkg.installed"
    )
    assert runs["never"] == ["c"]


class FakeWheelClient(FakeLiveClient):
    async def wheel(self, fun: str, **kwargs: Any) -> Any:
        self.calls.append(("", fun, kwargs))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_reactors_returns_only_the_reactor_setting(api: Api) -> None:
    config = {
        "reactor": [
            {"salt/minion/*/start": ["/srv/reactor/start.sls"]},
            {"custom/tag": "/srv/reactor/one.sls"},
        ],
        "external_auth": {"pam": {"brine": ["secret stuff"]}},
    }
    use_live_client(api, FakeWheelClient(config))
    resp = api.client.get("/api/reactors")
    assert resp.json() == [
        {"tag": "salt/minion/*/start", "sls": ["/srv/reactor/start.sls"]},
        {"tag": "custom/tag", "sls": ["/srv/reactor/one.sls"]},
    ]
    assert "secret" not in resp.text


def test_reactors_handles_none_configured_and_errors(api: Api) -> None:
    use_live_client(api, FakeWheelClient({}))
    assert api.get("/api/reactors") == []
    use_live_client(api, FakeWheelClient(SaltApiUnavailable("down")))
    assert api.client.get("/api/reactors").status_code == 502


def test_issues(api: Api) -> None:
    api.seed(api.ingest.keys, {"minions": ["a", "b", "c", "d"], "minions_pre": ["new"]})
    api.seed(api.ingest.presence, ["a", "b", "c"], at=NOW - timedelta(minutes=2), method="events")
    api.seed(api.ingest.presence, ["a", "b"], at=NOW, method="events")  # c went offline
    for mid, version in [("a", "3006.28"), ("b", "3006.28"), ("c", "3006.9")]:
        api.seed(api.ingest.grains, mid, {"saltversion": version}, at=NOW, source="minion")
    bad = {"cmd_|-calibrate_|-false_|-run": {"result": False, "comment": "no", "changes": {}}}
    api.seed(
        api.ingest.job_new,
        jid="s1",
        kind="local",
        fun="state.apply",
        at=NOW,
        user="root",
        minions=["a"],
    )
    api.seed(
        api.ingest.job_return,
        jid="s1",
        kind="local",
        minion_id="a",
        fun="state.apply",
        at=NOW,
        data=bad,
        success=False,
        retcode=2,
    )
    api.seed(
        api.ingest.job_new,
        jid="c1",
        kind="local",
        fun="cmd.run",
        at=NOW,
        user="root",
        target="*",
        minions=["a", "b"],
    )
    api.seed(
        api.ingest.job_return,
        jid="c1",
        kind="local",
        minion_id="b",
        fun="cmd.run",
        at=NOW,
        data="boom",
        success=False,
        retcode=1,
    )

    issues = api.get("/api/issues")
    keys = [i["key"] for i in issues]
    # The collector isn't running in tests, so salt-api shows as unreachable.
    assert keys[:2] == ["salt-api", "state:a"]
    assert {"key:new", "offline:c", "never:d", "version:c", "job-failed:c1"} <= set(keys)
    by_key = {i["key"]: i for i in issues}
    assert by_key["state:a"]["jid"] == "s1" and by_key["state:a"]["title"] == "a: 1 state failed"
    assert by_key["version:c"]["detail"] == "Most of the fleet runs 3006.28."
    assert by_key["job-failed:c1"]["title"] == "cmd.run failed on 1 minion"
    severities = [i["severity"] for i in issues]
    assert severities == sorted(severities, key=["critical", "warning", "info"].index)


def test_presence_blind_minions_are_stale_not_offline(api: Api) -> None:
    seed_fleet(api)  # a online, b offline
    api.seed(api.ingest.presence_blind, {"a": {"ipv4": ["10.0.0.1"]}})  # b has no cached IPs
    by_id = {m["id"]: m["status"] for m in api.get("/api/fleet")["minions"]}
    assert by_id == {"a": "online", "b": "stale"}
    keys = {k["id"]: k["status"] for k in api.get("/api/keys")}
    assert keys["b"] == "stale"
    issue_keys = [i["key"] for i in api.get("/api/issues")]
    assert "blind:b" in issue_keys and "offline:b" not in issue_keys

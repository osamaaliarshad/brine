"""Key management: accepting, rejecting and deleting minion keys, and who may."""

import fnmatch
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import parse_config
from app.main import create_app
from app.salt.acl import allows, missing
from app.salt.client import SaltApiForbidden, SaltApiUnavailable
from tests.test_api import Api

CSRF = {"X-Requested-With": "brine"}
ALL_KEY_PERMS = [{"@wheel": ["key.list_all", "key.finger", "key.*_dict"]}]


class FakeMaster:
    """Key directories that wheel key.*_dict calls really move keys between."""

    def __init__(self, perms: list[Any] | None = None) -> None:
        self.dirs: dict[str, dict[str, str]] = {
            "minions": {"rover-01": "aa:01", "web1": "aa:w1", "web[1]": "aa:wb"},
            "minions_pre": {"rover-04": "aa:04"},
            "minions_rejected": {"rover-05": "aa:05"},
            "minions_denied": {},
        }
        self.perms = ALL_KEY_PERMS if perms is None else perms
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.forbidden: set[str] = set()
        self.down = False

    async def permissions(self) -> list[Any]:
        if self.down:
            raise SaltApiUnavailable("down")
        return self.perms

    def _move(self, match: dict[str, list[str]], allowed: set[str], to: str) -> None:
        for name, ids in match.items():
            for mid in ids:
                if name in allowed and mid in self.dirs[name]:
                    self.dirs[to][mid] = self.dirs[name].pop(mid)

    async def wheel(self, fun: str, **kwargs: Any) -> Any:
        self.calls.append((fun, kwargs))
        if fun in self.forbidden:
            raise SaltApiForbidden(f"brine's Salt account isn't allowed to run wheel {fun}", 403)
        match: Any = kwargs.get("match")
        if fun == "key.finger":
            return {
                name: {k: fp for k, fp in keys.items() if fnmatch.fnmatchcase(k, match)}
                for name, keys in self.dirs.items()
            }
        if fun == "key.list_all":
            return {name: sorted(keys) for name, keys in self.dirs.items()}
        if fun == "key.accept_dict":
            extra = {"minions_rejected"} if kwargs.get("include_rejected") else set()
            self._move(match, {"minions_pre"} | extra, "minions")
        elif fun == "key.reject_dict":
            extra = {"minions"} if kwargs.get("include_accepted") else set()
            self._move(match, {"minions_pre"} | extra, "minions_rejected")
        elif fun == "key.delete_dict":
            for name, ids in match.items():
                for mid in ids:
                    self.dirs[name].pop(mid, None)
        return {}

    def state_of(self, mid: str) -> list[str]:
        return [name for name, keys in self.dirs.items() if mid in keys]

    def changed(self) -> list[str]:
        return [fun for fun, _ in self.calls if fun.endswith("_dict")]

    async def close(self) -> None:
        pass


def make_api(tmp_path: Path, role: str = "admin") -> Iterator[tuple[Api, FakeMaster]]:
    settings = parse_config(
        "salt_api: {url: 'https://salt.test:8000', username: brine, password: x}\n"
        f"auth: {{provider: none, anonymous_role: {role}}}\n"
        f"database: 'sqlite:///{(tmp_path / 'brine.db').as_posix()}'\n",
        {},
    )
    app = create_app(settings, frontend_dist=Path("/nonexistent"), run_collector=False)
    master = FakeMaster()
    with TestClient(app) as client:
        client.app.state.runtime.client = master  # type: ignore[attr-defined]
        api = Api(client)
        api.seed(api.ingest.keys, {name: sorted(keys) for name, keys in master.dirs.items()})
        yield api, master


@pytest.fixture
def setup(tmp_path: Path) -> Iterator[tuple[Api, FakeMaster]]:
    yield from make_api(tmp_path)


def act(api: Api, mid: str, action: str, **body: Any) -> Any:
    return api.client.post(f"/api/keys/{mid}/{action}", json=body, headers=CSRF)


def audit(api: Api) -> list[tuple[str, str | None, Any]]:
    entries = api.get("/api/audit")["entries"]
    return [(e["action"], e["target"], e["detail"]) for e in entries]


def test_accepting_a_pending_key(setup: tuple[Api, FakeMaster]) -> None:
    api, master = setup
    resp = act(api, "rover-04", "accept", state="pending", fingerprint="aa:04")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"id": "rover-04", "key_state": "accepted"}
    assert master.state_of("rover-04") == ["minions"]
    assert ("key.accept_dict", {"match": {"minions_pre": ["rover-04"]}}) in master.calls
    keys = {k["id"]: k["key_state"] for k in api.get("/api/keys")}
    assert keys["rover-04"] == "accepted"
    assert audit(api)[0] == (
        "key.accept",
        "rover-04",
        {"from": "pending", "fingerprint": "aa:04"},
    )


def test_accepting_needs_the_fingerprint_you_checked(setup: tuple[Api, FakeMaster]) -> None:
    api, master = setup
    assert act(api, "rover-04", "accept", state="pending").status_code == 422
    # The key was swapped since the page loaded: refuse, and say what it is now.
    master.dirs["minions_pre"]["rover-04"] = "bb:66"
    resp = act(api, "rover-04", "accept", state="pending", fingerprint="aa:04")
    assert resp.status_code == 409 and "bb:66" in resp.json()["detail"]
    assert master.changed() == [] and master.state_of("rover-04") == ["minions_pre"]


def test_refuses_when_the_key_moved_since_you_looked(setup: tuple[Api, FakeMaster]) -> None:
    api, master = setup
    master.dirs["minions"]["rover-04"] = master.dirs["minions_pre"].pop("rover-04")
    resp = act(api, "rover-04", "reject", state="pending")
    assert resp.status_code == 409
    assert "accepted now, not pending" in resp.json()["detail"]
    assert act(api, "nobody", "delete", state="pending", confirm="nobody").status_code == 409
    assert master.changed() == []


def test_deleting_takes_typing_the_name(setup: tuple[Api, FakeMaster]) -> None:
    api, master = setup
    assert act(api, "rover-01", "delete", state="accepted").status_code == 422
    assert act(api, "rover-01", "delete", state="accepted", confirm="rover-0").status_code == 422
    resp = act(api, "rover-01", "delete", state="accepted", confirm="rover-01")
    assert resp.json() == {"id": "rover-01", "key_state": "deleted"}
    assert master.state_of("rover-01") == []
    assert "rover-01" not in {k["id"] for k in api.get("/api/keys")}
    assert "rover-01" not in {m["id"] for m in api.get("/api/fleet")["minions"]}


def test_rejecting_an_accepted_key_takes_typing_the_name(setup: tuple[Api, FakeMaster]) -> None:
    api, master = setup
    assert act(api, "rover-01", "reject", state="accepted").status_code == 422
    resp = act(api, "rover-01", "reject", state="accepted", confirm="rover-01")
    assert resp.json()["key_state"] == "rejected"
    assert master.calls[-3] == (
        "key.reject_dict",
        {"match": {"minions": ["rover-01"]}, "include_accepted": True},
    )
    # Rejecting a pending key is undoable, so a plain confirmation is enough.
    assert act(api, "rover-04", "reject", state="pending").json()["key_state"] == "rejected"


def test_accepting_a_rejected_key(setup: tuple[Api, FakeMaster]) -> None:
    api, master = setup
    resp = act(api, "rover-05", "accept", state="rejected", fingerprint="aa:05")
    assert resp.json()["key_state"] == "accepted"
    assert (
        "key.accept_dict",
        {"match": {"minions_rejected": ["rover-05"]}, "include_rejected": True},
    ) in master.calls


@pytest.mark.parametrize(
    ("mid", "action", "state"),
    [("rover-01", "accept", "accepted"), ("rover-05", "reject", "rejected")],
)
def test_actions_that_dont_apply_are_refused(
    setup: tuple[Api, FakeMaster], mid: str, action: str, state: str
) -> None:
    api, master = setup
    resp = act(api, mid, action, state=state, fingerprint="x", confirm=mid)
    assert resp.status_code == 409
    assert master.calls == []


def test_glob_characters_in_ids_match_only_that_minion(setup: tuple[Api, FakeMaster]) -> None:
    api, master = setup
    resp = act(api, "web[1]", "delete", state="accepted", confirm="web[1]")
    assert resp.status_code == 200, resp.text
    assert master.state_of("web[1]") == [] and master.state_of("web1") == ["minions"]
    assert master.calls[0] == ("key.finger", {"match": "web[[]1]"})


def test_only_admins_manage_keys(tmp_path: Path) -> None:
    for api, master in make_api(tmp_path, role="operator"):
        resp = act(api, "rover-04", "accept", state="pending", fingerprint="aa:04")
        assert resp.status_code == 403 and master.calls == []


def test_writes_without_the_csrf_header_are_refused(setup: tuple[Api, FakeMaster]) -> None:
    api, master = setup
    resp = api.client.post(
        "/api/keys/rover-04/accept", json={"state": "pending", "fingerprint": "aa:04"}
    )
    assert resp.status_code == 403 and master.calls == []


def test_salt_refusing_says_what_to_add(setup: tuple[Api, FakeMaster]) -> None:
    api, master = setup
    master.forbidden.add("key.delete_dict")
    resp = act(api, "rover-04", "delete", state="pending", confirm="rover-04")
    assert resp.status_code == 403
    detail = resp.json()["detail"]
    assert "key.delete_dict" in detail and "external_auth" in detail
    assert audit(api) == []


def test_capabilities_follow_the_salt_acl(setup: tuple[Api, FakeMaster]) -> None:
    api, master = setup
    assert api.get("/api/capabilities")["manage_keys"] == {"allowed": True, "missing": []}
    master.perms = [{"@wheel": ["key.list_all", "key.finger", "key.delete_dict"]}]
    assert api.get("/api/capabilities")["manage_keys"] == {
        "allowed": False,
        "missing": ["key.accept_dict", "key.reject_dict"],
    }
    master.down = True
    assert api.get("/api/capabilities")["manage_keys"] == {"allowed": None, "missing": []}


@pytest.mark.parametrize(
    ("perms", "allowed"),
    [
        (["@wheel"], True),
        (["@wheels"], True),
        (["@key"], True),  # a whole module
        (["@runner", "@jobs"], False),
        ([{"@wheel": ["key.accept_dict"]}], True),
        ([{"@wheel": ["key.*"]}], True),
        ([{"@wheel": ["key.accept"]}], True),  # Salt matches from the start, like re.match
        ([{"@wheel": ["key.list_all", "key.finger"]}], False),
        ([{"@key": ["accept_dict"]}], True),
        ([{"@key": ["reject_dict"]}], False),
        ([{"@wheel": [{"key.accept_dict": {"kwargs": {"match": ".*"}}}]}], True),
        ([{"@runner": ["key.accept_dict"]}], False),
        ([{"*": ["key.accept_dict"]}], False),  # minion functions, not wheel
        ([{"@wheel": ["key.[accept"]}], False),  # invalid regex never matches
        ([".*"], False),
    ],
)
def test_acl_matching(perms: list[Any], allowed: bool) -> None:
    assert allows(perms, "wheel", "key.accept_dict") is allowed


def test_acl_missing_lists_what_to_add() -> None:
    perms = [{"@wheel": ["key.accept_dict"]}]
    funs = ["key.accept_dict", "key.reject_dict"]
    assert missing(perms, "wheel", funs) == ["key.reject_dict"]

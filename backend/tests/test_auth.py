"""Sign-in, sessions, roles and the audit log, with a fake identity provider."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
import pytest
from authlib.integrations.starlette_client import OAuthError
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from app.api.auth import safe_next
from app.auth.roles import role_for
from app.config import ConfigError, Settings, parse_config
from app.main import create_app

CSRF = {"X-Requested-With": "brine"}

OIDC = """
salt_api: {url: 'https://salt.test:8000', username: brine, password: x}
auth:
  issuer: https://accounts.google.com
  client_id: test-client
  client_secret: test-secret
  allowed_domains: [example.com]
roles:
  viewer: ["*@example.com"]
  admin: ["boss@example.com"]
"""


class FakeIdP:
    """Plays the identity provider: redirects out, then hands back whatever userinfo we set."""

    def __init__(self) -> None:
        self.userinfo: dict[str, Any] = {}
        self.error: OAuthError | None = None
        self.redirect_uris: list[str] = []

    async def authorize_redirect(self, request: Request, redirect_uri: str) -> Response:
        self.redirect_uris.append(redirect_uri)
        return RedirectResponse(f"https://idp.test/authorize?redirect_uri={quote(redirect_uri)}")

    async def authorize_access_token(self, request: Request) -> dict[str, Any]:
        if self.error:
            raise self.error
        return {"userinfo": self.userinfo}


def settings_for(tmp_path: Path, extra: str = "") -> Settings:
    return parse_config(
        OIDC + extra + f"database: 'sqlite:///{(tmp_path / 'brine.db').as_posix()}'\n", {}
    )


@pytest.fixture
def idp() -> FakeIdP:
    return FakeIdP()


@pytest.fixture
def client(tmp_path: Path, idp: FakeIdP) -> Iterator[TestClient]:
    app = create_app(
        settings_for(tmp_path), frontend_dist=Path("/nonexistent"), run_collector=False
    )
    with TestClient(app) as c:
        c.app.state.runtime.oidc = idp  # type: ignore[attr-defined]
        yield c


def sign_in(c: TestClient, idp: FakeIdP, email: str, next_path: str = "/") -> httpx.Response:
    idp.userinfo = {"email": email, "email_verified": True, "name": email.split("@")[0]}
    c.get("/api/auth/login", params={"next": next_path}, follow_redirects=False)
    resp: httpx.Response = c.get("/api/auth/callback", follow_redirects=False)
    return resp


def audit_actions(c: TestClient, idp: FakeIdP) -> list[tuple[str, str]]:
    sign_in(c, idp, "boss@example.com")
    entries = c.get("/api/audit").json()["entries"]
    return [(e["action"], e["actor"]) for e in reversed(entries)]


# --- the lock -------------------------------------------------------------------------------


def test_everything_needs_a_user_except_sign_in_and_health(client: TestClient) -> None:
    for path in [
        "/api/fleet",
        "/api/jobs",
        "/api/keys",
        "/api/status",
        "/api/settings",
        "/api/issues",
        "/api/stream",
        "/api/events/stream",
        "/api/audit",
        "/api/inventory/keys",
        "/api/inventory/values?key=@packages:x",
        "/api/inventory/changes",
        "/api/inventory/compare?reference=x",
        "/api/minions/x/inventory",
    ]:
        assert client.get(path).status_code == 401, path
    assert client.get("/api/healthz").status_code == 200
    assert client.get("/api/auth/info").json() == {"provider": "oidc", "display_name": "Google"}
    assert client.get("/api/auth/me").status_code == 401


# --- signing in -----------------------------------------------------------------------------


def test_login_sends_you_to_the_provider_with_our_callback(
    client: TestClient, idp: FakeIdP
) -> None:
    resp = client.get("/api/auth/login", params={"next": "/jobs"}, follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert resp.headers["location"].startswith("https://idp.test/authorize")
    assert idp.redirect_uris == ["http://testserver/api/auth/callback"]


def test_public_url_sets_the_callback(tmp_path: Path, idp: FakeIdP) -> None:
    settings = settings_for(tmp_path, "public_url: https://brine.example.com\n")
    with TestClient(create_app(settings, frontend_dist=Path("/x"), run_collector=False)) as c:
        c.app.state.runtime.oidc = idp  # type: ignore[attr-defined]
        c.get("/api/auth/login", follow_redirects=False)
    assert idp.redirect_uris == ["https://brine.example.com/api/auth/callback"]


def test_successful_sign_in(client: TestClient, idp: FakeIdP) -> None:
    resp = sign_in(client, idp, "alice@example.com", next_path="/jobs?tab=states")
    assert resp.status_code == 303 and resp.headers["location"] == "/jobs?tab=states"
    me = client.get("/api/auth/me").json()
    assert me == {
        "email": "alice@example.com",
        "name": "alice",
        "picture": None,
        "role": "viewer",
        "provider": "oidc",
    }
    assert client.get("/api/fleet").status_code == 200
    cookie = resp.headers["set-cookie"].lower()
    assert "brine_session=" in cookie and "httponly" in cookie and "samesite=lax" in cookie


def test_people_without_a_role_are_turned_away(client: TestClient, idp: FakeIdP) -> None:
    resp = sign_in(client, idp, "stranger@gmail.com")
    assert resp.headers["location"] == "/login?error=denied"
    assert client.get("/api/fleet").status_code == 401
    assert ("auth.login_denied", "stranger@gmail.com") in audit_actions(client, idp)


def test_unverified_email_is_refused(client: TestClient, idp: FakeIdP) -> None:
    idp.userinfo = {"email": "alice@example.com", "email_verified": False}
    client.get("/api/auth/login", follow_redirects=False)
    resp = client.get("/api/auth/callback", follow_redirects=False)
    assert resp.headers["location"] == "/login?error=unverified"


def test_provider_errors_go_back_to_the_login_page(client: TestClient, idp: FakeIdP) -> None:
    idp.error = OAuthError(error="mismatching_state")
    resp = client.get("/api/auth/callback", follow_redirects=False)
    assert resp.headers["location"] == "/login?error=failed"


def test_logout(client: TestClient, idp: FakeIdP) -> None:
    sign_in(client, idp, "alice@example.com")
    assert client.post("/api/auth/logout", headers=CSRF).status_code == 204
    assert client.get("/api/fleet").status_code == 401
    assert ("auth.logout", "alice@example.com") in audit_actions(client, idp)


def test_writes_need_the_csrf_header(client: TestClient, idp: FakeIdP) -> None:
    # A form on another site can POST with the cookie, but can't add a custom header.
    sign_in(client, idp, "alice@example.com")
    resp = client.post("/api/auth/logout")
    assert resp.status_code == 403 and "X-Requested-With" in resp.json()["detail"]
    assert client.get("/api/fleet").status_code == 200  # still signed in


def test_tampered_session_cookie_is_ignored(client: TestClient, idp: FakeIdP) -> None:
    sign_in(client, idp, "alice@example.com")
    value = client.cookies.get("brine_session")
    assert value
    client.cookies.set("brine_session", value[:-4] + "AAAA")
    assert client.get("/api/fleet").status_code == 401


def test_roles_are_rechecked_on_every_request(
    client: TestClient, idp: FakeIdP, tmp_path: Path
) -> None:
    sign_in(client, idp, "alice@example.com")
    runtime = client.app.state.runtime  # type: ignore[attr-defined]
    runtime.settings = settings_for(tmp_path).model_copy(
        update={"roles": runtime.settings.roles.model_copy(update={"viewer": []})}
    )
    assert client.get("/api/fleet").status_code == 401


# --- roles and the audit log ----------------------------------------------------------------


def test_audit_log_is_admin_only_and_records_sign_ins(client: TestClient, idp: FakeIdP) -> None:
    sign_in(client, idp, "alice@example.com")
    assert client.get("/api/audit").status_code == 403
    actions = audit_actions(client, idp)
    assert actions[:2] == [("auth.login", "alice@example.com"), ("auth.login", "boss@example.com")]
    page = client.get("/api/audit", params={"action": "auth.", "limit": 1}).json()
    assert len(page["entries"]) == 1 and page["next_before"] is not None


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("/jobs?tab=states", "/jobs?tab=states"),
        ("//evil.example.com", "/"),
        ("https://evil.example.com", "/"),
        ("/\\evil.example.com", "/"),
        (None, "/"),
    ],
)
def test_safe_next(given: str | None, expected: str) -> None:
    assert safe_next(given) == expected


def test_role_mapping(tmp_path: Path) -> None:
    s = settings_for(tmp_path)
    assert role_for("boss@example.com", s.roles, s.auth) == "admin"  # highest wins
    assert role_for("Alice@Example.com", s.roles, s.auth) == "viewer"  # case-insensitive
    assert role_for("boss@gmail.com", s.roles, s.auth) is None  # domain gate
    assert role_for("not-an-email", s.roles, s.auth) is None


def test_half_configured_oidc_refuses_to_start() -> None:
    with pytest.raises(ConfigError, match=r"oidc-providers\.md"):
        parse_config("salt_api: {url: 'https://s.test', username: u, password: p}\n", {})


# --- sign-in off ----------------------------------------------------------------------------


def test_sign_in_off_treats_everyone_as_the_anonymous_role(tmp_path: Path) -> None:
    settings = parse_config(
        "salt_api: {url: 'https://salt.test:8000', username: brine, password: x}\n"
        "auth: {provider: none, anonymous_role: viewer}\n"
        f"database: 'sqlite:///{(tmp_path / 'brine.db').as_posix()}'\n",
        {},
    )
    with TestClient(create_app(settings, frontend_dist=Path("/x"), run_collector=False)) as c:
        assert c.get("/api/auth/me").json()["role"] == "viewer"
        assert c.get("/api/auth/info").json()["provider"] == "none"
        assert c.get("/api/fleet").status_code == 200
        assert c.get("/api/audit").status_code == 403  # viewer
        resp = c.get("/api/auth/login", params={"next": "/keys"}, follow_redirects=False)
        assert resp.headers["location"] == "/keys"

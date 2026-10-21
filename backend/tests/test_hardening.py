"""Security hardening: framing, cross-site reads, verified emails, regex targets, refreshes."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.api.commands as commands_api
from app.main import create_app
from tests.test_auth import FakeIdP, settings_for, sign_in
from tests.test_commands import CSRF
from tests.test_commands import make_api as command_api
from tests.test_orchestrations import make_api as orchestration_api


def test_pages_and_api_refuse_framing(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>brine</html>", encoding="utf-8")
    app = create_app(settings_for(tmp_path), frontend_dist=dist, run_collector=False)
    with TestClient(app) as c:
        for path in ("/", "/run", "/api/healthz"):
            headers = c.get(path).headers
            assert headers["x-frame-options"] == "DENY"
            assert headers["content-security-policy"] == "frame-ancestors 'none'"
            assert headers["x-content-type-options"] == "nosniff"


def test_reads_sent_from_other_sites_are_refused(tmp_path: Path) -> None:
    idp = FakeIdP()
    app = create_app(
        settings_for(tmp_path), frontend_dist=Path("/nonexistent"), run_collector=False
    )
    with TestClient(app) as c:
        c.app.state.runtime.oidc = idp  # type: ignore[attr-defined]
        sign_in(c, idp, "alice@example.com")
        # A link or image on another site: refused, even though the cookie came along.
        cross = {"Sec-Fetch-Site": "cross-site"}
        assert c.get("/api/fleet", headers=cross).status_code == 403
        assert c.get("/api/fleet", headers={"Sec-Fetch-Site": "same-origin"}).status_code == 200
        assert c.get("/api/fleet").status_code == 200  # browsers without the header still work
        # The sign-in provider sending you back is cross-site by nature.
        idp.userinfo = {"email": "alice@example.com", "email_verified": True}
        callback = c.get("/api/auth/callback", headers=cross, follow_redirects=False)
        assert callback.status_code == 303


@pytest.mark.parametrize(
    ("claims", "required", "signed_in"),
    [
        ({"email_verified": True}, True, True),
        ({}, True, False),  # the provider didn't say: not good enough by default
        ({"email_verified": "false"}, True, False),
        ({}, False, True),  # Microsoft Entra never says; opted out in the config
    ],
)
def test_sign_in_needs_a_verified_email(
    tmp_path: Path, claims: dict[str, Any], required: bool, signed_in: bool
) -> None:
    settings = settings_for(tmp_path)
    settings = settings.model_copy(
        update={"auth": settings.auth.model_copy(update={"require_verified_email": required})}
    )
    idp = FakeIdP()
    app = create_app(settings, frontend_dist=Path("/nonexistent"), run_collector=False)
    with TestClient(app) as c:
        c.app.state.runtime.oidc = idp  # type: ignore[attr-defined]
        c.get("/api/auth/login", follow_redirects=False)
        idp.userinfo = {"email": "alice@example.com", **claims}
        resp = c.get("/api/auth/callback", follow_redirects=False)
    assert (resp.headers["location"] == "/") is signed_in


def _preview(api: Any, target: str) -> Any:
    body = {"command": "test.ping", "target": target, "target_type": "pcre"}
    return api.client.post("/api/commands/preview", json=body, headers=CSRF)


def test_regex_targets_are_limited(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for api, _ in command_api(tmp_path, "operator"):
        too_long = _preview(api, "a" * 201)
        assert too_long.status_code == 422 and "under 200" in too_long.json()["detail"]
        monkeypatch.setattr(commands_api, "REGEX_SECONDS", 0.0)
        slow = _preview(api, "rover-.*")
        assert slow.status_code == 422 and "too long" in slow.json()["detail"]


def test_only_operators_force_orchestrations_to_render_again(tmp_path: Path) -> None:
    for api, _ in orchestration_api(tmp_path, "viewer"):
        assert api.client.get("/api/orchestrations").status_code == 200
        assert api.client.get("/api/orchestrations?refresh=true").status_code == 403
        assert api.client.get("/api/orchestrations?saltenv=../../etc").status_code == 422

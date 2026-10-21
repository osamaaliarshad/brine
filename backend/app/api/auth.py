"""Sign-in with OpenID Connect: /api/auth/login → provider → /api/auth/callback → session.

These routes are public (you can't be signed in yet); everything else under /api requires a
user. See docs/oidc-providers.md for setting up a provider.
"""

from __future__ import annotations

import logging

from authlib.integrations.starlette_client import OAuthError
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel

from app.api.deps import RuntimeDep
from app.audit import record
from app.auth.oidc import provider_name
from app.auth.roles import role_for
from app.auth.users import SESSION_USER, User, current_user

log = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


class AuthInfo(BaseModel):
    provider: str  # "oidc" or "none"
    display_name: str  # for the sign-in button


def safe_next(value: str | None) -> str:
    """Only same-site paths: never redirect somewhere else after sign-in."""
    if value and value.startswith("/") and not value.startswith("//") and "\\" not in value:
        return value
    return "/"


def _redirect_uri(request: Request, runtime: RuntimeDep) -> str:
    if runtime.settings.public_url:
        return str(runtime.settings.public_url).rstrip("/") + "/api/auth/callback"
    return str(request.url_for("auth_callback"))


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("/info", response_model=AuthInfo)
async def info(runtime: RuntimeDep) -> AuthInfo:
    auth = runtime.settings.auth
    return AuthInfo(provider=auth.provider, display_name=provider_name(auth))


@router.get("/login")
async def login(request: Request, runtime: RuntimeDep, next: str | None = None) -> Response:
    if runtime.oidc is None:  # sign-in is off: nothing to do
        return RedirectResponse(safe_next(next), status_code=303)
    request.session["next"] = safe_next(next)
    return await runtime.oidc.authorize_redirect(request, _redirect_uri(request, runtime))


@router.get("/callback", name="auth_callback")
async def callback(request: Request, runtime: RuntimeDep) -> Response:
    if runtime.oidc is None:
        return RedirectResponse("/", status_code=303)
    try:
        token = await runtime.oidc.authorize_access_token(request)
    except OAuthError as exc:
        log.warning("sign-in failed: %s", exc)
        return RedirectResponse("/login?error=failed", status_code=303)

    claims = token.get("userinfo") or {}
    email = claims.get("email")
    verified = (
        claims.get("email_verified") is True or not runtime.settings.auth.require_verified_email
    )
    if not isinstance(email, str) or not verified:
        await record(
            runtime.sessions,
            actor=str(email or "unknown"),
            action="auth.login_denied",
            detail={"reason": "no verified email", "ip": _client_ip(request)},
        )
        return RedirectResponse("/login?error=unverified", status_code=303)

    role = role_for(email, runtime.settings.roles, runtime.settings.auth)
    if role is None:
        await record(
            runtime.sessions,
            actor=email,
            action="auth.login_denied",
            detail={"reason": "no role", "ip": _client_ip(request)},
        )
        return RedirectResponse("/login?error=denied", status_code=303)

    destination = safe_next(request.session.get("next"))
    request.session.clear()  # drop sign-in state; start a fresh session
    request.session[SESSION_USER] = {
        "email": email,
        "name": claims.get("name") or email,
    }
    await record(
        runtime.sessions,
        actor=email,
        action="auth.login",
        detail={"role": role, "ip": _client_ip(request)},
    )
    return RedirectResponse(destination, status_code=303)


@router.post("/logout", status_code=204)
async def logout(request: Request, runtime: RuntimeDep) -> Response:
    user = request.session.get(SESSION_USER)
    if isinstance(user, dict) and user.get("email"):
        await record(runtime.sessions, actor=str(user["email"]), action="auth.logout")
    request.session.clear()
    return Response(status_code=204)


@router.get("/me", response_model=User)
async def me(request: Request) -> User:
    return await current_user(request)

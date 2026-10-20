"""The signed-in user, as a FastAPI dependency."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel

from app.auth.roles import at_least, role_for
from app.config import Role
from app.runtime import Runtime

SESSION_USER = "user"


class User(BaseModel):
    email: str
    name: str
    picture: str | None = None
    role: Role
    provider: str  # "oidc" or "none" (sign-in off)


async def current_user(request: Request) -> User:
    """The user making this request, or 401.

    Roles are worked out again on every request from the config, so taking someone out of it
    locks them out immediately, not when their session expires.
    """
    runtime: Runtime = request.app.state.runtime
    auth = runtime.settings.auth
    if auth.provider == "none":
        return User(email="local", name="Local user", role=auth.anonymous_role, provider="none")
    data = request.session.get(SESSION_USER)
    if not isinstance(data, dict) or not isinstance(data.get("email"), str):
        raise HTTPException(401, "sign in first")
    role = role_for(data["email"], runtime.settings.roles, auth)
    if role is None:
        request.session.clear()
        raise HTTPException(401, "your account no longer has access")
    return User(
        email=data["email"],
        name=str(data.get("name") or data["email"]),
        picture=data.get("picture"),
        role=role,
        provider="oidc",
    )


CurrentUser = Annotated[User, Depends(current_user)]


def require_role(needed: Role) -> Callable[..., Coroutine[Any, Any, User]]:
    async def check(user: CurrentUser) -> User:
        if not at_least(user.role, needed):
            raise HTTPException(403, f"needs the {needed} role")
        return user

    return check

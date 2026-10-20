"""Signed session cookies whose key comes from the running app.

Starlette's SessionMiddleware needs its secret when the app is built, but brine's secret may
live in its database, which only exists once startup has run. This wrapper creates the real
middleware on the first request, from `app.state.runtime.session_secret`.
"""

from __future__ import annotations

from typing import Any

from starlette.middleware.sessions import SessionMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

SESSION_COOKIE = "brine_session"


class LazySessionMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.inner: SessionMiddleware | None = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        if self.inner is None:
            runtime: Any = scope["app"].state.runtime
            auth = runtime.settings.auth
            public_url = runtime.settings.public_url
            self.inner = SessionMiddleware(
                self.app,
                secret_key=runtime.session_secret,
                session_cookie=SESSION_COOKIE,
                max_age=auth.session_hours * 3600,
                same_site="lax",
                https_only=bool(public_url and public_url.scheme == "https"),
            )
        await self.inner(scope, receive, send)

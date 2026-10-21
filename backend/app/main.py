"""FastAPI entrypoint: JSON API under /api, and the built frontend for everything else."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.types import Scope

from app import catchup, retention
from app.api import api_router, orchestrations
from app.auth.session import LazySessionMiddleware
from app.config import Settings, load_config
from app.runtime import Runtime

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def _app_version() -> str:
    try:
        return version("brine")
    except PackageNotFoundError:
        return "dev"


class SPAStaticFiles(StaticFiles):
    """Static files that fall back to index.html, so client-side routes survive a reload.

    Files under /assets/ have a content hash in their name, so browsers may keep them forever;
    everything else (index.html above all) is checked on every load, so an upgraded brine shows
    up without anyone clearing their cache.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            response = await super().get_response(path, scope)
        except HTTPException as exc:
            # `path` is OS-normalised (backslashes on Windows), so check the raw request path.
            if exc.status_code != 404 or scope["path"].startswith("/api/"):
                raise
            response = await super().get_response("index.html", scope)
        if scope["path"].startswith("/assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-cache"
        return response


def create_app(
    settings: Settings | None = None,
    *,
    frontend_dist: Path | None = None,
    run_collector: bool = True,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if not logging.getLogger().handlers:
            logging.basicConfig(
                level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
            )
            # One line per salt-api request is noise; failures are logged by the collector.
            logging.getLogger("httpx").setLevel(logging.WARNING)
        runtime = await Runtime.start(settings or load_config(), run_collector=run_collector)
        if run_collector:
            runtime.background(catchup.run_forever(runtime), "catch-up")
            runtime.background(retention.run_forever(runtime), "retention")
            runtime.background(orchestrations.keep_warm(runtime), "orchestrations")
        app.state.runtime = runtime
        try:
            yield
        finally:
            await runtime.stop()

    app = FastAPI(title="brine", version=_app_version(), lifespan=lifespan)
    app.add_middleware(LazySessionMiddleware)

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Any) -> Response:
        response: Response = await call_next(request)
        # Never inside another site's frame (clickjacking: the Run page is one click from a
        # command), no MIME sniffing, and no full URLs leaking to other sites.
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Content-Security-Policy", "frame-ancestors 'none'")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response

    @app.get("/api/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "version": app.version}

    app.include_router(api_router)

    dist = frontend_dist or FRONTEND_DIST
    if (dist / "index.html").is_file():
        app.mount("/", SPAStaticFiles(directory=dist, html=True), name="frontend")

    return app

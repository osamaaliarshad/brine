"""FastAPI entrypoint: JSON API under /api, and the built frontend for everything else."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.types import Scope

from app.api import api_router
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
    """Static files that fall back to index.html, so client-side routes survive a reload."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            # `path` is OS-normalised (backslashes on Windows), so check the raw request path.
            if exc.status_code != 404 or scope["path"].startswith("/api/"):
                raise
            return await super().get_response("index.html", scope)


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
        app.state.runtime = runtime
        try:
            yield
        finally:
            await runtime.stop()

    app = FastAPI(title="brine", version=_app_version(), lifespan=lifespan)
    app.add_middleware(LazySessionMiddleware)

    @app.get("/api/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "version": app.version}

    app.include_router(api_router)

    dist = frontend_dist or FRONTEND_DIST
    if (dist / "index.html").is_file():
        app.mount("/", SPAStaticFiles(directory=dist, html=True), name="frontend")

    return app

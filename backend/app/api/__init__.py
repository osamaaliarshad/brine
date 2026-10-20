"""REST and SSE endpoints, all under /api.

Phase 2 adds authentication as a dependency on `api_router`, which covers every route here.
"""

from fastapi import APIRouter

from app.api import (
    automation,
    events,
    fleet,
    issues,
    jobs,
    live,
    nodegroups,
    statefiles,
    system,
)

api_router = APIRouter(prefix="/api")
api_router.include_router(automation.router, tags=["automation"])
api_router.include_router(events.router, tags=["events"])
api_router.include_router(fleet.router, tags=["fleet"])
api_router.include_router(issues.router, tags=["issues"])
api_router.include_router(jobs.router, tags=["jobs"])
api_router.include_router(live.router, tags=["live"])
api_router.include_router(nodegroups.router, tags=["nodegroups"])
api_router.include_router(statefiles.router, tags=["states"])
api_router.include_router(system.router, tags=["system"])

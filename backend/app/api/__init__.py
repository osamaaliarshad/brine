"""REST and SSE endpoints, all under /api.

Everything requires a signed-in user except /api/auth/* (signing in) and /api/healthz.
Endpoints that need more than viewing add `require_role(...)` themselves. Every write
(POST, PUT, PATCH, DELETE) needs the CSRF header, signing out included.
"""

from fastapi import APIRouter, Depends

from app.api import (
    audit,
    auth,
    automation,
    commands,
    events,
    fleet,
    issues,
    jobs,
    keys,
    live,
    nodegroups,
    statefiles,
    system,
)
from app.auth.csrf import require_csrf_header
from app.auth.users import current_user

protected = APIRouter(dependencies=[Depends(current_user)])
protected.include_router(audit.router, tags=["audit"])
protected.include_router(automation.router, tags=["automation"])
protected.include_router(commands.router, tags=["commands"])
protected.include_router(events.router, tags=["events"])
protected.include_router(fleet.router, tags=["fleet"])
protected.include_router(issues.router, tags=["issues"])
protected.include_router(jobs.router, tags=["jobs"])
protected.include_router(keys.router, tags=["keys"])
protected.include_router(live.router, tags=["live"])
protected.include_router(nodegroups.router, tags=["nodegroups"])
protected.include_router(statefiles.router, tags=["states"])
protected.include_router(system.router, tags=["system"])

api_router = APIRouter(prefix="/api", dependencies=[Depends(require_csrf_header)])
api_router.include_router(auth.router)
api_router.include_router(protected)

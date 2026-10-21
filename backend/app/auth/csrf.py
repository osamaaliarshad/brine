"""Cross-site request forgery: every write must carry a header plain forms and links can't set.

Another site can only add a custom header after a CORS preflight, which brine never grants, so a
write that has it came from brine's own pages. The SameSite=Lax session cookie already blocks
most cross-site writes; this covers the rest (older browsers, sibling subdomains). Reads that
another site sends someone to (a link, an image) are refused using the browser's
Sec-Fetch-Site header.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

CSRF_HEADER = "X-Requested-With"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# The sign-in provider sends people back here from its own site.
CROSS_SITE_OK = frozenset({"/api/auth/callback"})


async def require_csrf_header(request: Request) -> None:
    if request.method not in SAFE_METHODS and not request.headers.get(CSRF_HEADER):
        raise HTTPException(403, f"writes need the {CSRF_HEADER} header")
    # Some reads do work too (ask minions live, run state.show_top, write an audit entry).
    # Browsers say where a request comes from: refuse reads another site sent someone to.
    if (
        request.headers.get("sec-fetch-site") == "cross-site"
        and request.url.path not in CROSS_SITE_OK
    ):
        raise HTTPException(403, "brine's API doesn't answer requests from other sites")

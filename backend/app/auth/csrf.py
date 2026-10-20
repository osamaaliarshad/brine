"""Cross-site request forgery: every write must carry a header plain forms and links can't set.

Another site can only add a custom header after a CORS preflight, which brine never grants, so a
write that has it came from brine's own pages. The SameSite=Lax session cookie already blocks
most cross-site writes; this covers the rest (older browsers, sibling subdomains).
"""

from __future__ import annotations

from fastapi import HTTPException, Request

CSRF_HEADER = "X-Requested-With"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


async def require_csrf_header(request: Request) -> None:
    if request.method not in SAFE_METHODS and not request.headers.get(CSRF_HEADER):
        raise HTTPException(403, f"writes need the {CSRF_HEADER} header")

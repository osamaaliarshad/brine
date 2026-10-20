"""The OpenID Connect client (Authlib), and what brine needs from it.

Tests swap in a fake with the same two methods, so the flow is testable without a real
identity provider.
"""

from __future__ import annotations

from typing import Any, Protocol

from authlib.integrations.starlette_client import OAuth
from starlette.requests import Request
from starlette.responses import Response

from app.config import AuthConfig

KNOWN_ISSUERS = {
    "accounts.google.com": "Google",
    "login.microsoftonline.com": "Microsoft",
    "okta.com": "Okta",
    "auth0.com": "Auth0",
}


class OidcClient(Protocol):
    async def authorize_redirect(self, request: Request, redirect_uri: str) -> Response: ...
    async def authorize_access_token(self, request: Request) -> dict[str, Any]: ...


def make_oidc_client(auth: AuthConfig) -> OidcClient | None:
    if auth.provider != "oidc" or not auth.issuer or not auth.client_id or not auth.client_secret:
        return None
    oauth = OAuth()
    issuer = str(auth.issuer).rstrip("/")
    client: OidcClient = oauth.register(
        "oidc",
        client_id=auth.client_id,
        client_secret=auth.client_secret.get_secret_value(),
        server_metadata_url=f"{issuer}/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )
    return client


def provider_name(auth: AuthConfig) -> str:
    """What the sign-in button calls the provider: configured, recognised, or its host."""
    if auth.display_name:
        return auth.display_name
    host = auth.issuer.host if auth.issuer else None
    if not host:
        return "single sign-on"
    for known, name in KNOWN_ISSUERS.items():
        if host == known or host.endswith(f".{known}"):
            return name
    return host

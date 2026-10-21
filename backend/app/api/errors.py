"""salt-api failures as HTTP errors people can act on."""

from __future__ import annotations

from fastapi import HTTPException

from app.salt.client import SaltApiError, SaltApiForbidden


def salt_http_error(exc: SaltApiError) -> HTTPException:
    if isinstance(exc, SaltApiForbidden):
        return HTTPException(
            403,
            f"{exc}. Add it to external_auth for that account "
            "(see docs/permissions-and-salt-acl.md).",
        )
    return HTTPException(502, f"salt-api: {exc}")

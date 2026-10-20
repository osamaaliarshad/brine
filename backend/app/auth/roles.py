"""Who gets which role: email patterns from the config, highest match wins."""

from __future__ import annotations

from fnmatch import fnmatchcase

from app.config import AuthConfig, Role, RolesConfig

ROLE_ORDER: tuple[Role, ...] = ("viewer", "operator", "admin")


def role_for(email: str, roles: RolesConfig, auth: AuthConfig) -> Role | None:
    """The highest role whose patterns match `email`, or None (not allowed in).

    `auth.allowed_domains`, when set, is checked first: other domains never get in, whatever
    the role patterns say.
    """
    email = email.strip().lower()
    if "@" not in email:
        return None
    domain = email.rsplit("@", 1)[1]
    if auth.allowed_domains and domain not in {d.lower() for d in auth.allowed_domains}:
        return None
    for role in reversed(ROLE_ORDER):
        if any(fnmatchcase(email, pattern.lower()) for pattern in getattr(roles, role)):
            return role
    return None


def at_least(role: Role, needed: Role) -> bool:
    return ROLE_ORDER.index(role) >= ROLE_ORDER.index(needed)

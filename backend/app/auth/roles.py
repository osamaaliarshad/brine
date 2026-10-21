"""Who gets which role: email patterns from the config, highest match wins."""

from __future__ import annotations

from fnmatch import fnmatchcase

from app.config import AuthConfig, Role, RolesConfig, Settings

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


def current_role(email: str, settings: Settings) -> Role | None:
    """The role `email` has under the running config (everyone's the anonymous role when
    sign-in is off). For acting later on someone's behalf, e.g. a catch-up run."""
    if settings.auth.provider == "none":
        return settings.auth.anonymous_role
    return role_for(email, settings.roles, settings.auth)


def at_least(role: Role, needed: Role) -> bool:
    return ROLE_ORDER.index(role) >= ROLE_ORDER.index(needed)

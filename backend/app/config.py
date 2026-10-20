"""Configuration: one YAML file, with secrets pulled from the environment.

Two ways to get values in from the environment:

* ``${VAR}`` / ``${VAR:-default}`` placeholders anywhere in the YAML, expanded before parsing.
* ``BRINE__SECTION__KEY=value`` variables, which override (or add) a single nested key
  after parsing, e.g. ``BRINE__SALT_API__PASSWORD``.

The file path comes from ``BRINE_CONFIG`` (default ``config.yaml``).
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, SecretStr, ValidationError

ENV_PREFIX = "BRINE__"
CONFIG_PATH_VAR = "BRINE_CONFIG"
_PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


class ConfigError(Exception):
    """Raised when the config file is missing, malformed, or invalid."""


class _Strict(BaseModel):
    # Reject unknown keys so a typo in config.yaml fails loudly instead of being ignored.
    model_config = ConfigDict(extra="forbid", frozen=True)


class SaltApiConfig(_Strict):
    url: HttpUrl
    username: str
    password: SecretStr
    eauth: str = "pam"
    verify_tls: bool = True
    timeout_seconds: float = Field(default=10.0, gt=0)


class AuthConfig(_Strict):
    provider: Literal["oidc"] = "oidc"
    issuer: HttpUrl | None = None
    client_id: str | None = None
    client_secret: SecretStr | None = None
    allowed_domains: list[str] = Field(default_factory=list)


class RolesConfig(_Strict):
    """Email patterns (fnmatch-style, e.g. ``*@example.com``) granted each role."""

    viewer: list[str] = Field(default_factory=list)
    operator: list[str] = Field(default_factory=list)
    admin: list[str] = Field(default_factory=list)


class GrainColumn(_Strict):
    grain: str
    label: str | None = None


class FleetConfig(_Strict):
    columns: list[GrainColumn] = Field(default_factory=list)
    stale_after_minutes: int = Field(default=15, ge=1)


class Settings(_Strict):
    salt_api: SaltApiConfig
    auth: AuthConfig = Field(default_factory=AuthConfig)
    roles: RolesConfig = Field(default_factory=RolesConfig)
    fleet: FleetConfig = Field(default_factory=FleetConfig)
    database: str = "sqlite:///data/brine.db"


def expand_placeholders(data: Any, env: Mapping[str, str]) -> Any:
    """Replace ``${VAR}`` and ``${VAR:-default}`` in every string value of parsed YAML.

    Runs after parsing, so comments are left alone and env values can't alter YAML structure.
    """
    missing: list[str] = []

    def repl(match: re.Match[str]) -> str:
        name, default = match.group(1), match.group(2)
        if name in env:
            return env[name]
        if default is not None:
            return default
        missing.append(name)
        return ""

    def walk(node: Any) -> Any:
        if isinstance(node, str):
            return _PLACEHOLDER.sub(repl, node)
        if isinstance(node, dict):
            return {key: walk(value) for key, value in node.items()}
        if isinstance(node, list):
            return [walk(item) for item in node]
        return node

    expanded = walk(data)
    if missing:
        raise ConfigError(f"environment variable(s) not set: {', '.join(sorted(set(missing)))}")
    return expanded


def apply_env_overrides(data: dict[str, Any], env: Mapping[str, str]) -> dict[str, Any]:
    """Apply ``BRINE__A__B=value`` variables as ``data["a"]["b"] = value``."""
    for key, value in env.items():
        if not key.startswith(ENV_PREFIX):
            continue
        path = [part.lower() for part in key[len(ENV_PREFIX) :].split("__") if part]
        if not path:
            continue
        node = data
        for part in path[:-1]:
            child = node.get(part)
            if not isinstance(child, dict):
                child = {}
                node[part] = child
            node = child
        # Parse as YAML so `true`, `15` and `[a, b]` get their natural types.
        node[path[-1]] = yaml.safe_load(value) if value else value
    return data


def parse_config(text: str, env: Mapping[str, str]) -> Settings:
    """Build validated settings from YAML text and an environment mapping."""
    try:
        raw = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError("config must be a YAML mapping at the top level")
    try:
        return Settings.model_validate(apply_env_overrides(expand_placeholders(raw, env), env))
    except ValidationError as exc:
        raise ConfigError(str(exc)) from exc


def load_config(path: Path | None = None, env: Mapping[str, str] | None = None) -> Settings:
    """Load settings from ``path`` (or ``$BRINE_CONFIG``, or ``config.yaml``)."""
    env = os.environ if env is None else env
    path = path or Path(env.get(CONFIG_PATH_VAR, "config.yaml"))
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigError(
            f"config file not found: {path} (set {CONFIG_PATH_VAR} or copy config.example.yaml)"
        ) from exc
    return parse_config(text, env)

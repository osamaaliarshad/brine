"""Configuration: one YAML file, with secrets pulled from the environment.

Two ways to get values in from the environment:

* ``${VAR}`` / ``${VAR:-default}`` placeholders anywhere in the YAML except check commands,
  expanded before parsing.
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
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)

ENV_PREFIX = "BRINE__"
CONFIG_PATH_VAR = "BRINE_CONFIG"
_PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")
# Where placeholders are left as written: each check's command.
_LITERAL = {("inventory", "checks")}


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


Role = Literal["viewer", "operator", "admin"]


class AuthConfig(_Strict):
    """Sign-in. ``oidc`` (any OpenID Connect provider) is the default and must be configured;
    ``none`` turns sign-in off and treats every visitor as ``anonymous_role``: for the demo
    fleet or a laptop only, and brine says so on every page."""

    provider: Literal["oidc", "none"] = "oidc"
    issuer: HttpUrl | None = None
    client_id: str | None = None
    client_secret: SecretStr | None = None
    # What the sign-in button says, e.g. "Google". Derived from the issuer when unset.
    display_name: str | None = None
    # If set, only these email domains can sign in at all (checked before roles).
    allowed_domains: list[str] = Field(default_factory=list)
    # Sign-in needs the provider to say the email is verified. Microsoft Entra never says so;
    # with a single-tenant Entra app (see docs/oidc-providers.md), set this to false.
    require_verified_email: bool = True
    anonymous_role: Role = "viewer"
    session_hours: int = Field(default=12, ge=1, le=24 * 30)
    # Signs session cookies. If unset, brine generates one and keeps it in its database.
    session_secret: SecretStr | None = None

    @model_validator(mode="after")
    def _oidc_is_complete(self) -> AuthConfig:
        if self.provider == "oidc" and not (self.issuer and self.client_id and self.client_secret):
            raise ValueError(
                "sign-in is not configured: set auth.issuer, auth.client_id and "
                "auth.client_secret (see docs/oidc-providers.md), or set auth.provider: none "
                "to run without sign-in (demo or local use only)"
            )
        return self


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
    # Without a presence observation this recent, statuses are shown as stale.
    stale_after_minutes: int = Field(default=15, ge=1)
    # How often grains are re-collected from connected minions.
    grains_refresh_minutes: int = Field(default=30, ge=1)


class PresenceConfig(_Strict):
    """How brine learns who is online. See docs/presence-and-status.md.

    * ``events``: listen for ``salt/presence/*`` (needs ``presence_events: True`` on the master).
    * ``connected``: poll ``wheel minions.connected`` (cheap, same detection as presence events).
    * ``ping``: poll ``runner manage.status`` (pings every minion; works through NAT).
    * ``auto``: ``events`` if the master sends them, otherwise ``connected``.
    """

    method: Literal["auto", "events", "connected", "ping"] = "auto"
    poll_seconds: int = Field(default=60, ge=5)


class CommandsConfig(_Strict):
    """Salt functions each role may run from brine's command box (fnmatch patterns, e.g.
    ``test.*``). Master-side functions carry their client: ``runners.jobs.list_jobs``,
    ``wheel.key.list_all``. Viewers never run commands. brine's Salt account's external_auth
    still limits everything, admins included."""

    operator: list[str] = Field(default_factory=list)
    admin: list[str] = Field(default_factory=lambda: ["*"])
    # Catch-up runs (opted into per run): how long a command waits for an offline minion.
    catch_up_days: int = Field(default=7, ge=1, le=90)


class TemplateConfig(_Strict):
    """A command people can pick on the Run page. Same fields as SaltGUI's
    `saltgui_templates`, which brine also reads from the master config."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    description: str = ""
    target: str = ""
    # SaltGUI spells it `targettype`; both work.
    target_type: Literal["glob", "list", "compound", "grain", "nodegroup", "pcre"] = Field(
        default="glob", alias="targettype"
    )
    command: str = ""  # a template may only fill in the target
    category: str | None = None
    categories: list[str] = Field(default_factory=list)


class RetentionConfig(_Strict):
    """How long brine keeps history, in days. 0 keeps it forever."""

    jobs_days: int = Field(default=90, ge=0)  # jobs, their returns, finished catch-up runs
    # presence changes, grains history, package and check changes, issues marked as read
    history_days: int = Field(default=90, ge=0)
    audit_days: int = Field(default=365, ge=0)


# Up to 64 characters: the size of the `source` column in the inventory tables.
_CHECK_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
# A first argument like `NAME=value`: the minion reads it as a keyword argument, not a command.
_LEADING_KWARG = re.compile(r"[^\d\W][\w.-]*=")


class InventoryConfig(_Strict):
    """Packages and checks: what brine reads from each minion and keeps over time."""

    # How often each connected minion is read again (also after jobs that may change software,
    # and on Read now). From every 15 minutes to once a month.
    refresh_hours: float = Field(default=6, ge=0.25, le=24 * 30)
    # name -> a read-only shell command, on one line, run with cmd.run_all. `name=value` lines
    # become one entry each; any other output is one value. Print nothing when the thing isn't
    # there. Commands are taken literally, with no ${VAR} filled in: the minion's shell runs
    # them as written. Every signed-in role sees them in Settings, and their output in the
    # explorer, so keep secrets out of them.
    checks: dict[str, str] = Field(default_factory=dict)

    @field_validator("checks")
    @classmethod
    def _checks(cls, checks: dict[str, str]) -> dict[str, str]:
        cleaned: dict[str, str] = {}
        named: dict[str, str] = {}  # command -> the check that runs it
        for name, command in checks.items():
            if name == "packages" or not _CHECK_NAME.fullmatch(name):
                raise ValueError(
                    f"check name {name!r}: use lowercase letters, digits, - and _ "
                    "(and not 'packages')"
                )
            # Strip, so the newline a YAML `|` block leaves at the end doesn't count.
            command = command.strip()
            if not command:
                raise ValueError(f"check {name!r} has no command")
            if "\n" in command or "\r" in command:
                raise ValueError(f"check {name!r}: put the command on one line")
            # Tabs are fine; other control characters would break the ACL brine suggests.
            bad = next((c for c in command if c != "\t" and not c.isprintable()), None)
            if bad is not None:
                raise ValueError(
                    f"check {name!r}: the command has characters that can't be used "
                    f"(the first is U+{ord(bad):04X})"
                )
            if _LEADING_KWARG.match(command):
                raise ValueError(
                    f"check {name!r}: Salt reads a leading NAME=value as an option; start the "
                    "command with env, e.g. env LC_ALL=C dpkg-query …"
                )
            # Answers are matched to checks by their command, so each needs its own.
            if command in named:
                raise ValueError(f"checks {named[command]!r} and {name!r} run the same command")
            named[command] = name
            cleaned[name] = command
        return cleaned


class JobsConfig(_Strict):
    # On (re)connect, import up to this many jobs from the master's job cache.
    backfill_limit: int = Field(default=200, ge=0)


class Settings(_Strict):
    salt_api: SaltApiConfig
    auth: AuthConfig = Field(default_factory=AuthConfig)
    roles: RolesConfig = Field(default_factory=RolesConfig)
    fleet: FleetConfig = Field(default_factory=FleetConfig)
    presence: PresenceConfig = Field(default_factory=PresenceConfig)
    commands: CommandsConfig = Field(default_factory=CommandsConfig)
    templates: dict[str, TemplateConfig] = Field(default_factory=dict)
    retention: RetentionConfig = Field(default_factory=RetentionConfig)
    inventory: InventoryConfig = Field(default_factory=InventoryConfig)
    jobs: JobsConfig = Field(default_factory=JobsConfig)
    database: str = "sqlite:///data/brine.db"
    # How browsers reach brine, e.g. https://brine.example.com. Used for the sign-in redirect;
    # when unset, it's taken from each request (fine locally, or behind a proxy that forwards
    # the Host header).
    public_url: HttpUrl | None = None


def expand_placeholders(data: Any, env: Mapping[str, str]) -> Any:
    """Replace ``${VAR}`` and ``${VAR:-default}`` in every string value of parsed YAML except
    check commands, which are taken literally (see InventoryConfig.checks).

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

    def walk(node: Any, path: tuple[str, ...]) -> Any:
        if path in _LITERAL:
            return node
        if isinstance(node, str):
            return _PLACEHOLDER.sub(repl, node)
        if isinstance(node, dict):
            return {key: walk(value, (*path, str(key))) for key, value in node.items()}
        if isinstance(node, list):
            return [walk(item, path) for item in node]
        return node

    expanded = walk(data, ())
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

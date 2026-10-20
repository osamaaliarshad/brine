"""The command box: parsing what people type, and who may run what.

A command reads like the salt CLI after the target: ``state.apply webserver test=True``. It's
split like a shell would (quotes group words) and the words are sent to Salt as-is, so Salt
parses ``key=value`` and YAML values exactly as it does for ``salt`` on the master.
``runners.<fun>`` and ``wheel.<fun>`` run on the master instead, as in SaltGUI.

Jobs brine starts for someone carry ``metadata: {"brine": {"actor": <email>}}``. Salt copies
that into every return and into its job cache, so brine records them under the person, not
under its own service account (whose jobs are otherwise housekeeping).
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from typing import Any, Literal

from app.config import CommandsConfig

Client = Literal["local", "runner", "wheel"]

# The prefix that picks a master-side client, and how it's written in allowlists.
CLIENT_PREFIXES: dict[str, Client] = {"runners.": "runner", "runner.": "runner", "wheel.": "wheel"}
QUALIFIED_PREFIX: dict[Client, str] = {"local": "", "runner": "runners.", "wheel": "wheel."}


class CommandError(ValueError):
    """The command can't be run as typed; the message says why, for the person."""


@dataclass(frozen=True)
class Command:
    client: Client
    fun: str  # without the client prefix: test.ping, jobs.list_jobs
    args: list[str] = field(default_factory=list)  # words after the function, as typed

    @property
    def qualified(self) -> str:
        """How allowlists and the audit log name it: test.ping, runners.jobs.list_jobs."""
        return QUALIFIED_PREFIX[self.client] + self.fun


def parse_command(text: str) -> Command:
    try:
        words = shlex.split(text)
    except ValueError as exc:  # "No closing quotation"
        raise CommandError(f"Can't read that command: {exc}.") from exc
    if not words:
        raise CommandError("Type a Salt function to run, like test.ping.")
    first, args = words[0], words[1:]
    client: Client = "local"
    for prefix, prefix_client in CLIENT_PREFIXES.items():
        if first.startswith(prefix):
            client, first = prefix_client, first.removeprefix(prefix)
            break
    module, dot, name = first.partition(".")
    if not (module and dot and name) or not all(
        part.replace("_", "").isalnum() for part in first.split(".")
    ):
        raise CommandError(f"{words[0]!r} isn't a Salt function name, like test.ping.")
    return Command(client=client, fun=first, args=args)


def allowed_patterns(role: str, config: CommandsConfig) -> list[str]:
    """What this role may run. Higher roles also get everything lower roles may run."""
    if role == "admin":
        return [*config.admin, *config.operator]
    if role == "operator":
        return list(config.operator)
    return []


def is_allowed(command: Command, patterns: list[str]) -> bool:
    return any(fnmatchcase(command.qualified, pattern) for pattern in patterns)


def command_metadata(actor: str) -> dict[str, Any]:
    return {"brine": {"actor": actor}}


def actor_of(metadata: Any) -> str | None:
    """Who asked brine to run a job, from the job's Salt metadata (None if brine didn't)."""
    brine = metadata.get("brine") if isinstance(metadata, dict) else None
    actor = brine.get("actor") if isinstance(brine, dict) else None
    return actor if isinstance(actor, str) and actor else None

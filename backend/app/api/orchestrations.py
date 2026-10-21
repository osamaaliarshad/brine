"""Orchestrations: SLS files on the master whose steps run Salt commands (salt.state,
salt.function, salt.runner, salt.wheel), shown step by step like SaltGUI's Orchestrations page.

Salt doesn't mark orchestration files as such, so brine reads the .sls files, keeps the ones with
orchestration steps, and has the master render those (`state.orchestrate_show_sls`), so Jinja
and includes work. Running one goes through the Run page like any other command.

Many orchestrations read their inputs from pillar given at run time (a reactor's
`pillar: {minion_id: ...}`). brine finds the keys they read, renders them with placeholders such
as `<minion_id>` so their steps still show, and the Run page asks for the real values.
The listing is kept for a minute: reading every .sls file through salt-api takes a while.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import RuntimeDep
from app.api.schemas import (
    Orchestration,
    OrchestrationInput,
    Orchestrations,
    OrchestrationStep,
)
from app.api.statefiles import walk_files
from app.auth.users import CurrentUser
from app.commands import CommandError, allowed_patterns, is_allowed, parse_command
from app.runtime import Runtime
from app.salt.client import SaltApiError, SaltApiForbidden

router = APIRouter()

ORCHESTRATION_STEP = re.compile(
    r"^\s*-?\s*salt\.(state|function|runner|wheel|parallel_runners)\s*:", re.MULTILINE
)
MAX_FILES = 300  # .sls files read per listing
PARALLEL_READS = 4
# Step arguments shown in their own columns; everything else goes in the details.
REQUISITES = ("require", "watch", "onchanges", "onfail", "prereq", "listen")
# Pillar an orchestration reads: pillar['key'] must be given to render it at all;
# pillar.get('key') and salt['pillar.get']('key') have defaults.
REQUIRED_PILLAR = re.compile(r"""\bpillar\s*\[\s*['"]([A-Za-z_][\w-]*)['"]\s*\]""")
OPTIONAL_PILLAR = re.compile(
    r"""(?:\bpillar\.get|\bsalt\s*\[\s*['"]pillar\.get['"]\s*\])\s*\(\s*['"]([A-Za-z_][\w-]*)"""
)
LISTING_SECONDS = 60
SALTENV = re.compile(r"[\w.-]{1,64}")


def pillar_inputs(text: str) -> list[OrchestrationInput]:
    required = list(dict.fromkeys(REQUIRED_PILLAR.findall(text)))
    optional = [k for k in dict.fromkeys(OPTIONAL_PILLAR.findall(text)) if k not in required]
    return [OrchestrationInput(name=k, required=True) for k in required] + [
        OrchestrationInput(name=k, required=False) for k in optional
    ]


def sls_name(path: str) -> str:
    """orch/rollout.sls -> orch.rollout; orch/init.sls -> orch."""
    name = path.removesuffix(".sls").replace("/", ".")
    return name.removesuffix(".init")


def _requisites(args: dict[str, Any]) -> list[str]:
    needs: list[str] = []
    for kind in REQUISITES:
        for entry in args.pop(kind, None) or []:
            ids = entry.values() if isinstance(entry, dict) else [entry]
            needs.extend(f"{kind} {i}" if kind != "require" else str(i) for i in ids)
    return needs


def parse_steps(rendered: Any) -> tuple[list[OrchestrationStep], str | None]:
    """Steps in run order from `state.orchestrate_show_sls`, or the render error."""
    if isinstance(rendered, list):  # Salt reports render errors as a list of strings
        return [], "\n".join(str(e) for e in rendered)
    if not isinstance(rendered, dict) or len(rendered) != 1:
        return [], "The master's answer wasn't an orchestration."
    (high,) = rendered.values()
    if isinstance(high, list):
        return [], "\n".join(str(e) for e in high)
    steps: list[tuple[float, OrchestrationStep]] = []
    for step_id, body in (high or {}).items():
        if not isinstance(body, dict):
            continue
        for module, chunks in body.items():
            if module.startswith("__") or not isinstance(chunks, list):
                continue
            fun = next((c for c in chunks if isinstance(c, str)), "")
            args: dict[str, Any] = {}
            for chunk in chunks:
                if isinstance(chunk, dict):
                    args.update(chunk)
            order = args.pop("order", 0)
            target = args.pop("tgt", None)
            target_type = args.pop("tgt_type", None)
            if fun == "state":
                what = str(args.pop("sls", "")) or (
                    "highstate" if args.pop("highstate", None) else ""
                )
            else:
                what = str(args.pop("name", step_id))
            steps.append(
                (
                    order if isinstance(order, int | float) else 0,
                    OrchestrationStep(
                        id=str(step_id),
                        function=f"{module}.{fun}",
                        what=what,
                        target=None if target is None else str(target),
                        target_type=None if target_type is None else str(target_type),
                        needs=_requisites(args),
                        details=args,
                    ),
                )
            )
    return [step for _, step in sorted(steps, key=lambda s: s[0])], None


async def _read(runtime: Runtime, path: str, saltenv: str, gate: asyncio.Semaphore) -> str:
    async with gate:
        result = await runtime.client.wheel("file_roots.read", path=path, saltenv=saltenv)
    entries = [e for e in result if isinstance(e, dict)] if isinstance(result, list) else []
    return str(next(iter(entries[0].values()))) if entries else ""


async def _discover(runtime: Runtime, saltenv: str) -> tuple[list[Orchestration], bool]:
    """(orchestrations, whether there were more .sls files than brine reads)."""
    roots = await runtime.client.wheel("file_roots.list_env", saltenv=saltenv)
    paths = sorted(
        {path for tree in (roots or {}).values() for path in walk_files(tree)},
        key=lambda p: (p.count("/"), p),
    )
    sls = [p for p in paths if p.endswith(".sls") and p != "top.sls"]
    gate = asyncio.Semaphore(PARALLEL_READS)
    contents = await asyncio.gather(*(_read(runtime, p, saltenv, gate) for p in sls[:MAX_FILES]))
    found: list[Orchestration] = []
    for path, text in zip(sls, contents, strict=False):
        if not ORCHESTRATION_STEP.search(text):
            continue
        inputs = pillar_inputs(text)
        placeholders = {i.name: f"<{i.name}>" for i in inputs if i.required}
        rendered = await runtime.client.runner(
            "state.orchestrate_show_sls",
            mods=sls_name(path),
            saltenv=saltenv,
            **({"pillar": placeholders} if placeholders else {}),
        )
        steps, error = parse_steps(rendered)
        found.append(
            Orchestration(sls=sls_name(path), path=path, steps=steps, error=error, inputs=inputs)
        )
    return found, len(sls) > MAX_FILES


@router.get("/orchestrations", response_model=Orchestrations)
async def orchestrations(
    runtime: RuntimeDep,
    user: CurrentUser,
    saltenv: str = Query("base"),
    refresh: bool = Query(False, description="read the master again, not the last minute's"),
) -> Orchestrations:
    if refresh and user.role == "viewer":
        raise HTTPException(403, "Reading the master again needs the operator role.")
    if not SALTENV.fullmatch(saltenv):
        raise HTTPException(422, "That isn't a saltenv name.")
    key = f"orchestrations:{saltenv}"
    cached = runtime.memo.get(key)
    try:
        if cached and not refresh and time.monotonic() - cached[0] < LISTING_SECONDS:
            found, truncated = cached[1]
        else:
            found, truncated = await _discover(runtime, saltenv)
            runtime.memo[key] = (time.monotonic(), (found, truncated))
    except SaltApiForbidden as exc:
        raise HTTPException(
            403,
            f"{exc}. Add it to external_auth for that account "
            "(see docs/permissions-and-salt-acl.md).",
        ) from exc
    except SaltApiError as exc:
        raise HTTPException(502, f"salt-api: {exc}") from exc

    patterns = allowed_patterns(user.role, runtime.settings.commands)
    try:
        can_run = is_allowed(parse_command("runners.state.orchestrate x"), patterns)
    except CommandError:
        can_run = False
    return Orchestrations(
        saltenv=saltenv, orchestrations=found, truncated=truncated, can_run=can_run
    )

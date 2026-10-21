"""States on the master: which minions get which SLS (the top file), and the files themselves."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import RuntimeDep, SessionDep
from app.api.fleet import reachable
from app.api.schemas import StateFile, StateFileContent, StateTop
from app.salt.client import SaltApiError

router = APIRouter()

TOP_TIMEOUT_SECONDS = 15
MAX_FILE_CHARS = 512_000


def walk_files(tree: Any, prefix: str = "") -> list[str]:
    """`file_roots.list_env` nests directories as dicts and marks files with "f"."""
    files: list[str] = []
    for name, node in (tree or {}).items():
        path = f"{prefix}{name}"
        if isinstance(node, dict):
            files.extend(walk_files(node, f"{path}/"))
        else:
            files.append(path)
    return files


@router.get("/states/top", response_model=StateTop)
async def state_top(runtime: RuntimeDep, session: SessionDep) -> StateTop:
    """Each minion's states per environment, from `state.show_top` (asked live)."""
    ask, skipped = await reachable(runtime, session)
    try:
        result = (
            await runtime.client.local(
                ",".join(ask), "state.show_top", tgt_type="list", salt_timeout=TOP_TIMEOUT_SECONDS
            )
            if ask
            else {}
        )
    except SaltApiError as exc:
        raise HTTPException(502, f"salt-api: {exc}") from exc
    minions = {
        mid: {env: [str(s) for s in sls] for env, sls in top.items() if isinstance(sls, list)}
        for mid, top in sorted(result.items())
        if isinstance(top, dict)
    }
    return StateTop(
        fetched_at=datetime.now(UTC),
        minions=minions,
        missing=[m for m in ask if m not in minions],
        skipped=skipped,
    )


@router.get("/states/files", response_model=list[StateFile])
async def state_files(runtime: RuntimeDep, saltenv: str = Query("base")) -> list[StateFile]:
    try:
        roots = await runtime.client.wheel("file_roots.list_env", saltenv=saltenv)
    except SaltApiError as exc:
        raise HTTPException(502, f"salt-api: {exc}") from exc
    files = [
        StateFile(root=str(root), path=path)
        for root, tree in (roots or {}).items()
        for path in walk_files(tree)
    ]
    return sorted(files, key=lambda f: (f.path.count("/"), f.path))


@router.get("/states/file", response_model=StateFileContent)
async def state_file(
    runtime: RuntimeDep,
    path: str = Query(..., min_length=1),
    saltenv: str = Query("base"),
) -> StateFileContent:
    if path.startswith(("/", "\\")) or ".." in path.replace("\\", "/").split("/"):
        raise HTTPException(400, "path must be relative to the file roots")
    try:
        result = await runtime.client.wheel("file_roots.read", path=path, saltenv=saltenv)
    except SaltApiError as exc:
        raise HTTPException(502, f"salt-api: {exc}") from exc
    entries = [e for e in result if isinstance(e, dict)] if isinstance(result, list) else []
    if not entries:
        raise HTTPException(404, f"no file {path!r} in {saltenv}")
    full_path, content = next(iter(entries[0].items()))
    text = str(content)
    return StateFileContent(
        path=path,
        full_path=str(full_path),
        content=text[:MAX_FILE_CHARS],
        truncated=len(text) > MAX_FILE_CHARS,
    )

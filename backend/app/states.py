"""Make sense of Salt state output (state.apply / state.highstate / state.sls returns)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

STATE_FUNCTIONS = frozenset(
    {"state.apply", "state.highstate", "state.sls", "state.sls_id", "state.single"}
)


class StateResult(BaseModel):
    id: str  # the state ID from the SLS
    name: str
    function: str  # e.g. file.managed
    sls: str | None
    result: bool | None  # None: test mode, would change
    changed: bool
    comment: str
    duration_ms: float | None


def parse_state_return(data: Any) -> list[StateResult] | None:
    """Per-state results in run order, or None if `data` isn't state output.

    A state run that failed to compile returns a list of error strings; that becomes a single
    failed pseudo-state so it's visible rather than silently skipped.
    """
    if isinstance(data, list) and data and all(isinstance(e, str) for e in data):
        return [
            StateResult(
                id="(compile)",
                name="(compile)",
                function="",
                sls=None,
                result=False,
                changed=False,
                comment="\n".join(data),
                duration_ms=None,
            )
        ]
    if not isinstance(data, dict) or not data:
        return None
    states: list[tuple[int, StateResult]] = []
    for key, value in data.items():
        # Keys look like "file_|-/etc/motd_|-/etc/motd_|-managed".
        parts = key.split("_|-")
        if len(parts) != 4 or not isinstance(value, dict) or "result" not in value:
            return None
        module, state_id, name, fun = parts
        duration = value.get("duration")
        states.append(
            (
                int(value.get("__run_num__", len(states))),
                StateResult(
                    id=str(value.get("__id__", state_id)),
                    name=str(value.get("name", name)),
                    function=f"{module}.{fun}",
                    sls=value.get("__sls__"),
                    result=value.get("result"),
                    changed=bool(value.get("changes")),
                    comment=str(value.get("comment", "")),
                    duration_ms=float(duration) if isinstance(duration, int | float) else None,
                ),
            )
        )
    return [state for _, state in sorted(states, key=lambda s: s[0])]

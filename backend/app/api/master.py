"""The few master settings brine reads: `reactor`, `nodegroups` and `saltgui_templates`.

`wheel config.values` returns the whole master config, which can hold secrets: only these keys
are kept, in memory for a minute (several pages ask), never stored or sent to browsers whole.
"""

from __future__ import annotations

import time
from typing import Any

from app.runtime import Runtime

KEYS = ("reactor", "nodegroups", "saltgui_templates")
KEEP_SECONDS = 60
_MEMO = "master-settings"


async def master_settings(runtime: Runtime) -> dict[str, Any]:
    cached = runtime.memo.get(_MEMO)
    if cached and time.monotonic() - cached[0] < KEEP_SECONDS:
        return dict(cached[1])
    values = await runtime.client.wheel("config.values")
    kept = {key: values.get(key) for key in KEYS} if isinstance(values, dict) else {}
    runtime.memo[_MEMO] = (time.monotonic(), kept)
    return dict(kept)

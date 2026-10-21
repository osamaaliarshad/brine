"""Pillar values stay with admins.

`pillar.obfuscate` (what brine's own Pillar tab uses) returns the structure with every value
replaced by its type. Every other pillar function (`pillar.items`, `pillar.get`, the
`pillar.show_pillar` runner, ...) returns real values, which can be passwords and keys. Run from
the salt CLI or the Run page, that output reaches brine's job history and event stream: there,
only admins see it; everyone else sees a note saying it's hidden.
"""

from __future__ import annotations

import re
from typing import Any

HIDDEN = "Hidden: this is pillar data, which can hold secrets. Only admins see it."
SAFE = frozenset({"pillar.obfuscate"})
_RETURN_TAG = re.compile(r"^salt/(job/[^/]+/ret/|run/[^/]+/ret$)")


def reveals_pillar(fun: Any) -> bool:
    """Whether a Salt function's output is real pillar data. Event `fun`s carry the client
    (`runner.pillar.show_pillar`), job records don't."""
    if not isinstance(fun, str):
        return False
    name = fun.removeprefix("runner.").removeprefix("wheel.")
    return name.startswith("pillar.") and name not in SAFE


def mask_event(entry: dict[str, Any]) -> dict[str, Any]:
    """A copy of an event-log entry with a pillar function's return hidden, if it is one."""
    data = entry.get("data")
    if not (isinstance(data, dict) and _RETURN_TAG.match(str(entry.get("tag", "")))):
        return entry
    if not reveals_pillar(data.get("fun")):
        return entry
    return {**entry, "data": {**data, "return": HIDDEN}}

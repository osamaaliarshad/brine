"""Read the service account's external_auth entries (the `perms` salt-api returns at login).

brine uses this to show only the actions Salt will actually allow; Salt still enforces the ACL
on every call. Matching follows Salt's own rules for wheel and runner functions
(`CkMinions.spec_check`): `@wheel` or `@key` allow everything in them, and
`{'@wheel': [regex, ...]}` / `{'@key': [regex, ...]}` allow the functions whose name the regex
matches from the start.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any, Literal

Form = Literal["wheel", "runner"]


def _regex_matches(pattern: str, name: str) -> bool:
    try:
        return re.match(pattern, name) is not None
    except re.error:
        return False


def _fun_allowed(spec: Any, name: str) -> bool:
    for item in spec if isinstance(spec, list) else [spec]:
        if isinstance(item, str) and _regex_matches(item, name):
            return True
        # {regex: {args: [...], kwargs: {...}}}: argument limits are left to Salt.
        if isinstance(item, dict) and len(item) == 1:
            (pattern,) = item
            if isinstance(pattern, str) and _regex_matches(pattern, name):
                return True
    return False


def allows(perms: Iterable[Any], form: Form, fun: str) -> bool:
    """Whether these external_auth entries let the account run `fun` (e.g. key.accept_dict)."""
    module, _, name = fun.partition(".")
    whole_form = {f"@{form}", f"@{form}s"}
    for entry in perms:
        if isinstance(entry, str):
            if entry in whole_form or entry == f"@{module}":
                return True
        elif isinstance(entry, dict) and len(entry) == 1:
            ((key, spec),) = entry.items()
            if key == f"@{module}" and _fun_allowed(spec, name):
                return True
            if key in whole_form and _fun_allowed(spec, fun):
                return True
    return False


def missing(perms: Iterable[Any], form: Form, funs: Iterable[str]) -> list[str]:
    entries = list(perms)
    return [fun for fun in funs if not allows(entries, form, fun)]

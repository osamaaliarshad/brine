"""Retention: brine's history is pruned once an hour, per `retention:` in the config.

Jobs (with their returns) and finished catch-up runs after `jobs_days`, presence changes and
grains history after `history_days`, the audit log after `audit_days`. 0 keeps that kind forever.
Salt keeps its own, much shorter, job cache; this only touches brine's database.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from app.runtime import Runtime

log = logging.getLogger(__name__)

PRUNE_SECONDS = 3600


def _cutoff(now: datetime, days: int) -> datetime | None:
    return now - timedelta(days=days) if days else None


async def prune(runtime: Runtime, now: datetime | None = None) -> dict[str, int]:
    now = now or datetime.now(UTC)
    keep = runtime.settings.retention
    deleted = await runtime.ingest.prune(
        jobs_before=_cutoff(now, keep.jobs_days),
        history_before=_cutoff(now, keep.history_days),
        audit_before=_cutoff(now, keep.audit_days),
    )
    if any(deleted.values()):
        log.info("pruned old history: %s", ", ".join(f"{n} {k}" for k, n in deleted.items() if n))
    return deleted


async def run_forever(runtime: Runtime) -> None:
    while True:
        try:
            await prune(runtime)
        except Exception:  # a failed prune mustn't stop the next one
            log.exception("pruning old history failed")
        await asyncio.sleep(PRUNE_SECONDS)

"""Minion status: what brine can honestly say about whether a minion is up right now.

Presence observations (a `salt/presence/present` event, or a poll) are fleet-wide: each one
says who is connected *at that moment*. A status is only "observed" while the latest
observation is recent; after that brine falls back to "last known".
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum


class Status(StrEnum):
    ONLINE = "online"  # in the latest, still-fresh presence observation
    OFFLINE = "offline"  # missing from the latest, still-fresh presence observation
    STALE = "stale"  # no fresh observation; showing the last known state
    UNKNOWN = "unknown"  # no fresh observation, and brine has never seen this minion


def minion_status(
    *,
    connected: bool,
    last_seen_at: datetime | None,
    presence_at: datetime | None,
    now: datetime,
    stale_after: timedelta,
    observable: bool = True,
) -> Status:
    """`observable=False`: presence detection can't see this minion (the master has no cached
    IP addresses for it), so being absent from a presence check proves nothing."""
    fresh = presence_at is not None and now - presence_at <= stale_after
    if fresh and connected:
        return Status.ONLINE
    if fresh and observable:
        return Status.OFFLINE
    if last_seen_at is None:
        return Status.UNKNOWN
    return Status.STALE

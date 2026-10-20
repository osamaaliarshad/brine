from datetime import UTC, datetime, timedelta

import pytest

from app.status import Status, minion_status

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
STALE_AFTER = timedelta(minutes=15)


def status(*, connected: bool, last_seen: timedelta | None, presence: timedelta | None) -> Status:
    return minion_status(
        connected=connected,
        last_seen_at=None if last_seen is None else NOW - last_seen,
        presence_at=None if presence is None else NOW - presence,
        now=NOW,
        stale_after=STALE_AFTER,
    )


@pytest.mark.parametrize(
    ("connected", "last_seen", "presence", "expected"),
    [
        # Fresh presence data: trust it.
        (True, timedelta(seconds=10), timedelta(seconds=10), Status.ONLINE),
        (False, timedelta(hours=2), timedelta(seconds=10), Status.OFFLINE),
        # Fresh data says absent and brine never saw it: still observed offline.
        (False, None, timedelta(seconds=10), Status.OFFLINE),
        # Exactly at the threshold still counts as fresh.
        (True, timedelta(minutes=15), timedelta(minutes=15), Status.ONLINE),
        # Presence data too old (e.g. salt-api unreachable): fall back to last known.
        (True, timedelta(minutes=20), timedelta(minutes=20), Status.STALE),
        (False, timedelta(days=3), timedelta(minutes=16), Status.STALE),
        # Never observed presence at all (fresh install, presence not working yet).
        (False, timedelta(minutes=1), None, Status.STALE),
        (False, None, None, Status.UNKNOWN),
        (False, None, timedelta(hours=1), Status.UNKNOWN),
    ],
)
def test_minion_status(
    connected: bool,
    last_seen: timedelta | None,
    presence: timedelta | None,
    expected: Status,
) -> None:
    assert status(connected=connected, last_seen=last_seen, presence=presence) is expected


def test_unobservable_minions_are_never_claimed_offline() -> None:
    def unobservable(connected: bool, last_seen_at: datetime | None) -> Status:
        return minion_status(
            connected=connected,
            last_seen_at=last_seen_at,
            presence_at=NOW - timedelta(seconds=10),
            now=NOW,
            stale_after=STALE_AFTER,
            observable=False,
        )

    assert unobservable(False, NOW - timedelta(minutes=1)) is Status.STALE
    assert unobservable(False, None) is Status.UNKNOWN
    # If presence does see it after all, it's online.
    assert unobservable(True, NOW) is Status.ONLINE

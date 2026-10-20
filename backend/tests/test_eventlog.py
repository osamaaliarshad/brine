import asyncio

from app.eventlog import EventLog
from app.salt.events import SaltEvent


def test_keeps_the_most_recent_events_with_sequence_numbers() -> None:
    log = EventLog(maxlen=3)
    for i in range(5):
        log.append(SaltEvent(f"tag/{i}", {"i": i}))
    recent = log.recent()
    assert [e["tag"] for e in recent] == ["tag/2", "tag/3", "tag/4"]
    assert [e["seq"] for e in recent] == [3, 4, 5]
    assert recent[0]["received_at"]


def test_shortens_public_keys_and_huge_returns() -> None:
    log = EventLog()
    pub = "-----BEGIN PUBLIC KEY-----" + "A" * 400 + "-----END PUBLIC KEY-----"
    entry = log.append(SaltEvent("salt/auth", {"pub": pub, "id": "m"}))
    assert len(entry["data"]["pub"]) < 80 and entry["data"]["id"] == "m"

    big = log.append(SaltEvent("salt/job/1/ret/m", {"return": "x" * 50_000, "id": "m"}))
    assert "omitted" in big["data"]["return"]["_brine"]
    small = log.append(SaltEvent("salt/job/2/ret/m", {"return": "ok"}))
    assert small["data"]["return"] == "ok"


async def test_subscribers_get_new_events() -> None:
    log = EventLog()
    log.append(SaltEvent("before"))
    async with log.subscribe() as queue:
        log.append(SaltEvent("after"))
        entry = await asyncio.wait_for(queue.get(), 1)
    assert entry["tag"] == "after"

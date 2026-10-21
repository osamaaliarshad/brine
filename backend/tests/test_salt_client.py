import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import respx

from app.config import SaltApiConfig
from app.salt.client import (
    SaltApiAuthError,
    SaltApiClient,
    SaltApiError,
    SaltApiForbidden,
    SaltApiUnavailable,
)
from app.salt.events import SaltEvent, parse_job_start_time, parse_sse, parse_stamp

API = "https://salt.test:8000"
CONFIG = SaltApiConfig.model_validate(
    {"url": API, "username": "brine", "password": "pw", "eauth": "pam"}
)


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


def login_ok(token: str, expire: float = 1_043_200.0) -> httpx.Response:
    body = {"return": [{"token": token, "expire": expire, "perms": [".*"], "user": "brine"}]}
    return httpx.Response(200, json=body)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
async def client(clock: Clock) -> AsyncIterator[SaltApiClient]:
    c = SaltApiClient(CONFIG, clock=clock)
    yield c
    await c.close()


@respx.mock
async def test_logs_in_once_and_sends_token(client: SaltApiClient) -> None:
    login = respx.post(f"{API}/login").mock(return_value=login_ok("t1"))
    run = respx.post(f"{API}/").mock(
        return_value=httpx.Response(200, json={"return": [{"m1": True}]})
    )

    assert await client.local("*", "test.ping") == {"m1": True}
    assert await client.local("*", "test.ping") == {"m1": True}

    assert login.call_count == 1
    assert json.loads(login.calls[0].request.content) == {
        "username": "brine",
        "password": "pw",
        "eauth": "pam",
    }
    assert run.calls[0].request.headers["X-Auth-Token"] == "t1"
    assert json.loads(run.calls[0].request.content) == [
        {"client": "local", "tgt": "*", "tgt_type": "glob", "fun": "test.ping", "arg": []}
    ]


@respx.mock
async def test_relogs_in_on_401_and_retries(client: SaltApiClient) -> None:
    respx.post(f"{API}/login").mock(side_effect=[login_ok("old"), login_ok("new")])
    run = respx.post(f"{API}/").mock(
        side_effect=[
            httpx.Response(401, text="expired"),
            httpx.Response(200, json={"return": [{"up": ["m1"], "down": []}]}),
        ]
    )

    assert await client.runner("manage.status") == {"up": ["m1"], "down": []}
    assert [c.request.headers["X-Auth-Token"] for c in run.calls] == ["old", "new"]


@respx.mock
async def test_refreshes_token_before_it_expires(client: SaltApiClient, clock: Clock) -> None:
    login = respx.post(f"{API}/login").mock(
        side_effect=[login_ok("t1", expire=clock.now + 3600), login_ok("t2")]
    )
    run = respx.post(f"{API}/").mock(return_value=httpx.Response(200, json={"return": [{}]}))

    await client.local("*", "test.ping")
    clock.now += 3600 - 30  # inside the refresh margin
    await client.local("*", "test.ping")

    assert login.call_count == 2
    assert run.calls[-1].request.headers["X-Auth-Token"] == "t2"


@respx.mock
async def test_bad_credentials_raise_auth_error(client: SaltApiClient) -> None:
    respx.post(f"{API}/login").mock(return_value=httpx.Response(401, text="nope"))
    with pytest.raises(SaltApiAuthError, match="rejected the login"):
        await client.local("*", "test.ping")


@respx.mock
async def test_login_without_permissions_is_an_auth_error(client: SaltApiClient) -> None:
    body = {"return": [{"token": "t", "expire": 2e9, "perms": [], "user": "brine"}]}
    respx.post(f"{API}/login").mock(return_value=httpx.Response(200, json=body))
    with pytest.raises(SaltApiAuthError, match="no permissions"):
        await client.local("*", "test.ping")


@respx.mock
async def test_connection_failure_is_unavailable(client: SaltApiClient) -> None:
    respx.post(f"{API}/login").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(SaltApiUnavailable, match="can't reach"):
        await client.local("*", "test.ping")


@respx.mock
async def test_gateway_errors_are_unavailable(client: SaltApiClient) -> None:
    respx.post(f"{API}/login").mock(return_value=login_ok("t"))
    respx.post(f"{API}/").mock(return_value=httpx.Response(503))
    with pytest.raises(SaltApiUnavailable):
        await client.local("*", "test.ping")


@respx.mock
async def test_wheel_unwraps_data_and_reports_failure(client: SaltApiClient) -> None:
    respx.post(f"{API}/login").mock(return_value=login_ok("t"))
    ok = {"return": [{"tag": "x", "data": {"success": True, "return": {"minions": ["m1"]}}}]}
    bad = {"return": [{"tag": "x", "data": {"success": False, "return": "boom"}}]}
    respx.post(f"{API}/").mock(
        side_effect=[httpx.Response(200, json=ok), httpx.Response(200, json=bad)]
    )

    assert await client.wheel("key.list_all") == {"minions": ["m1"]}
    with pytest.raises(SaltApiError, match="boom"):
        await client.wheel("key.list_all")


@respx.mock
async def test_wheel_keeps_salt_api_error_strings(client: SaltApiClient) -> None:
    respx.post(f"{API}/login").mock(return_value=login_ok("t"))
    respx.post(f"{API}/").mock(
        return_value=httpx.Response(200, json={"return": ["Exception occurred in wheel"]})
    )
    with pytest.raises(SaltApiError, match="Exception occurred in wheel"):
        await client.wheel("key.accept_dict", match={"minions_pre": ["m1"]})


@respx.mock
async def test_refused_after_a_fresh_login_means_not_allowed(client: SaltApiClient) -> None:
    # salt-api answers a call the ACL doesn't allow with 401, like an expired token. If a fresh
    # token is refused too, it's the ACL, and the error says which function.
    login = respx.post(f"{API}/login").mock(return_value=login_ok("t"))
    respx.post(f"{API}/").mock(return_value=httpx.Response(401, text="<html>401</html>"))
    with pytest.raises(SaltApiForbidden, match=r"isn't allowed to run wheel key.delete_dict"):
        await client.wheel("key.delete_dict", match={"minions": ["m1"]})
    assert login.call_count == 2


@respx.mock
async def test_permissions_come_from_the_login(client: SaltApiClient) -> None:
    perms = [{"@wheel": ["key.list_all"]}, "@jobs"]
    body = {"return": [{"token": "t", "expire": 1_043_200.0, "perms": perms, "user": "brine"}]}
    login = respx.post(f"{API}/login").mock(return_value=httpx.Response(200, json=body))
    assert await client.permissions() == perms
    assert await client.permissions() == perms
    assert login.call_count == 1


@respx.mock
async def test_local_async_returns_jid(client: SaltApiClient) -> None:
    respx.post(f"{API}/login").mock(return_value=login_ok("t"))
    respx.post(f"{API}/").mock(
        side_effect=[
            httpx.Response(200, json={"return": [{"jid": "2026", "minions": ["m1"]}]}),
            httpx.Response(200, json={"return": [{}]}),  # no minion matched
        ]
    )
    assert await client.local_async("*", "grains.items") == "2026"
    assert await client.local_async("nope", "grains.items") is None


SSE_BODY = (
    "retry: 400\n\n"
    "tag: salt/presence/present\n"
    'data: {"tag": "salt/presence/present", "data": {"present": ["m1"], '
    '"_stamp": "2026-10-20T14:01:33.033166"}}\n\n'
    ": keep-alive\n\n"
    "tag: broken\n"
    "data: {not json\n\n"
    'data: {"tag": "salt/key", "data": {"act": "accept", "id": "m2"}}\n\n'
)


@respx.mock
async def test_events_stream_parses_sse(client: SaltApiClient) -> None:
    respx.post(f"{API}/login").mock(return_value=login_ok("t"))
    route = respx.get(f"{API}/events").mock(return_value=httpx.Response(200, text=SSE_BODY))

    events = [e async for e in client.events()]

    assert [e.tag for e in events] == ["salt/presence/present", "salt/key"]
    assert events[0].data["present"] == ["m1"]
    assert events[0].stamp == datetime(2026, 10, 20, 14, 1, 33, 33166, tzinfo=UTC)
    assert route.calls[0].request.headers["X-Auth-Token"] == "t"


@respx.mock
async def test_events_relogin_on_401(client: SaltApiClient) -> None:
    respx.post(f"{API}/login").mock(side_effect=[login_ok("old"), login_ok("new")])
    respx.get(f"{API}/events").mock(
        side_effect=[httpx.Response(401), httpx.Response(200, text=SSE_BODY)]
    )
    assert len([e async for e in client.events()]) == 2


async def test_parse_sse_handles_multiline_data() -> None:
    async def lines() -> AsyncIterator[str]:
        for line in ['data: {"tag": "a",', 'data: "data": {"x": 1}}', ""]:
            yield line

    assert [e async for e in parse_sse(lines())] == [SaltEvent("a", {"x": 1})]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-10-20T14:01:33.033166", datetime(2026, 10, 20, 14, 1, 33, 33166, tzinfo=UTC)),
        ("garbage", None),
        (None, None),
    ],
)
def test_parse_stamp(value: Any, expected: datetime | None) -> None:
    assert parse_stamp(value) == expected


def test_parse_job_start_time() -> None:
    assert parse_job_start_time("2026, Oct 20 14:01:33.273737") == datetime(
        2026, 10, 20, 14, 1, 33, 273737, tzinfo=UTC
    )
    assert parse_job_start_time("nope") is None


FLAKY = {"status": 500, "return": "An unexpected error occurred"}


@respx.mock
async def test_salt_api_500s_are_retried_when_safe(client: SaltApiClient) -> None:
    respx.post(f"{API}/login").mock(return_value=login_ok("t"))
    run = respx.post(f"{API}/").mock(
        side_effect=[
            httpx.Response(500, json=FLAKY),
            httpx.Response(200, json={"return": [{"up": ["m1"], "down": []}]}),
        ]
    )
    assert await client.runner("manage.status") == {"up": ["m1"], "down": []}
    assert run.call_count == 2


@respx.mock
async def test_starting_a_job_is_never_retried(client: SaltApiClient) -> None:
    # The 500 may have come after the job started: retrying could run it twice.
    respx.post(f"{API}/login").mock(return_value=login_ok("t"))
    run = respx.post(f"{API}/").mock(
        side_effect=[
            httpx.Response(500, json=FLAKY),
            httpx.Response(200, json={"return": [{"jid": "j1", "minions": ["m1"]}]}),
        ]
    )
    with pytest.raises(SaltApiError) as caught:
        await client.start_job("m1", "state.apply")
    assert caught.value.status == 500 and run.call_count == 1

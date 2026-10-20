"""Phase 0 smoke test: prove the demo salt-api does everything brine needs.

Run from the repo root with the demo stack up:

    uv run --project backend python demo/smoke_test.py [--presence]

--presence also stops and restarts rover-03 and waits for salt-api's presence events to
report it lost and then back. Takes about a minute.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

API = os.environ.get("SALT_API_URL", "http://127.0.0.1:8001")
USER = os.environ.get("SALT_API_USER", "brine")
PASSWORD = os.environ.get("SALT_API_PASSWORD", "brine-demo")
ACCEPTED = {"rover-01", "rover-02", "rover-03", "dock-01"}
COMPOSE = ["docker", "compose", "-f", "docker-compose.demo.yml"]


def step(msg: str) -> None:
    print(f"\n== {msg}", flush=True)


def ok(msg: str) -> None:
    print(f"   ok  {msg}", flush=True)


def fail(msg: str) -> None:
    print(f"   FAIL {msg}", flush=True)
    sys.exit(1)


async def login(client: httpx.AsyncClient) -> str:
    resp = await client.post(
        "/login", json={"username": USER, "password": PASSWORD, "eauth": "pam"}
    )
    if resp.status_code != 200:
        fail(f"login returned {resp.status_code}: {resp.text[:200]}")
    info = resp.json()["return"][0]
    ok(
        f"token for {info['user']} (eauth={info['eauth']}), expires in {info['expire'] - time.time():.0f}s"
    )
    return str(info["token"])


async def call(http: httpx.AsyncClient, token: str, /, **lowstate: Any) -> Any:
    # Positional-only, because salt's lowstate has its own `client` key (local/runner/wheel).
    resp = await http.post("/", json=[lowstate], headers={"X-Auth-Token": token})
    if resp.status_code != 200:
        fail(f"{lowstate.get('fun')} returned {resp.status_code}: {resp.text[:200]}")
    return resp.json()["return"][0]


async def events(client: httpx.AsyncClient, token: str) -> AsyncIterator[dict[str, Any]]:
    """Yield events from salt-api's /events server-sent-event stream."""
    async with client.stream(
        "GET", "/events", headers={"X-Auth-Token": token}, timeout=None
    ) as resp:
        async for line in resp.aiter_lines():
            if line.startswith("data:"):
                yield json.loads(line[5:])


async def wait_for_event(
    client: httpx.AsyncClient, token: str, tag: str, check: Any, timeout: float
) -> dict[str, Any]:
    async def watch() -> dict[str, Any]:
        async for event in events(client, token):
            if event["tag"].startswith(tag) and check(event["data"]):
                return event
        raise RuntimeError("event stream ended")

    try:
        return await asyncio.wait_for(watch(), timeout)
    except TimeoutError:
        fail(f"no matching {tag} event within {timeout:.0f}s")
        raise  # unreachable


def compose(*args: str) -> None:
    if not shutil.which("docker"):
        fail("docker not on PATH")
    subprocess.run([*COMPOSE, *args], check=True, capture_output=True)


async def main(presence: bool) -> None:
    async with httpx.AsyncClient(base_url=API, timeout=30) as client:
        step(f"login to {API}")
        token = await login(client)

        step("test.ping (waiting up to 90s for the fleet to connect)")
        deadline = time.monotonic() + 90
        while True:
            pong = await call(client, token, client="local", tgt="*", fun="test.ping")
            if set(pong) >= ACCEPTED or time.monotonic() > deadline:
                break
            await asyncio.sleep(3)
        if not set(pong) >= ACCEPTED:
            fail(f"only {sorted(pong)} answered")
        ok(f"{len(pong)} minions answered: {', '.join(sorted(pong))}")

        step("grains.items")
        grains = await call(client, token, client="local", tgt="*", fun="grains.items")
        for mid in sorted(grains):
            g = grains[mid]
            ok(
                f"{mid:9} site={g.get('site')} app={g.get('app_version')} "
                f"fw={g.get('firmware_version')} os={g.get('osfinger')} salt={g.get('saltversion')}"
            )

        step("wheel key.list_all")
        keys = (await call(client, token, client="wheel", fun="key.list_all"))["data"]["return"]
        ok(f"accepted={sorted(keys['minions'])} pending={sorted(keys['minions_pre'])}")
        if "rover-04" not in keys["minions_pre"]:
            fail("rover-04 should be pending")

        step("runner manage.status")
        status = await call(client, token, client="runner", fun="manage.status")
        ok(f"up={sorted(status['up'])} down={sorted(status['down'])}")

        step("/events: waiting for a salt/presence/present event listing the fleet")
        event = await wait_for_event(
            client,
            token,
            "salt/presence/present",
            lambda d: set(d.get("present", [])) >= ACCEPTED,
            timeout=45,
        )
        ok(f"present={sorted(event['data']['present'])}")

        if not presence:
            print("\nAll checks passed (run with --presence to test going offline).")
            return

        step("stopping rover-03 and waiting for salt/presence/change lost=[rover-03]")
        compose("stop", "rover-03")
        start = time.monotonic()
        await wait_for_event(
            client,
            token,
            "salt/presence/change",
            lambda d: "rover-03" in d.get("lost", []),
            timeout=60,
        )
        ok(f"master reported rover-03 lost after {time.monotonic() - start:.0f}s")
        status = await call(client, token, client="runner", fun="manage.status")
        if "rover-03" not in status["down"]:
            fail(f"manage.status still shows rover-03 up: {status}")
        ok(f"manage.status down={sorted(status['down'])}")

        step("starting rover-03 and waiting for salt/presence/change new=[rover-03]")
        compose("start", "rover-03")
        start = time.monotonic()
        await wait_for_event(
            client,
            token,
            "salt/presence/change",
            lambda d: "rover-03" in d.get("new", []),
            timeout=90,
        )
        ok(f"master reported rover-03 back after {time.monotonic() - start:.0f}s")

    print("\nAll checks passed, including going offline and coming back.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--presence", action="store_true", help="also stop/start rover-03")
    asyncio.run(main(parser.parse_args().presence))

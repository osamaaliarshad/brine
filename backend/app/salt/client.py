"""Async salt-api (rest_cherrypy) client.

Logs in with brine's service account, keeps the token fresh (re-login shortly before it
expires, and once more if salt-api answers 401), and wraps the three client types brine uses.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx

from app.config import SaltApiConfig
from app.salt.events import SaltEvent, parse_sse

log = logging.getLogger(__name__)

# Re-login when the token has less than this long to live.
REFRESH_MARGIN_SECONDS = 60


class SaltApiError(Exception):
    """salt-api answered, but not with what we asked for."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class SaltApiUnavailable(SaltApiError):
    """salt-api (or the master behind it) can't be reached right now."""


class SaltApiAuthError(SaltApiError):
    """The service account was rejected (wrong password, or no permissions)."""


class SaltApiForbidden(SaltApiAuthError):
    """Logged in fine, but external_auth doesn't let the service account do this."""


class SaltApiClient:
    def __init__(
        self,
        config: SaltApiConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._config = config
        self._clock = clock
        self._http = httpx.AsyncClient(
            base_url=str(config.url),
            verify=config.verify_tls,
            timeout=config.timeout_seconds,
            transport=transport,
            headers={"Accept": "application/json"},
        )
        self._token: str | None = None
        self._expires_at = 0.0
        self._perms: list[Any] = []
        self._login_lock = asyncio.Lock()

    @property
    def username(self) -> str:
        return self._config.username

    async def close(self) -> None:
        await self._http.aclose()

    # --- auth -----------------------------------------------------------------------------

    async def _login(self) -> None:
        body = {
            "username": self._config.username,
            "password": self._config.password.get_secret_value(),
            "eauth": self._config.eauth,
        }
        resp = await self._send("POST", "/login", json=body)
        if resp.status_code == 401:
            raise SaltApiAuthError(
                f"salt-api rejected the login for {self._config.username!r} "
                f"(eauth={self._config.eauth}); check the password and external_auth config",
                401,
            )
        _raise_for_status(resp)
        info = resp.json()["return"][0]
        if not info.get("perms"):
            raise SaltApiAuthError(
                f"{self._config.username!r} logged in but has no permissions in external_auth"
            )
        self._token = str(info["token"])
        self._expires_at = float(info["expire"])
        self._perms = list(info["perms"])
        log.info("logged in to salt-api as %s", self._config.username)

    async def _get_token(self, *, force: bool = False) -> str:
        async with self._login_lock:
            expiring = self._expires_at - self._clock() < REFRESH_MARGIN_SECONDS
            if force or self._token is None or expiring:
                await self._login()
            assert self._token is not None
            return self._token

    async def permissions(self) -> list[Any]:
        """The service account's external_auth entries, as salt-api reported them at login."""
        await self._get_token()
        return self._perms

    # --- requests -------------------------------------------------------------------------

    async def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            return await self._http.request(method, path, **kwargs)
        except httpx.TransportError as exc:
            raise SaltApiUnavailable(f"can't reach salt-api at {self._config.url}: {exc}") from exc

    async def _authed(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        token = await self._get_token()
        resp = await self._send(method, path, headers={"X-Auth-Token": token}, **kwargs)
        if resp.status_code == 401:
            # Token revoked or salt-api restarted: log in again once.
            token = await self._get_token(force=True)
            resp = await self._send(method, path, headers={"X-Auth-Token": token}, **kwargs)
            if resp.status_code == 401:
                # A fresh token refused too: external_auth doesn't allow this call.
                raise SaltApiForbidden("salt-api refused: the service account isn't allowed", 403)
        _raise_for_status(resp)
        return resp

    async def run(self, lowstate: dict[str, Any], *, wait_seconds: float | None = None) -> Any:
        """POST one lowstate chunk to salt-api and return its result. `wait_seconds` overrides
        the configured timeout, for calls that wait on slow work."""
        extra: dict[str, Any] = {"timeout": wait_seconds} if wait_seconds is not None else {}
        try:
            resp = await self._authed("POST", "/", json=[lowstate], **extra)
        except SaltApiForbidden as exc:
            client, fun = str(lowstate.get("client", "")), lowstate.get("fun")
            what = fun if client.startswith("local") else f"{client} {fun}"
            raise SaltApiForbidden(
                f"brine's Salt account isn't allowed to run {what}", 403
            ) from exc
        try:
            return resp.json()["return"][0]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise SaltApiError(f"unexpected salt-api response: {resp.text[:200]}") from exc

    async def local(
        self,
        tgt: str,
        fun: str,
        *,
        arg: list[Any] | None = None,
        kwarg: dict[str, Any] | None = None,
        tgt_type: str = "glob",
        salt_timeout: int | None = None,
    ) -> dict[str, Any]:
        """Run an execution module on minions and wait for their returns. Minions that don't
        answer within `salt_timeout` seconds (Salt's default if None) are simply absent."""
        lowstate: dict[str, Any] = {
            "client": "local",
            "tgt": tgt,
            "tgt_type": tgt_type,
            "fun": fun,
            "arg": arg or [],
        }
        if kwarg:
            lowstate["kwarg"] = kwarg
        if salt_timeout is not None:
            lowstate["timeout"] = salt_timeout
        result = await self.run(lowstate)
        return result if isinstance(result, dict) else {}

    async def local_async(
        self, tgt: str, fun: str, *, arg: list[Any] | None = None, tgt_type: str = "glob"
    ) -> str | None:
        """Start a job without waiting; returns its jid (None if no minion matched)."""
        jid, _ = await self.start_job(tgt, fun, arg=arg, tgt_type=tgt_type)
        return jid

    async def start_job(
        self,
        tgt: str,
        fun: str,
        *,
        arg: list[Any] | None = None,
        tgt_type: str = "glob",
        metadata: dict[str, Any] | None = None,
    ) -> tuple[str | None, list[str]]:
        """Start a job without waiting: (jid, the minions Salt sent it to). No jid if nothing
        matched. `metadata` travels with the job into every return and the job cache."""
        lowstate: dict[str, Any] = {
            "client": "local_async",
            "tgt": tgt,
            "tgt_type": tgt_type,
            "fun": fun,
            "arg": arg or [],
        }
        if metadata:
            lowstate["metadata"] = metadata
        result = await self.run(lowstate)
        if not isinstance(result, dict) or not result.get("jid"):
            return None, []
        return str(result["jid"]), [str(m) for m in result.get("minions") or []]

    async def runner(self, fun: str, **kwargs: Any) -> Any:
        return await self.run({"client": "runner", "fun": fun, **kwargs})

    async def wheel(self, fun: str, **kwargs: Any) -> Any:
        result = await self.run({"client": "wheel", "fun": fun, **kwargs})
        if not isinstance(result, dict):  # salt-api reports some failures as a bare string
            raise SaltApiError(f"wheel {fun} failed: {result!r:.200}")
        data = result.get("data", {})
        if not data.get("success", False):
            raise SaltApiError(f"wheel {fun} failed: {data.get('return')!r:.200}")
        return data.get("return")

    async def events(self) -> AsyncIterator[SaltEvent]:
        """Stream events from `/events` until the connection ends or fails."""
        for attempt in range(2):
            token = await self._get_token(force=attempt > 0)
            try:
                async with self._http.stream(
                    "GET",
                    "/events",
                    headers={"X-Auth-Token": token, "Accept": "text/event-stream"},
                    timeout=httpx.Timeout(self._config.timeout_seconds, read=None),
                ) as resp:
                    if resp.status_code == 401 and attempt == 0:
                        continue
                    _raise_for_status(resp)
                    async for event in parse_sse(resp.aiter_lines()):
                        yield event
                    return
            except httpx.TransportError as exc:
                raise SaltApiUnavailable(
                    f"event stream from {self._config.url} failed: {exc}"
                ) from exc


def _raise_for_status(resp: httpx.Response) -> None:
    if resp.status_code < 400:
        return
    try:
        detail = resp.text[:200]
    except httpx.ResponseNotRead:  # streaming response; the body isn't worth reading here
        detail = ""
    if resp.status_code in (502, 503, 504):
        raise SaltApiUnavailable(f"salt-api returned {resp.status_code}", resp.status_code)
    if resp.status_code == 401:
        raise SaltApiAuthError("salt-api rejected the token", 401)
    raise SaltApiError(f"salt-api returned {resp.status_code}: {detail}", resp.status_code)

"""Standalone async API client.

This client owns connection details, cookies, and fetch/set operations. It
returns normalized, JSON-serializable dictionaries by using the internal
payload normalizers.

The Home Assistant integration should treat this client as the primary API.

This module intentionally avoids Home Assistant imports.
"""

from __future__ import annotations

import asyncio
import json
import time
import xml.etree.ElementTree as ET
from http import HTTPStatus
from typing import Any, cast

import aiohttp
import async_timeout
from yarl import URL

from . import payloads
from .exceptions import (
    ApexFusionAuthError,
    ApexFusionNotSupportedError,
    ApexFusionParseError,
    ApexFusionRateLimitedError,
    ApexFusionRestDisabledError,
    ApexFusionTransportError,
)
from .modules.trident import finalize_trident
from .rest_config import (
    parse_mxm_devices_from_mconf,
    sanitize_mconf_for_storage,
    sanitize_nconf_for_storage,
)

_DEFAULT_TIMEOUT_SECONDS = 10
_DEFAULT_STATUS_PATH = "/cgi-bin/status.xml"

_TRANSIENT_HTTP_STATUSES: set[int] = {
    HTTPStatus.REQUEST_TIMEOUT,
    HTTPStatus.TOO_MANY_REQUESTS,
    HTTPStatus.INTERNAL_SERVER_ERROR,
    HTTPStatus.BAD_GATEWAY,
    HTTPStatus.SERVICE_UNAVAILABLE,
    HTTPStatus.GATEWAY_TIMEOUT,
}


def _is_transient_http_status(status: int) -> bool:
    return status in _TRANSIENT_HTTP_STATUSES


def build_base_url(host: str) -> str:
    """Build the base URL for the controller.

    Args:
        host: Hostname or URL.

    Returns:
        Base URL without trailing slash.
    """
    host = (host or "").strip()
    if host.startswith("http://") or host.startswith("https://"):
        return host.rstrip("/")
    return f"http://{host}".rstrip("/")


def build_status_url(host: str, status_path: str) -> str:
    """Build a full URL to the XML status endpoint.

    Args:
        host: Hostname or URL.
        status_path: Path to status endpoint.

    Returns:
        Fully-qualified URL.
    """
    base = build_base_url(host)

    path = (status_path or _DEFAULT_STATUS_PATH).strip()
    if not path.startswith("/"):
        path = "/" + path

    return base + path


def _session_has_connect_sid(session: aiohttp.ClientSession, base_url: str) -> bool:
    try:
        cookies = session.cookie_jar.filter_cookies(URL(base_url))
        return "connect.sid" in cookies
    except Exception:
        return False


def _set_connect_sid_cookie(
    session: aiohttp.ClientSession, *, base_url: str, sid: str
) -> None:
    if not sid:
        return
    session.cookie_jar.update_cookies({"connect.sid": sid}, response_url=URL(base_url))


class ApexFusionClient:
    """Async client for the controller REST/XML/CGI endpoints."""

    def __init__(
        self,
        *,
        host: str,
        username: str | None = None,
        password: str | None = None,
        status_path: str | None = None,
        timeout_seconds: int | None = None,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self.host = str(host or "")
        self.username = str(username or "")
        self.password = str(password or "")
        self.status_path = str(status_path or _DEFAULT_STATUS_PATH)
        self.timeout_seconds = int(timeout_seconds or _DEFAULT_TIMEOUT_SECONDS)

        self._session = session
        self._owns_session = session is None

        self._rest_sid: str | None = None
        self._rest_disabled_until: float = 0.0
        self._rest_status_path: str | None = None

        self._rest_config_last_fetch: float = 0.0
        self._rest_config_refresh_seconds: float = 5 * 60
        self._cached_mconf: list[dict[str, Any]] | None = None
        self._cached_nconf: dict[str, Any] | None = None
        self._cached_mxm_devices: dict[str, dict[str, str]] | None = None

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session

    async def async_close(self) -> None:
        """Close any internally-owned aiohttp session."""
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None

    def _parse_retry_after_seconds(self, headers: Any) -> float | None:
        try:
            value = headers.get("Retry-After")
            if value is None:
                return None
            t = str(value).strip()
            if not t:
                return None
            return float(int(t))
        except Exception:
            return None

    def _disable_rest(self, *, seconds: float) -> None:
        until = time.monotonic() + max(0.0, seconds)
        if until > self._rest_disabled_until:
            self._rest_disabled_until = until

    def _assert_rest_available(self) -> None:
        now = time.monotonic()
        if now < self._rest_disabled_until:
            raise ApexFusionRestDisabledError(
                f"REST temporarily disabled (retry in ~{int(self._rest_disabled_until - now)}s)",
                retry_after_seconds=self._rest_disabled_until - now,
            )

    async def _async_rest_login(self) -> str:
        """Ensure a REST session cookie exists and return connect.sid.

        Returns:
            connect.sid cookie value.

        Raises:
            ApexFusionAuthError: If credentials are missing or rejected.
            ApexFusionNotSupportedError: If REST is not supported.
            ApexFusionRateLimitedError: If rate limited.
            ApexFusionTransportError: On network errors.
        """
        self._assert_rest_available()

        if not self.password:
            raise ApexFusionAuthError("Password is required for REST")

        base_url = build_base_url(self.host)

        if self._rest_sid:
            return self._rest_sid

        sid_morsel = self.session.cookie_jar.filter_cookies(URL(base_url)).get(
            "connect.sid"
        )
        if sid_morsel is not None and sid_morsel.value:
            self._rest_sid = sid_morsel.value
            return sid_morsel.value

        login_url = f"{base_url}/rest/login"

        login_candidates: list[str] = []
        if (self.username or "").strip():
            login_candidates.append(self.username.strip())
        if "admin" not in login_candidates:
            login_candidates.append("admin")

        last_status: int | None = None
        last_error: Exception | None = None

        for login_user in login_candidates:
            try:
                async with async_timeout.timeout(self.timeout_seconds):
                    async with self.session.post(
                        login_url,
                        json={
                            "login": login_user,
                            "password": self.password,
                            "remember_me": False,
                        },
                        headers={
                            "Accept": "*/*",
                            "Content-Type": "application/json",
                        },
                    ) as resp:
                        last_status = resp.status
                        if resp.status == 404:
                            raise ApexFusionNotSupportedError(
                                "REST login endpoint not found"
                            )
                        if resp.status in (401, 403):
                            continue
                        if resp.status == 429:
                            retry_after = self._parse_retry_after_seconds(resp.headers)
                            backoff = (
                                float(retry_after) if retry_after is not None else 300.0
                            )
                            self._disable_rest(seconds=backoff)
                            raise ApexFusionRateLimitedError(
                                f"Controller rate limited REST login; retry after ~{int(backoff)}s",
                                retry_after_seconds=retry_after,
                            )

                        resp.raise_for_status()
                        body = await resp.text()

                morsel = resp.cookies.get("connect.sid")
                if morsel is not None and morsel.value:
                    self._rest_sid = morsel.value
                    _set_connect_sid_cookie(
                        self.session, base_url=base_url, sid=morsel.value
                    )
                    return morsel.value

                login_any: Any = json.loads(body) if body else {}
                if isinstance(login_any, dict):
                    sid_any: Any = cast(dict[str, Any], login_any).get("connect.sid")
                    if isinstance(sid_any, str) and sid_any:
                        self._rest_sid = sid_any
                        _set_connect_sid_cookie(
                            self.session, base_url=base_url, sid=sid_any
                        )
                        return sid_any

            except ApexFusionNotSupportedError:
                raise
            except ApexFusionRateLimitedError:
                raise
            except (
                asyncio.TimeoutError,
                aiohttp.ClientError,
                json.JSONDecodeError,
            ) as err:
                last_error = err
                continue

        self._rest_sid = None
        if last_error is not None:
            raise ApexFusionTransportError(
                f"Error logging into Apex REST API: {last_error}"
            ) from last_error
        raise ApexFusionAuthError(
            f"REST login rejected (HTTP {last_status})"
            if last_status
            else "REST login rejected"
        )

    async def async_rest_put_json(self, *, path: str, payload: dict[str, Any]) -> None:
        """Send a REST control PUT.

        Args:
            path: URL path starting with `/rest/...`.
            payload: JSON payload.

        Raises:
            ApexFusionRestDisabledError: If REST is disabled.
            ApexFusionAuthError: If auth is rejected.
            ApexFusionNotSupportedError: If endpoint does not exist.
            ApexFusionRateLimitedError: If rate limited.
            ApexFusionTransportError: On network errors.
        """
        self._assert_rest_available()

        if not self.password:
            raise ApexFusionAuthError("Password is required for REST control")

        base_url = build_base_url(self.host)
        if not path.startswith("/"):
            path = "/" + path
        url = f"{base_url}{path}"

        async def _do_put(*, sid: str | None) -> None:
            headers: dict[str, str] = {"Accept": "*/*"}
            if sid:
                headers["Cookie"] = f"connect.sid={sid}"
            async with async_timeout.timeout(self.timeout_seconds):
                async with self.session.put(url, json=payload, headers=headers) as resp:
                    if resp.status == 404:
                        raise ApexFusionNotSupportedError("REST endpoint not found")
                    if resp.status == 429:
                        retry_after = self._parse_retry_after_seconds(resp.headers)
                        backoff = (
                            float(retry_after) if retry_after is not None else 300.0
                        )
                        self._disable_rest(seconds=backoff)
                        raise ApexFusionRateLimitedError(
                            f"Controller rate limited REST control; retry after ~{int(backoff)}s",
                            retry_after_seconds=retry_after,
                        )
                    if resp.status in (401, 403):
                        raise ApexFusionAuthError("REST control rejected")
                    if _is_transient_http_status(resp.status):
                        raise ApexFusionTransportError(
                            f"Transient REST control HTTP error (status={resp.status})"
                        )
                    resp.raise_for_status()
                    await resp.text()

        try:
            sid = await self._async_rest_login()
            await _do_put(sid=sid)
        except ApexFusionAuthError:
            self._rest_sid = None
            sid2 = await self._async_rest_login()
            await _do_put(sid=sid2)
        except (asyncio.TimeoutError, aiohttp.ClientError) as err:
            raise ApexFusionTransportError(
                f"Error sending REST control: {err}"
            ) from err

    async def async_rest_get_json(self, *, path: str) -> dict[str, Any]:
        """Send a REST GET.

        Args:
            path: REST path beginning with or without a leading slash.

        Returns:
            Parsed JSON object.
        """
        self._assert_rest_available()

        if not self.password:
            raise ApexFusionAuthError("Password is required for REST")

        base_url = build_base_url(self.host)
        if not path.startswith("/"):
            path = "/" + path
        url = f"{base_url}{path}"

        async def _do_get(*, sid: str | None) -> dict[str, Any]:
            headers: dict[str, str] = {"Accept": "*/*"}
            if sid:
                headers["Cookie"] = f"connect.sid={sid}"
            async with async_timeout.timeout(self.timeout_seconds):
                async with self.session.get(url, headers=headers) as resp:
                    if resp.status == 404:
                        raise ApexFusionNotSupportedError("REST endpoint not found")
                    if resp.status == 429:
                        retry_after = self._parse_retry_after_seconds(resp.headers)
                        backoff = (
                            float(retry_after) if retry_after is not None else 300.0
                        )
                        self._disable_rest(seconds=backoff)
                        raise ApexFusionRateLimitedError(
                            f"Controller rate limited REST GET; retry after ~{int(backoff)}s",
                            retry_after_seconds=retry_after,
                        )
                    if resp.status in (401, 403):
                        raise ApexFusionAuthError("REST GET rejected")
                    if _is_transient_http_status(resp.status):
                        raise ApexFusionTransportError(
                            f"Transient REST GET HTTP error (status={resp.status})"
                        )
                    resp.raise_for_status()
                    body = await resp.text()

            any_obj: Any = json.loads(body) if body else {}
            if not isinstance(any_obj, dict):
                raise ApexFusionParseError("REST response was not a JSON object")
            return cast(dict[str, Any], any_obj)

        try:
            sid = await self._async_rest_login()
            return await _do_get(sid=sid)
        except ApexFusionAuthError:
            self._rest_sid = None
            sid2 = await self._async_rest_login()
            return await _do_get(sid=sid2)
        except (asyncio.TimeoutError, aiohttp.ClientError, json.JSONDecodeError) as err:
            raise ApexFusionTransportError(f"Error fetching REST data: {err}") from err

    def _merge_cached_rest_config(self, data: dict[str, Any]) -> None:
        if self._cached_mconf is not None or self._cached_nconf is not None:
            config_any: Any = data.get("config")
            if not isinstance(config_any, dict):
                config_any = {}
                data["config"] = config_any
            config = cast(dict[str, Any], config_any)
            if self._cached_mconf is not None and "mconf" not in config:
                config["mconf"] = self._cached_mconf
            if self._cached_nconf is not None and "nconf" not in config:
                config["nconf"] = self._cached_nconf

        if self._cached_mxm_devices is not None and "mxm_devices" not in data:
            data["mxm_devices"] = self._cached_mxm_devices

        trident_any: Any = data.get("trident")
        if isinstance(trident_any, dict):
            trident = cast(dict[str, Any], trident_any)
            if trident.get("waste_size_ml") is None and self._cached_mconf:
                for m in self._cached_mconf:
                    if str(m.get("hwtype") or "").strip().upper() not in {"TRI", "TNP"}:
                        continue
                    extra_any: Any = m.get("extra")
                    if isinstance(extra_any, dict):
                        waste_any: Any = cast(dict[str, Any], extra_any).get(
                            "wasteSize"
                        )
                        if isinstance(waste_any, (int, float)):
                            trident["waste_size_ml"] = float(waste_any)
                            break

    async def async_try_refresh_rest_config(
        self, *, data: dict[str, Any], force: bool = False
    ) -> None:
        """Best-effort refresh of cached config subsets."""
        if not self.password:
            return

        now = time.monotonic()
        self._merge_cached_rest_config(data)

        should_refresh = force or (
            self._cached_mconf is None
            or (now - self._rest_config_last_fetch) >= self._rest_config_refresh_seconds
        )
        if not should_refresh:
            return

        base_url = build_base_url(self.host)

        def _apply_sanitized_config(*, config_obj: dict[str, Any]) -> None:
            sanitized_mconf = sanitize_mconf_for_storage(config_obj)
            sanitized_nconf = sanitize_nconf_for_storage(config_obj)
            mxm_devices = parse_mxm_devices_from_mconf(config_obj)

            if sanitized_mconf:
                self._cached_mconf = sanitized_mconf
                data.setdefault("config", {})["mconf"] = sanitized_mconf

                trident_any: Any = data.get("trident")
                if isinstance(trident_any, dict):
                    for m in sanitized_mconf:
                        if str(m.get("hwtype") or "").strip().upper() not in {
                            "TRI",
                            "TNP",
                        }:
                            continue
                        extra_any: Any = m.get("extra")
                        if not isinstance(extra_any, dict):
                            continue
                        waste_any: Any = cast(dict[str, Any], extra_any).get(
                            "wasteSize"
                        )
                        if isinstance(waste_any, (int, float)):
                            cast(dict[str, Any], trident_any)["waste_size_ml"] = float(
                                waste_any
                            )
                            break

            if sanitized_nconf:
                self._cached_nconf = sanitized_nconf
                data.setdefault("config", {})["nconf"] = sanitized_nconf

            self._cached_mxm_devices = mxm_devices
            data["mxm_devices"] = mxm_devices

        try:
            sid = await self._async_rest_login()
            headers: dict[str, str] = {
                "Accept": "*/*",
                "Content-Type": "application/json",
                "Cookie": f"connect.sid={sid}",
            }
            config_url = f"{base_url}/rest/config"
            async with async_timeout.timeout(self.timeout_seconds):
                async with self.session.get(config_url, headers=headers) as resp:
                    if resp.status == 404:
                        raise ApexFusionNotSupportedError("/rest/config not found")
                    if resp.status in (401, 403):
                        raise ApexFusionAuthError("REST config rejected")
                    resp.raise_for_status()
                    config_text = await resp.text()

            config_any: Any = json.loads(config_text) if config_text else {}
            if not isinstance(config_any, dict):
                return
            config_obj = cast(dict[str, Any], config_any)
            _apply_sanitized_config(config_obj=config_obj)
            self._rest_config_last_fetch = now
        except (ApexFusionAuthError, ApexFusionNotSupportedError):
            return
        except (asyncio.TimeoutError, aiohttp.ClientError, json.JSONDecodeError):
            return

    async def async_refresh_config_now(self) -> dict[str, Any]:
        """Force a sanitized /rest/config refresh.

        Returns:
            Dict containing `config` and `mxm_devices` sections.
        """
        config_obj = await self.async_rest_get_json(path="/rest/config")
        sanitized_mconf = sanitize_mconf_for_storage(config_obj)
        sanitized_nconf = sanitize_nconf_for_storage(config_obj)
        mxm_devices = parse_mxm_devices_from_mconf(config_obj)

        self._cached_mconf = sanitized_mconf
        self._cached_nconf = sanitized_nconf or self._cached_nconf
        self._cached_mxm_devices = mxm_devices
        self._rest_config_last_fetch = time.monotonic()

        return {
            "config": {"mconf": sanitized_mconf, "nconf": sanitized_nconf},
            "mxm_devices": mxm_devices,
        }

    async def async_fetch_status(self) -> dict[str, Any]:
        """Fetch controller status and normalize it.

        Returns:
            Normalized status dict.

        Raises:
            ApexFusionAuthError: If auth required and rejected.
            ApexFusionTransportError: On network failures.
            ApexFusionParseError: On parsing failures.
        """

        base_url = build_base_url(self.host)
        url = build_status_url(self.host, self.status_path)

        auth: aiohttp.BasicAuth | None = None
        if self.password:
            auth = aiohttp.BasicAuth(self.username or "admin", self.password)

        # Prefer REST when credentials exist.
        if self.password:
            try:
                data = await self._async_fetch_status_via_rest(base_url=base_url)
                await self.async_try_refresh_rest_config(data=data)
                finalize_trident(data)
                return data
            except (
                ApexFusionNotSupportedError,
                ApexFusionAuthError,
                ApexFusionRateLimitedError,
            ):
                # fall through to CGI/XML
                pass
            except ApexFusionRestDisabledError:
                pass

        # Try CGI JSON first.
        try:
            json_url = f"{base_url}/cgi-bin/status.json"
            async with async_timeout.timeout(self.timeout_seconds):
                async with self.session.get(json_url, auth=auth) as resp:
                    if resp.status == 404:
                        raise FileNotFoundError
                    if resp.status in (401, 403):
                        raise ApexFusionAuthError("Invalid auth for Apex status.json")
                    resp.raise_for_status()
                    body = await resp.text()

            any_obj: Any = json.loads(body) if body else {}
            if not isinstance(any_obj, dict):
                raise ApexFusionParseError("CGI JSON response was not an object")
            data = payloads.parse_status_cgi_json(cast(dict[str, Any], any_obj))
            finalize_trident(data)
            return data
        except FileNotFoundError:
            pass
        except (asyncio.TimeoutError, aiohttp.ClientError, json.JSONDecodeError) as err:
            raise ApexFusionTransportError(
                f"Error fetching/parsing Apex status.json: {err}"
            ) from err

        # Fall back to XML status.
        try:
            async with async_timeout.timeout(self.timeout_seconds):
                async with self.session.get(url, auth=auth) as resp:
                    if resp.status in (401, 403):
                        raise ApexFusionAuthError("Invalid auth for Apex status.xml")
                    resp.raise_for_status()
                    xml_text = await resp.text()
            data = payloads.parse_status_xml(xml_text)
            finalize_trident(data)
            return data
        except (asyncio.TimeoutError, aiohttp.ClientError, ET.ParseError) as err:
            raise ApexFusionTransportError(
                f"Error fetching/parsing Apex status.xml: {err}"
            ) from err

    async def _async_fetch_status_via_rest(self, *, base_url: str) -> dict[str, Any]:
        self._assert_rest_available()

        accept_headers = {
            "Accept": "*/*",
            "Content-Type": "application/json",
        }

        def _candidate_status_urls() -> list[str]:
            if self._rest_status_path:
                return [f"{base_url}{self._rest_status_path}"]
            return [f"{base_url}/rest/status"]

        def _cookie_headers(sid: str | None) -> dict[str, str]:
            headers = dict(accept_headers)
            if sid:
                headers["Cookie"] = f"connect.sid={sid}"
            return headers

        class _RestStatusUnauthorized(Exception):
            """REST status endpoint rejected the session."""

        async def _fetch_rest_status(
            sid: str | None, *, status_url: str
        ) -> dict[str, Any] | None:
            async with async_timeout.timeout(self.timeout_seconds):
                async with self.session.get(
                    status_url, headers=_cookie_headers(sid)
                ) as resp:
                    if resp.status == 404:
                        raise ApexFusionNotSupportedError(
                            "REST status endpoint not found"
                        )
                    if resp.status in (401, 403):
                        raise _RestStatusUnauthorized
                    if resp.status == 429:
                        retry_after = self._parse_retry_after_seconds(resp.headers)
                        raise ApexFusionRateLimitedError(
                            "REST status rate limited",
                            retry_after_seconds=retry_after,
                        )
                    if _is_transient_http_status(resp.status):
                        raise ApexFusionTransportError(
                            f"Transient REST status HTTP error (status={resp.status})"
                        )
                    resp.raise_for_status()
                    text = await resp.text()

            any_obj: Any = json.loads(text) if text else {}
            if not isinstance(any_obj, dict):
                raise ApexFusionParseError("REST status response was not an object")
            return cast(dict[str, Any], any_obj)

        sid: str | None = None
        # If a cookie is already present, try once without logging in.
        if _session_has_connect_sid(self.session, base_url):
            sid_m = self.session.cookie_jar.filter_cookies(URL(base_url)).get(
                "connect.sid"
            )
            sid = sid_m.value if sid_m is not None else None

        for status_url in _candidate_status_urls():
            try:
                raw = await _fetch_rest_status(sid, status_url=status_url)
                if raw is None:
                    continue
                self._rest_status_path = URL(status_url).path
                data = payloads.parse_status_rest(raw)
                return data
            except _RestStatusUnauthorized:
                # Force login and retry once.
                sid = await self._async_rest_login()
                raw = await _fetch_rest_status(sid, status_url=status_url)
                if raw is None:
                    continue
                self._rest_status_path = URL(status_url).path
                data = payloads.parse_status_rest(raw)
                return data
            except ApexFusionRateLimitedError as err:
                backoff = (
                    float(err.retry_after_seconds)
                    if err.retry_after_seconds is not None
                    else 300.0
                )
                self._disable_rest(seconds=backoff)
                raise

        raise ApexFusionTransportError("REST status fetch failed")

"""Config flow for Apex Fusion (Local)."""

from __future__ import annotations

import asyncio
import json
import logging
import xml.etree.ElementTree as ET
from http import HTTPStatus
from typing import Any, cast
from urllib.parse import urlparse

import aiohttp
import async_timeout
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from yarl import URL

from .const import (
    CONF_HOST,
    DEFAULT_PASSWORD,
    DEFAULT_STATUS_PATH,
    DEFAULT_USERNAME,
    DOMAIN,
    LOGGER_NAME,
)
from .coordinator import build_base_url, build_status_url

_LOGGER = logging.getLogger(LOGGER_NAME)


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


STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_USERNAME, default=DEFAULT_USERNAME): str,
        vol.Optional(CONF_PASSWORD, default=DEFAULT_PASSWORD): str,
    }
)


STEP_REAUTH_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_USERNAME, default=DEFAULT_USERNAME): str,
        vol.Optional(CONF_PASSWORD, default=DEFAULT_PASSWORD): str,
    }
)


def _normalize_host(host: str) -> str:
    """Normalize a host field to a hostname/IP.

    Users sometimes paste URLs (e.g., http://10.0.0.5). This integration stores
    only the host portion and assumes http.

    Args:
        host: Raw host input.

    Returns:
        Hostname/IP without scheme/path.
    """
    raw = (host or "").strip()
    if not raw:
        return raw

    if raw.startswith("http://") or raw.startswith("https://"):
        parsed = urlparse(raw)
        return (parsed.hostname or parsed.netloc or raw).strip()

    # If someone typed a bare URL-ish value without scheme, keep as-is.
    return raw


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""


async def _async_validate_input(
    hass: HomeAssistant, data: dict[str, Any]
) -> dict[str, str]:
    """Validate user input.

    Tries REST first (if a password is provided), then falls back to
    legacy status.xml.

    Args:
        hass: Home Assistant instance.
        data: User-provided config data.

    Returns:
        A dict containing a display title and unique_id.

    Raises:
        CannotConnect: If the device cannot be reached.
        InvalidAuth: If authentication fails.
    """
    host = _normalize_host(str(data[CONF_HOST]))
    username = str(data.get(CONF_USERNAME, DEFAULT_USERNAME) or DEFAULT_USERNAME)
    password = str(data.get(CONF_PASSWORD, DEFAULT_PASSWORD) or "")
    status_path = DEFAULT_STATUS_PATH

    _LOGGER.debug(
        "Validating Apex connection host=%s user=%s has_password=%s",
        host,
        username,
        bool(password),
    )

    base_url = build_base_url(host)
    url = build_status_url(host, status_path)
    session = async_get_clientsession(hass)

    auth: aiohttp.BasicAuth | None = None
    if password:
        auth = aiohttp.BasicAuth(username or "admin", password)

    # Prefer REST if present; fall back to XML.
    rest_invalid_auth = False

    if password:
        try:
            login_url = f"{base_url}/rest/login"
            accept_headers = {"Accept": "*/*", "Content-Type": "application/json"}

            max_attempts = 2
            for attempt in range(1, max_attempts + 1):
                _LOGGER.debug(
                    "REST validation attempt %s/%s host=%s user=%s",
                    attempt,
                    max_attempts,
                    host,
                    username,
                )

                try:
                    login_cookie_sid = ""
                    login_body = ""

                    login_candidates: list[str] = []
                    if username:
                        login_candidates.append(username)
                    if "admin" not in login_candidates:
                        login_candidates.append("admin")

                    logged_in = False
                    for login_user in login_candidates:
                        async with async_timeout.timeout(10):
                            async with session.post(
                                login_url,
                                json={
                                    "login": login_user,
                                    "password": password,
                                    "remember_me": False,
                                },
                                headers=accept_headers,
                            ) as resp:
                                _LOGGER.debug(
                                    "REST login HTTP %s content_type=%s",
                                    resp.status,
                                    resp.headers.get("Content-Type"),
                                )
                                if resp.status == 404:
                                    raise KeyError("rest_not_supported")
                                if resp.status in (401, 403):
                                    _LOGGER.debug(
                                        "REST login rejected for user=%s; trying next candidate",
                                        login_user,
                                    )
                                    continue
                                if _is_transient_http_status(resp.status):
                                    raise CannotConnect
                                resp.raise_for_status()
                                login_body = await resp.text()

                                morsel = resp.cookies.get("connect.sid")
                                if morsel is not None and morsel.value:
                                    login_cookie_sid = morsel.value
                                logged_in = True
                                break

                    if not logged_in:
                        # Some devices/users may not permit REST login but still
                        # allow legacy status.xml BasicAuth access.
                        rest_invalid_auth = True
                        raise CannotConnect

                    sid_set = False
                    sid_value = ""
                    if login_cookie_sid:
                        _set_connect_sid_cookie(
                            session, base_url=base_url, sid=login_cookie_sid
                        )
                        sid_set = True
                        sid_value = login_cookie_sid

                    sid_set = sid_set or _session_has_connect_sid(session, base_url)
                    if not sid_set and login_body:
                        try:
                            login_any: Any = json.loads(login_body)
                            if isinstance(login_any, dict):
                                sid_any: Any = cast(dict[str, Any], login_any).get(
                                    "connect.sid"
                                )
                                if isinstance(sid_any, str) and sid_any:
                                    _set_connect_sid_cookie(
                                        session, base_url=base_url, sid=sid_any
                                    )
                                    sid_set = True
                                    sid_value = sid_any
                        except json.JSONDecodeError:
                            pass

                    _LOGGER.debug(
                        "REST login session established=%s (will_send_cookie_header=%s)",
                        sid_set,
                        bool(sid_value),
                    )

                    request_headers = dict(accept_headers)
                    if sid_value:
                        request_headers["Cookie"] = f"connect.sid={sid_value}"

                    status_urls = [
                        f"{base_url}/rest/status",
                    ]

                    status_text = ""
                    status_ok = False
                    for status_url in status_urls:
                        async with async_timeout.timeout(10):
                            async with session.get(
                                status_url, headers=request_headers
                            ) as resp:
                                _LOGGER.debug(
                                    "REST status HTTP %s content_type=%s has_connect_sid=%s",
                                    resp.status,
                                    resp.headers.get("Content-Type"),
                                    _session_has_connect_sid(session, base_url),
                                )
                                if resp.status == 404:
                                    continue
                                if resp.status in (401, 403):
                                    rest_invalid_auth = True
                                    raise CannotConnect
                                if _is_transient_http_status(resp.status):
                                    raise CannotConnect
                                resp.raise_for_status()
                                status_text = await resp.text()
                                status_ok = True
                                break

                    if not status_ok:
                        raise KeyError("rest_not_supported")

                    # Ensure it's JSON.
                    json.loads(status_text) if status_text else {}

                    title = f"Apex ({host})"
                    return {"title": title, "unique_id": host}

                except (asyncio.TimeoutError, aiohttp.ClientError) as err:
                    _LOGGER.debug("Transient REST validation error: %s", err)
                    if attempt < max_attempts:
                        await asyncio.sleep(0.5 * attempt)

            raise CannotConnect

        except KeyError:
            # No REST, try XML.
            _LOGGER.debug("REST not supported; falling back to status.xml")
            pass
        except InvalidAuth:
            # Reserved for legacy XML auth failures below.
            raise
        except (CannotConnect, json.JSONDecodeError) as err:
            # REST flaky? Try XML before failing.
            _LOGGER.debug("REST validation failed; trying status.xml: %s", err)

    try:
        _LOGGER.debug("Trying legacy XML validation: %s", url)
        async with async_timeout.timeout(10):
            async with session.get(url, auth=auth) as resp:
                _LOGGER.debug("XML status HTTP %s", resp.status)
                if resp.status in (401, 403):
                    raise InvalidAuth
                resp.raise_for_status()
                body = await resp.text()

        ET.fromstring(body)

    except InvalidAuth:
        if rest_invalid_auth:
            _LOGGER.debug(
                "REST login rejected and legacy XML auth failed host=%s user=%s",
                host,
                username,
            )
        raise
    except (asyncio.TimeoutError, aiohttp.ClientError, ET.ParseError) as err:
        raise CannotConnect from err

    title = f"Apex ({host})"
    return {"title": title, "unique_id": host}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Apex Fusion."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step.

        Args:
            user_input: User-provided input, if any.

        Returns:
            A Home Assistant flow result.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await _async_validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(info["unique_id"])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    async def async_step_reauth(self, user_input: dict[str, Any]) -> ConfigFlowResult:
        """Handle config entry re-authentication.

        Args:
            user_input: Context from Home Assistant, including `entry_id`.

        Returns:
            A Home Assistant flow result.
        """
        # NOTE: Home Assistant reserves `_reauth_entry_id` on ConfigFlow.
        self._apex_reauth_entry_id = str(user_input.get("entry_id") or "") or None
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Prompt for updated credentials.

        Args:
            user_input: Updated credentials, if submitted.

        Returns:
            A Home Assistant flow result.
        """
        entry_id = getattr(self, "_apex_reauth_entry_id", None)
        if not entry_id:
            return self.async_abort(reason="unknown")

        entry = self.hass.config_entries.async_get_entry(entry_id)
        if entry is None:
            return self.async_abort(reason="unknown")

        errors: dict[str, str] = {}

        if user_input is not None:
            merged: dict[str, Any] = dict(entry.data)
            merged.update(user_input)
            try:
                await _async_validate_input(self.hass, merged)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected exception during reauth")
                errors["base"] = "unknown"
            else:
                self.hass.config_entries.async_update_entry(entry, data=merged)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_SCHEMA,
            errors=errors,
            description_placeholders={CONF_HOST: str(entry.data.get(CONF_HOST, ""))},
        )

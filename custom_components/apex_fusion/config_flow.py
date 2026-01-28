"""Config flow for Apex Fusion (Local)."""

from __future__ import annotations

import asyncio
import json
import logging
import xml.etree.ElementTree as ET
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

from .const import (
    CONF_HOST,
    DEFAULT_PASSWORD,
    DEFAULT_STATUS_PATH,
    DEFAULT_USERNAME,
    DOMAIN,
)
from .coordinator import build_base_url, build_status_url

_LOGGER = logging.getLogger(DOMAIN)


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
    if password:
        try:
            login_url = f"{base_url}/rest/login"
            status_url = f"{base_url}/rest/status/data"

            _LOGGER.debug("Trying REST validation: %s", status_url)

            async with async_timeout.timeout(10):
                async with session.post(
                    login_url,
                    json={
                        "login": username or "admin",
                        "password": password,
                        "remember_me": False,
                    },
                    headers={"Accept": "application/json"},
                ) as resp:
                    _LOGGER.debug("REST login HTTP %s", resp.status)
                    if resp.status == 404:
                        raise KeyError("rest_not_supported")
                    if resp.status in (401, 403):
                        raise InvalidAuth
                    resp.raise_for_status()
                    login_body = await resp.text()

            cookie_header: dict[str, str] = {"Accept": "application/json"}
            try:
                login_any: Any = json.loads(login_body) if login_body else {}
                if isinstance(login_any, dict):
                    login_dict = cast(dict[str, Any], login_any)
                    sid_any: Any = login_dict.get("connect.sid")
                    if isinstance(sid_any, str) and sid_any:
                        cookie_header["Cookie"] = f"connect.sid={sid_any}"
            except Exception:
                pass

            async with async_timeout.timeout(10):
                async with session.get(status_url, headers=cookie_header) as resp:
                    _LOGGER.debug("REST status HTTP %s", resp.status)
                    if resp.status == 404:
                        raise KeyError("rest_not_supported")
                    if resp.status in (401, 403):
                        raise InvalidAuth
                    resp.raise_for_status()
                    status_text = await resp.text()

            # Ensure it's JSON.
            json.loads(status_text) if status_text else {}

            title = f"Apex ({host})"
            return {"title": title, "unique_id": host}

        except KeyError:
            # No REST, try XML.
            _LOGGER.debug("REST not supported; falling back to status.xml")
            pass
        except InvalidAuth:
            _LOGGER.debug("REST auth failed for host=%s user=%s", host, username)
            raise
        except (asyncio.TimeoutError, aiohttp.ClientError, json.JSONDecodeError) as err:
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
        raise
    except (asyncio.TimeoutError, aiohttp.ClientError, ET.ParseError) as err:
        raise CannotConnect from err

    title = f"Apex ({host})"
    return {"title": title, "unique_id": host}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Apex Fusion."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._reauth_entry_id: str | None = None

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
        self._reauth_entry_id = str(user_input.get("entry_id") or "") or None
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
        if not self._reauth_entry_id:
            return self.async_abort(reason="unknown")

        entry = self.hass.config_entries.async_get_entry(self._reauth_entry_id)
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

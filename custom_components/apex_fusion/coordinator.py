"""Coordinator for fetching/parsing Apex controller state.

Strategy:
- Prefer the newer REST API if present and credentials work.
- Fall back to legacy `status.xml` if REST is unavailable.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import xml.etree.ElementTree as ET
from typing import Any, cast

import aiohttp
import async_timeout
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_STATUS_PATH,
    DEFAULT_TIMEOUT_SECONDS,
    DOMAIN,
)

_LOGGER = logging.getLogger(DOMAIN)


class _RestNotSupported(Exception):
    """Internal signal used to fall back to legacy XML."""


_MXM_STATUS_LINE = re.compile(
    r"^\s*(?P<name>[^\(]+)\([^\)]*\)\s*-\s*Rev\s+(?P<rev>[^\s]+)\s+Ser\s+#:\s+(?P<serial>[^\s]+)\s+-\s*(?P<status>.+?)\s*$"
)


def _parse_mxm_devices_from_mconf(
    mconf_obj: dict[str, Any],
) -> dict[str, dict[str, str]]:
    """Extract MXM device metadata from `/rest/config/mconf`.

    The MXM module includes a multiline `extra.status` string listing attached
    devices with revision and serial numbers.

    Args:
        mconf_obj: Parsed JSON from `/rest/config/mconf`.

    Returns:
        Mapping of device name -> metadata dict.
    """
    out: dict[str, dict[str, str]] = {}

    mconf_any: Any = mconf_obj.get("mconf")
    if not isinstance(mconf_any, list):
        return out

    for module_any in cast(list[Any], mconf_any):
        if not isinstance(module_any, dict):
            continue
        module = cast(dict[str, Any], module_any)
        if str(module.get("hwtype") or "").strip().upper() != "MXM":
            continue
        extra_any: Any = module.get("extra")
        if not isinstance(extra_any, dict):
            continue
        extra = cast(dict[str, Any], extra_any)
        status_text_any: Any = extra.get("status")
        if not isinstance(status_text_any, str) or not status_text_any.strip():
            continue
        for line in status_text_any.splitlines():
            match = _MXM_STATUS_LINE.match(line)
            if not match:
                continue
            name = match.group("name").strip()
            if not name:
                continue
            out[name] = {
                "rev": match.group("rev").strip(),
                "serial": match.group("serial").strip(),
                "status": match.group("status").strip(),
            }

    return out


def _to_number(s: str | None) -> float | None:
    """Convert a string to a float if possible.

    Args:
        s: Input string.

    Returns:
        Parsed float, or None if not parseable.
    """
    if s is None:
        return None
    t = s.strip()
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def build_status_url(host: str, status_path: str) -> str:
    """Build a full URL to the legacy status endpoint.

    Args:
        host: Hostname or URL.
        status_path: Path to status endpoint.

    Returns:
        Fully-qualified URL.
    """
    host = (host or "").strip()
    if host.startswith("http://") or host.startswith("https://"):
        base = host.rstrip("/")
    else:
        base = f"http://{host}".rstrip("/")

    path = (status_path or DEFAULT_STATUS_PATH).strip()
    if not path.startswith("/"):
        path = "/" + path

    return base + path


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


def parse_status_xml(xml_text: str) -> dict[str, Any]:
    """Parse legacy `status.xml` into a normalized dict.

    Args:
        xml_text: Raw XML text.

    Returns:
        Normalized dict containing at least: meta, probes, outlets.
    """
    root = ET.fromstring(xml_text)

    meta: dict[str, Any] = {
        "software": (root.attrib.get("software") or "").strip() or None,
        "hardware": (root.attrib.get("hardware") or "").strip() or None,
        "hostname": (root.findtext("./hostname") or "").strip() or None,
        "serial": (root.findtext("./serial") or "").strip() or None,
        "timezone": (root.findtext("./timezone") or "").strip() or None,
        "date": (root.findtext("./date") or "").strip() or None,
    }

    probes: dict[str, dict[str, Any]] = {}
    for p in root.findall("./probes/probe"):
        name = (p.findtext("name") or "").strip()
        if not name:
            continue
        value_raw = p.findtext("value")
        probes[name] = {
            "name": name,
            "type": (p.findtext("type") or "").strip() or None,
            "value_raw": (value_raw.strip() if value_raw else None),
            "value": _to_number(value_raw),
        }

    outlets: list[dict[str, Any]] = []
    for o in root.findall("./outlets/outlet"):
        name = (o.findtext("name") or "").strip()
        if not name:
            continue
        outlets.append(
            {
                "name": name,
                "output_id": (o.findtext("outputID") or "").strip() or None,
                "state": (o.findtext("state") or "").strip() or None,
                "device_id": (o.findtext("deviceID") or "").strip() or None,
            }
        )

    return {"meta": meta, "probes": probes, "outlets": outlets}


def parse_status_rest(status_obj: dict[str, Any]) -> dict[str, Any]:
    """Parse REST status JSON into a normalized dict.

    This integration primarily uses `/rest/status/data` because it contains both
    probe/output state and richer controller metadata (system + network).

    Args:
        status_obj: Parsed JSON dict from `/rest/status/data`.

    Returns:
        Normalized dict containing at least: meta, probes, outlets, network, raw.
    """
    nstat_any: Any = status_obj.get("nstat")
    nstat: dict[str, Any] = {}
    if isinstance(nstat_any, dict):
        nstat = cast(dict[str, Any], nstat_any)

    system_any: Any = status_obj.get("system")
    system: dict[str, Any] = {}
    if isinstance(system_any, dict):
        system = cast(dict[str, Any], system_any)

    meta: dict[str, Any] = {
        "software": (str(system.get("software") or "").strip() or None),
        "hardware": (str(system.get("hardware") or "").strip() or None),
        "hostname": (
            str(system.get("hostname") or nstat.get("hostname") or "").strip() or None
        ),
        "serial": (str(system.get("serial") or "").strip() or None),
        "timezone": (str(system.get("timezone") or "").strip() or None),
        "date": system.get("date"),
        "type": (str(system.get("type") or "").strip() or None),
        "firmware_latest": (str(nstat.get("latestFirmware") or "").strip() or None),
        "source": "rest",
    }

    network: dict[str, Any] = {
        "ipaddr": (str(nstat.get("ipaddr") or "").strip() or None),
        "gateway": (str(nstat.get("gateway") or "").strip() or None),
        "netmask": (str(nstat.get("netmask") or "").strip() or None),
        "dhcp": nstat.get("dhcp"),
        "wifi_enable": nstat.get("wifiEnable"),
        "ssid": nstat.get("ssid"),
        "strength": nstat.get("strength"),
        "quality": nstat.get("quality"),
    }

    probes: dict[str, dict[str, Any]] = {}
    inputs_any: Any = status_obj.get("inputs")
    if isinstance(inputs_any, list):
        for item_any in cast(list[Any], inputs_any):
            if not isinstance(item_any, dict):
                continue
            item = cast(dict[str, Any], item_any)
            did_any: Any = item.get("did")
            did = did_any if isinstance(did_any, str) else None
            if not isinstance(did, str) or not did:
                continue
            value: Any = item.get("value")
            probes[did] = {
                "name": (str(item.get("name") or did)).strip(),
                "type": (str(item.get("type") or "")).strip() or None,
                "value_raw": value,
                "value": value,
            }

    outlets: list[dict[str, Any]] = []
    outputs_any: Any = status_obj.get("outputs")
    if isinstance(outputs_any, list):
        for item_any in cast(list[Any], outputs_any):
            if not isinstance(item_any, dict):
                continue
            item = cast(dict[str, Any], item_any)
            did_any: Any = item.get("did")
            did = did_any if isinstance(did_any, str) else None
            if not isinstance(did, str) or not did:
                continue
            status_any: Any = item.get("status")
            state: str | None = None
            if isinstance(status_any, list) and status_any:
                first: Any = cast(list[Any], status_any)[0]
                state = str(first) if first is not None else None

            output_type_any: Any = item.get("type")
            output_type = output_type_any if isinstance(output_type_any, str) else None

            gid_any: Any = item.get("gid")
            gid = gid_any if isinstance(gid_any, str) else None

            outlets.append(
                {
                    "name": (str(item.get("name") or did)).strip(),
                    "output_id": str(item.get("ID") or "").strip() or None,
                    "state": (state or "").strip() or None,
                    "device_id": did,
                    "type": (output_type or "").strip() or None,
                    "gid": (gid or "").strip() or None,
                    "status": status_any if isinstance(status_any, list) else None,
                }
            )

    return {
        "meta": meta,
        "network": network,
        "probes": probes,
        "outlets": outlets,
        "raw": status_obj,
    }


def parse_status_cgi_json(status_obj: dict[str, Any]) -> dict[str, Any]:
    """Parse legacy `/cgi-bin/status.json` into a normalized dict.

    Args:
        status_obj: Parsed JSON dict from `/cgi-bin/status.json`.

    Returns:
        Normalized dict containing at least: meta, probes, outlets, raw.
    """
    istat_any: Any = status_obj.get("istat")
    istat: dict[str, Any] = {}
    if isinstance(istat_any, dict):
        istat = cast(dict[str, Any], istat_any)

    meta: dict[str, Any] = {
        "software": None,
        "hardware": (str(istat.get("hardware") or "").strip() or None),
        "hostname": (str(istat.get("hostname") or "").strip() or None),
        "serial": None,
        "timezone": None,
        "date": istat.get("date"),
        "type": None,
        "source": "cgi_json",
    }

    probes: dict[str, dict[str, Any]] = {}
    inputs_any: Any = istat.get("inputs")
    if isinstance(inputs_any, list):
        for item_any in cast(list[Any], inputs_any):
            if not isinstance(item_any, dict):
                continue
            item = cast(dict[str, Any], item_any)
            did_any: Any = item.get("did")
            did = did_any if isinstance(did_any, str) else None
            if not did:
                continue
            value: Any = item.get("value")
            probes[did] = {
                "name": (str(item.get("name") or did)).strip(),
                "type": (str(item.get("type") or "")).strip() or None,
                "value_raw": value,
                "value": value,
            }

    outlets: list[dict[str, Any]] = []
    outputs_any: Any = istat.get("outputs")
    if isinstance(outputs_any, list):
        for item_any in cast(list[Any], outputs_any):
            if not isinstance(item_any, dict):
                continue
            item = cast(dict[str, Any], item_any)
            did_any: Any = item.get("did")
            did = did_any if isinstance(did_any, str) else None
            if not did:
                continue
            status_any: Any = item.get("status")
            state: str | None = None
            if isinstance(status_any, list) and status_any:
                first: Any = cast(list[Any], status_any)[0]
                state = str(first) if first is not None else None

            output_type_any: Any = item.get("type")
            output_type = output_type_any if isinstance(output_type_any, str) else None

            gid_any: Any = item.get("gid")
            gid = gid_any if isinstance(gid_any, str) else None

            outlets.append(
                {
                    "name": (str(item.get("name") or did)).strip(),
                    "output_id": str(item.get("ID") or "").strip() or None,
                    "state": (state or "").strip() or None,
                    "device_id": did,
                    "type": (output_type or "").strip() or None,
                    "gid": (gid or "").strip() or None,
                    "status": status_any if isinstance(status_any, list) else None,
                }
            )

    return {"meta": meta, "probes": probes, "outlets": outlets, "raw": status_obj}


class ApexNeptuneDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetches and parses status.xml into a shared data dict."""

    def __init__(self, hass: HomeAssistant, *, entry: ConfigEntry) -> None:
        """Initialize the coordinator.

        Args:
            hass: Home Assistant instance.
            entry: Config entry containing connection details.
        """
        self.hass = hass
        self.entry = entry

        super().__init__(
            hass,
            _LOGGER,
            name=f"Apex Fusion ({entry.data.get(CONF_HOST, '')})",
            update_interval=DEFAULT_SCAN_INTERVAL,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch and parse controller status.

        Returns:
            Coordinator data dict.

        Raises:
            UpdateFailed: If updates fail in a non-recoverable way.
        """
        host = str(self.entry.data[CONF_HOST])
        username = str(self.entry.data.get(CONF_USERNAME, ""))
        password = str(self.entry.data.get(CONF_PASSWORD, ""))
        status_path = DEFAULT_STATUS_PATH
        base_url = build_base_url(host)
        url = build_status_url(host, status_path)

        _LOGGER.debug(
            "Coordinator update start host=%s user=%s has_password=%s",
            host,
            (username or "admin"),
            bool(password),
        )

        session = async_get_clientsession(self.hass)

        auth: aiohttp.BasicAuth | None = None
        if password:
            auth = aiohttp.BasicAuth(username or "admin", password)

        timeout_seconds = DEFAULT_TIMEOUT_SECONDS

        # Prefer REST when credentials exist; fall back to XML.
        if password:
            try:
                login_url = f"{base_url}/rest/login"
                status_url = f"{base_url}/rest/status/data"

                _LOGGER.debug("Trying REST update: %s", status_url)

                async with async_timeout.timeout(timeout_seconds):
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
                            raise _RestNotSupported
                        if resp.status in (401, 403):
                            raise ConfigEntryAuthFailed(
                                "Invalid auth for Apex REST API"
                            )
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

                async with async_timeout.timeout(timeout_seconds):
                    async with session.get(status_url, headers=cookie_header) as resp:
                        if resp.status == 404:
                            raise _RestNotSupported
                        if resp.status in (401, 403):
                            raise ConfigEntryAuthFailed(
                                "Invalid auth for Apex REST API"
                            )
                        resp.raise_for_status()
                        status_text = await resp.text()

                status_any: Any = json.loads(status_text) if status_text else {}
                if isinstance(status_any, dict):
                    data = parse_status_rest(cast(dict[str, Any], status_any))

                    # Optional: fetch module config for richer MXM device metadata.
                    try:
                        mconf_url = f"{base_url}/rest/config/mconf"
                        _LOGGER.debug("Trying REST mconf update: %s", mconf_url)
                        async with async_timeout.timeout(timeout_seconds):
                            async with session.get(
                                mconf_url, headers=cookie_header
                            ) as resp:
                                if resp.status == 404:
                                    raise FileNotFoundError
                                if resp.status in (401, 403):
                                    raise PermissionError
                                resp.raise_for_status()
                                mconf_text = await resp.text()

                        mconf_any: Any = json.loads(mconf_text) if mconf_text else {}
                        if isinstance(mconf_any, dict):
                            mxm_devices = _parse_mxm_devices_from_mconf(
                                cast(dict[str, Any], mconf_any)
                            )
                            if mxm_devices:
                                data["mxm_devices"] = mxm_devices
                    except (FileNotFoundError, PermissionError):
                        pass
                    except (
                        asyncio.TimeoutError,
                        aiohttp.ClientError,
                        json.JSONDecodeError,
                    ) as err:
                        _LOGGER.debug("REST mconf fetch failed: %s", err)
                    except Exception as err:
                        _LOGGER.debug("Unexpected REST mconf error: %s", err)

                    return data

            except _RestNotSupported:
                _LOGGER.debug("REST not supported; falling back to status.xml")
                pass
            except ConfigEntryAuthFailed:
                _LOGGER.warning(
                    "REST authentication failed for host=%s user=%s",
                    host,
                    (username or "admin"),
                )
                raise
            except UpdateFailed:
                raise
            except (
                asyncio.TimeoutError,
                aiohttp.ClientError,
                json.JSONDecodeError,
            ) as err:
                _LOGGER.debug("REST update failed; falling back to status.xml: %s", err)
            except Exception as err:
                _LOGGER.debug(
                    "Unexpected REST error; falling back to status.xml: %s", err
                )

        # Try legacy JSON first (richer metadata than status.xml).
        if True:
            json_url = f"{base_url}/cgi-bin/status.json"
            try:
                _LOGGER.debug("Trying legacy CGI JSON update: %s", json_url)
                async with async_timeout.timeout(timeout_seconds):
                    async with session.get(json_url, auth=auth) as resp:
                        if resp.status in (401, 403):
                            raise ConfigEntryAuthFailed(
                                "Invalid auth for Apex legacy status.json"
                            )
                        if resp.status == 404:
                            raise FileNotFoundError
                        resp.raise_for_status()
                        body = await resp.text()

                parsed_any: Any = json.loads(body) if body else {}
                if isinstance(parsed_any, dict):
                    data = parse_status_cgi_json(cast(dict[str, Any], parsed_any))
                    meta = data.get("meta")
                    if isinstance(meta, dict):
                        cast(dict[str, Any], meta).setdefault("source", "cgi_json")
                    return data

            except FileNotFoundError:
                _LOGGER.debug("Legacy CGI status.json not found; trying status.xml")
            except ConfigEntryAuthFailed:
                _LOGGER.warning(
                    "Legacy CGI JSON authentication failed for host=%s user=%s",
                    host,
                    (username or "admin"),
                )
                raise
            except (
                asyncio.TimeoutError,
                aiohttp.ClientError,
                json.JSONDecodeError,
            ) as err:
                _LOGGER.debug(
                    "Legacy CGI JSON update failed; trying status.xml: %s", err
                )
            except Exception as err:
                _LOGGER.debug("Unexpected CGI JSON error; trying status.xml: %s", err)

        try:
            _LOGGER.debug("Trying legacy XML update: %s", url)
            async with async_timeout.timeout(timeout_seconds):
                async with session.get(url, auth=auth) as resp:
                    if resp.status in (401, 403):
                        raise ConfigEntryAuthFailed(
                            "Invalid auth for Apex legacy status.xml"
                        )
                    resp.raise_for_status()
                    body = await resp.text()

            data = parse_status_xml(body)
            meta = data.get("meta")
            if isinstance(meta, dict):
                cast(dict[str, Any], meta).setdefault("source", "xml")
            return data

        except ConfigEntryAuthFailed:
            _LOGGER.warning(
                "Legacy XML authentication failed for host=%s user=%s",
                host,
                (username or "admin"),
            )
            raise
        except (asyncio.TimeoutError, aiohttp.ClientError, ET.ParseError) as err:
            raise UpdateFailed(
                f"Error fetching/parsing Apex status.xml: {err}"
            ) from err
        except UpdateFailed:
            raise
        except Exception as err:
            raise UpdateFailed(f"Unexpected error updating Apex data: {err}") from err


__all__ = [
    "ApexNeptuneDataUpdateCoordinator",
    "build_base_url",
    "build_status_url",
    "parse_status_rest",
    "parse_status_cgi_json",
    "parse_status_xml",
]

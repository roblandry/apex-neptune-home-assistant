"""REST config parsing and sanitization.

The controller's `/rest/config` payload is large and can include sensitive
material. The internal API sanitizes and extracts only the fields needed by
higher-level consumers (including the HA integration).

This module intentionally avoids Home Assistant imports.
"""

from __future__ import annotations

import re
from typing import Any, cast

_MXM_STATUS_LINE = re.compile(
    r"^\s*(?P<name>[^\(]+)\([^\)]*\)\s*-\s*Rev\s+(?P<rev>[^\s]+)\s+Ser\s+#:\s+(?P<serial>[^\s]+)\s+-\s*(?P<status>.+?)\s*$"
)


def parse_mxm_devices_from_mconf(
    mconf_obj: dict[str, Any],
) -> dict[str, dict[str, str]]:
    """Extract MXM attached-device metadata from `mconf`.

    Args:
        mconf_obj: Parsed JSON from `/rest/config` (expects an `mconf` list).

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


def sanitize_mconf_for_storage(mconf_obj: dict[str, Any]) -> list[dict[str, Any]]:
    """Sanitize `mconf` (from `/rest/config`) for storage.

    Args:
        mconf_obj: REST config payload object.

    Returns:
        Sanitized list of module config dicts.
    """

    mconf_any: Any = mconf_obj.get("mconf")
    if not isinstance(mconf_any, list):
        return []

    out: list[dict[str, Any]] = []
    for module_any in cast(list[Any], mconf_any):
        if not isinstance(module_any, dict):
            continue
        module = cast(dict[str, Any], module_any)

        hwtype = str(module.get("hwtype") or module.get("hwType") or "").strip().upper()
        if not hwtype:
            continue

        item: dict[str, Any] = {"hwtype": hwtype}

        abaddr_any: Any = module.get("abaddr")
        if isinstance(abaddr_any, int):
            item["abaddr"] = abaddr_any

        name_any: Any = module.get("name")
        if isinstance(name_any, str) and name_any.strip():
            item["name"] = name_any.strip()

        update_any: Any = module.get("update")
        if isinstance(update_any, bool):
            item["update"] = update_any

        update_stat_any: Any = module.get("updateStat")
        if isinstance(update_stat_any, int):
            item["updateStat"] = update_stat_any

        extra_any: Any = module.get("extra")
        if isinstance(extra_any, dict):
            extra = cast(dict[str, Any], extra_any)
            extra_out: dict[str, Any] = {}

            waste_any: Any = extra.get("wasteSize")
            if isinstance(waste_any, (int, float)):
                extra_out["wasteSize"] = float(waste_any)

            status_any: Any = extra.get("status")
            if hwtype == "MXM" and isinstance(status_any, str) and status_any.strip():
                extra_out["status"] = status_any

            if extra_out:
                item["extra"] = extra_out

        out.append(item)

    return out


def sanitize_nconf_for_storage(nconf_obj: dict[str, Any]) -> dict[str, Any]:
    """Sanitize `nconf` (from `/rest/config`) for storage.

    This payload commonly includes credentials. Keep only update-related fields.

    Args:
        nconf_obj: REST config payload object.

    Returns:
        Sanitized dict containing update-related controller fields.
    """

    nconf_any: Any = nconf_obj.get("nconf")
    if not isinstance(nconf_any, dict):
        return {}

    nconf = cast(dict[str, Any], nconf_any)
    out: dict[str, Any] = {}

    latest_any: Any = nconf.get("latestFirmware")
    if isinstance(latest_any, str) and latest_any.strip():
        out["latestFirmware"] = latest_any.strip()

    flag_any: Any = nconf.get("updateFirmware")
    if isinstance(flag_any, bool):
        out["updateFirmware"] = flag_any

    return out

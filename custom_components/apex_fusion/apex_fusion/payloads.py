"""Payload parsing and normalization.

The internal API package provides parsing helpers that convert controller payloads
into normalized, JSON-serializable dictionaries.

The normalized structures are designed to be stable for Home Assistant wiring:
- `meta`: controller identity and version fields
- `network`: controller network fields (REST sources)
- `probes`: mapping of probe/input ids -> normalized probe dict
- `outlets`: list of normalized outlet/output dicts
- `feed`: feed-mode status when present
- `alerts`: last-statement/message when present
- `trident`: Trident status and consumables fields when present
- `raw`: original payload (REST / CGI JSON sources)

This module intentionally avoids Home Assistant imports.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any, cast

_INPUT_DID_MODULE_ABADDR = re.compile(r"^(?P<abaddr>\d+)_")


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


def module_abaddr_from_input_did(did: str) -> int | None:
    """Extract module Aquabus address from an input DID like `5_I1` or `4_0`.

    Args:
        did: Device id token, commonly containing an address prefix.

    Returns:
        Aquabus address when the DID encodes one; otherwise `None`.
    """
    t = (did or "").strip()
    if not t:
        return None

    m = _INPUT_DID_MODULE_ABADDR.match(t)
    if not m:
        return None
    try:
        return int(m.group("abaddr"))
    except ValueError:
        return None


def parse_status_xml(xml_text: str) -> dict[str, Any]:
    """Parse `status.xml` into a normalized dict.

    Args:
        xml_text: Raw XML text.

    Returns:
        Normalized dict containing at least: meta, probes, outlets.

    Raises:
        xml.etree.ElementTree.ParseError: If XML is not well-formed.
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

    return {
        "meta": meta,
        "probes": probes,
        "outlets": outlets,
        "alerts": {"last_statement": None, "last_message": None},
        "trident": {"status": None, "is_testing": None},
    }


def parse_status_rest(status_obj: dict[str, Any]) -> dict[str, Any]:
    """Parse REST status JSON into a normalized dict.

    This integration uses `/rest/status` (and tolerates variants that nest the
    same data under keys like `status`, `data`, etc.).

    Args:
        status_obj: Parsed JSON dict from `/rest/status`.

    Returns:
        Normalized dict containing at least: meta, probes, outlets, network, raw.
    """

    def _find_field(root: dict[str, Any], key: str) -> Any:
        direct = root.get(key)
        if direct is not None:
            return direct

        for container_key in (
            "data",
            "status",
            "istat",
            "systat",
            "result",
        ):
            container_any: Any = root.get(container_key)
            if isinstance(container_any, dict):
                container = cast(dict[str, Any], container_any)
                nested = container.get(key)
                if nested is not None:
                    return nested
        return None

    nstat_any: Any = _find_field(status_obj, "nstat")
    nstat: dict[str, Any] = (
        cast(dict[str, Any], nstat_any) if isinstance(nstat_any, dict) else {}
    )

    system_any: Any = _find_field(status_obj, "system")
    system: dict[str, Any] = (
        cast(dict[str, Any], system_any) if isinstance(system_any, dict) else {}
    )

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

    def _coerce_id(item: dict[str, Any], *keys: str) -> str:
        for k in keys:
            v: Any = item.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        for k in keys:
            v = item.get(k)
            if isinstance(v, int):
                return str(v)
        return ""

    probes: dict[str, dict[str, Any]] = {}
    inputs_any: Any = _find_field(status_obj, "inputs")
    if not isinstance(inputs_any, list):
        inputs_any = _find_field(status_obj, "probes")
    if isinstance(inputs_any, list):
        for item_any in cast(list[Any], inputs_any):
            if not isinstance(item_any, dict):
                continue
            item = cast(dict[str, Any], item_any)
            did = _coerce_id(item, "did", "device_id", "deviceID", "id")
            if not did:
                did = _coerce_id(item, "name")
            if not did:
                continue

            module_abaddr: int | None = None
            module_abaddr_any: Any = (
                item.get("module_abaddr") or item.get("abaddr") or item.get("abAddr")
            )
            if module_abaddr_any is None and isinstance(item.get("module"), dict):
                module = cast(dict[str, Any], item.get("module"))
                module_abaddr_any = module.get("abaddr") or module.get("abAddr")
            if isinstance(module_abaddr_any, int):
                module_abaddr = module_abaddr_any

            if module_abaddr is None:
                module_abaddr = module_abaddr_from_input_did(did)

            module_hwtype: str | None = None
            module_hwtype_any: Any = (
                item.get("module_hwtype") or item.get("hwtype") or item.get("hwType")
            )
            if module_hwtype_any is None and isinstance(item.get("module"), dict):
                module = cast(dict[str, Any], item.get("module"))
                module_hwtype_any = module.get("hwtype") or module.get("hwType")
            if isinstance(module_hwtype_any, str) and module_hwtype_any.strip():
                module_hwtype = module_hwtype_any.strip().upper()

            value: Any = item.get("value")
            probes[did] = {
                "name": (str(item.get("name") or did)).strip(),
                "type": (str(item.get("type") or "")).strip() or None,
                "value_raw": value,
                "value": value,
                "module_abaddr": module_abaddr,
                "module_hwtype": module_hwtype,
            }

    outlets: list[dict[str, Any]] = []
    outputs_any: Any = _find_field(status_obj, "outputs")
    if not isinstance(outputs_any, list):
        outputs_any = _find_field(status_obj, "outlets")
    if isinstance(outputs_any, list):
        for item_any in cast(list[Any], outputs_any):
            if not isinstance(item_any, dict):
                continue
            item = cast(dict[str, Any], item_any)
            did = _coerce_id(item, "did", "device_id", "deviceID", "id")
            if not did:
                did = _coerce_id(item, "name")
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

            out_module_abaddr: int | None = None
            out_abaddr_any: Any = (
                item.get("module_abaddr")
                or item.get("abaddr")
                or item.get("abAddr")
                or item.get("moduleAbAddr")
            )
            if out_abaddr_any is None and isinstance(item.get("module"), dict):
                module = cast(dict[str, Any], item.get("module"))
                out_abaddr_any = module.get("abaddr") or module.get("abAddr")
            if isinstance(out_abaddr_any, int):
                out_module_abaddr = out_abaddr_any

            if out_module_abaddr is None:
                out_module_abaddr = module_abaddr_from_input_did(did)

            out_module_hwtype: str | None = None
            out_hwtype_any: Any = (
                item.get("module_hwtype")
                or item.get("hwtype")
                or item.get("hwType")
                or item.get("moduleHwType")
            )
            if out_hwtype_any is None and isinstance(item.get("module"), dict):
                module = cast(dict[str, Any], item.get("module"))
                out_hwtype_any = module.get("hwtype") or module.get("hwType")
            if isinstance(out_hwtype_any, str) and out_hwtype_any.strip():
                out_module_hwtype = out_hwtype_any.strip().upper()

            intensity_any: Any = item.get("intensity")
            intensity: int | None = None
            if isinstance(intensity_any, int) and not isinstance(intensity_any, bool):
                intensity = intensity_any
            elif isinstance(intensity_any, float) and intensity_any.is_integer():
                intensity = int(intensity_any)
            elif isinstance(intensity_any, str) and intensity_any.strip().isdigit():
                intensity = int(intensity_any.strip())

            module_abaddr = out_module_abaddr

            outlets.append(
                {
                    "name": (str(item.get("name") or did)).strip(),
                    "output_id": (
                        str(item.get("ID") or item.get("output_id") or "").strip()
                        or None
                    ),
                    "state": (state or "").strip() or None,
                    "device_id": did,
                    "type": (output_type or "").strip() or None,
                    "gid": (gid or "").strip() or None,
                    "status": status_any if isinstance(status_any, list) else None,
                    "intensity": intensity,
                    "module_abaddr": module_abaddr,
                    "module_hwtype": out_module_hwtype,
                }
            )

    def _parse_trident_from_modules() -> dict[str, Any]:
        def _coerce_percent(value: Any) -> int | None:
            if value is None:
                return None
            if isinstance(value, bool):
                return None
            if isinstance(value, (int, float)):
                n = int(value)
                return n if 0 <= n <= 100 else None
            t = str(value).strip()
            if not t:
                return None
            if t.endswith("%"):
                t = t[:-1].strip()
            if not t.isdigit():
                return None
            n = int(t)
            return n if 0 <= n <= 100 else None

        def _flatten(d: dict[str, Any], *, prefix: str = "") -> list[tuple[str, Any]]:
            out: list[tuple[str, Any]] = []
            for k, v in d.items():
                key = f"{prefix}{k}" if not prefix else f"{prefix}_{k}"
                if isinstance(v, dict):
                    out.extend(_flatten(cast(dict[str, Any], v), prefix=key))
                else:
                    out.append((key, v))
            return out

        def _extract_consumables(extra: dict[str, Any]) -> dict[str, Any]:
            reagent_a: int | None = None
            reagent_b: int | None = None
            reagent_c: int | None = None
            waste_level: int | None = None

            reagents_any: Any = extra.get("reagents")
            if isinstance(reagents_any, (list, tuple)):
                reagents_list: list[Any]
                if isinstance(reagents_any, list):
                    reagents_list = cast(list[Any], reagents_any)
                else:
                    reagents_list = list(cast(tuple[Any, ...], reagents_any))

                if len(reagents_list) >= 3:
                    reagent_a = _coerce_percent(reagents_list[0])
                    reagent_b = _coerce_percent(reagents_list[1])
                    reagent_c = _coerce_percent(reagents_list[2])

            for key, value in _flatten(extra):
                k = str(key).strip().lower().replace(" ", "_")
                p = _coerce_percent(value)
                if p is None:
                    continue

                if "reagent" in k:
                    if reagent_a is None and (
                        "reagenta" in k
                        or "reagent_a" in k
                        or "reagent1" in k
                        or "reagent_1" in k
                        or "reagent-1" in k
                    ):
                        reagent_a = p
                        continue
                    if reagent_b is None and (
                        "reagentb" in k
                        or "reagent_b" in k
                        or "reagent2" in k
                        or "reagent_2" in k
                        or "reagent-2" in k
                    ):
                        reagent_b = p
                        continue
                    if reagent_c is None and (
                        "reagentc" in k
                        or "reagent_c" in k
                        or "reagent3" in k
                        or "reagent_3" in k
                        or "reagent-3" in k
                    ):
                        reagent_c = p
                        continue

                if (
                    waste_level is None
                    and "waste" in k
                    and any(token in k for token in ("level", "pct", "percent"))
                ):
                    waste_level = p

            return {
                "reagent_a_remaining": reagent_a,
                "reagent_b_remaining": reagent_b,
                "reagent_c_remaining": reagent_c,
                "waste_container_level": waste_level,
            }

        modules_any: Any = _find_field(status_obj, "modules")
        if not isinstance(modules_any, list):
            return {
                "present": False,
                "status": None,
                "is_testing": None,
                "abaddr": None,
                "reagent_a_remaining": None,
                "reagent_b_remaining": None,
                "reagent_c_remaining": None,
                "waste_container_level": None,
                "levels_ml": None,
            }

        best_status: str | None = None
        present = False
        abaddr: int | None = None
        levels_ml: list[float] | None = None
        trident_hwtype: str | None = None
        trident_hwrev: str | None = None
        trident_swrev: str | None = None
        trident_serial: str | None = None
        consumables: dict[str, Any] = {
            "reagent_a_remaining": None,
            "reagent_b_remaining": None,
            "reagent_c_remaining": None,
            "waste_container_level": None,
        }
        for module_any in cast(list[Any], modules_any):
            if not isinstance(module_any, dict):
                continue
            module = cast(dict[str, Any], module_any)
            hwtype = (
                str(
                    module.get("hwtype")
                    or module.get("hwType")
                    or module.get("type")
                    or ""
                )
                .strip()
                .upper()
            )

            extra_any: Any = module.get("extra")
            if not isinstance(extra_any, dict):
                continue
            extra = cast(dict[str, Any], extra_any)

            # TODO: Identify ACTUAL Triden NP hwtype; requires dump (Issue: https://github.com/roblandry/apex-fusion-home-assistant/issues/4)
            if hwtype not in {"TRI", "TNP"}:
                continue

            trident_hwtype = hwtype or None

            hwrev_any: Any = (
                module.get("hwrev")
                or module.get("hwRev")
                or module.get("hw_version")
                or module.get("hwVersion")
                or module.get("rev")
            )
            if isinstance(hwrev_any, (str, int, float)):
                t = str(hwrev_any).strip()
                trident_hwrev = t or trident_hwrev

            swrev_any: Any = (
                module.get("software")
                or module.get("swrev")
                or module.get("swRev")
                or module.get("sw_version")
                or module.get("swVersion")
            )
            if isinstance(swrev_any, (str, int, float)):
                t = str(swrev_any).strip()
                trident_swrev = t or trident_swrev

            serial_any: Any = (
                module.get("serial")
                or module.get("serialNo")
                or module.get("serialNO")
                or module.get("serial_number")
            )
            if isinstance(serial_any, (str, int, float)):
                t = str(serial_any).strip()
                trident_serial = t or trident_serial

            abaddr_any: Any = module.get("abaddr")
            if isinstance(abaddr_any, int):
                abaddr = abaddr_any

            present_any: Any = module.get("present")
            present = bool(present_any) if isinstance(present_any, bool) else True

            levels_any: Any = extra.get("levels")
            if isinstance(levels_any, list):
                parsed_levels: list[float] = []
                for item_any in cast(list[Any], levels_any):
                    if item_any is None or isinstance(item_any, bool):
                        continue
                    if isinstance(item_any, (int, float)):
                        parsed_levels.append(float(item_any))
                        continue
                    if isinstance(item_any, str):
                        n = _to_number(item_any)
                        if n is not None:
                            parsed_levels.append(n)
                levels_ml = parsed_levels or None

            consumables = _extract_consumables(extra)

            status_any: Any = extra.get("status")
            if not isinstance(status_any, str):
                break
            status = status_any.strip()
            if not status:
                break

            if status.lower().startswith("testing"):
                status = "Testing" + status[7:]

            if status.isalpha():
                if status.isupper() and len(status) <= 3:
                    status = status
                else:
                    status = status[:1].upper() + status[1:].lower()

            best_status = status
            break

        if best_status is None:
            return {
                "present": present,
                "status": None,
                "is_testing": None,
                "abaddr": abaddr,
                "hwtype": trident_hwtype,
                "hwrev": trident_hwrev,
                "swrev": trident_swrev,
                "serial": trident_serial,
                "levels_ml": levels_ml,
                **consumables,
            }

        lower = best_status.lower()
        is_testing = "testing" in lower
        return {
            "present": present,
            "status": best_status,
            "is_testing": is_testing,
            "abaddr": abaddr,
            "hwtype": trident_hwtype,
            "hwrev": trident_hwrev,
            "swrev": trident_swrev,
            "serial": trident_serial,
            "levels_ml": levels_ml,
            **consumables,
        }

    def _parse_last_alert_statement() -> dict[str, Any]:
        for key in ("notifications", "alerts", "alarms", "warnings", "messages"):
            items_any: Any = _find_field(status_obj, key)
            if not isinstance(items_any, list) or not items_any:
                continue
            last_any: Any = cast(list[Any], items_any)[-1]
            if isinstance(last_any, dict):
                last = cast(dict[str, Any], last_any)
                statement_any: Any = (
                    last.get("statement")
                    or last.get("Statement")
                    or last.get("detail")
                    or last.get("details")
                )
                if isinstance(statement_any, str) and statement_any.strip():
                    return {
                        "last_statement": statement_any.strip(),
                        "last_message": None,
                    }

                message_any: Any = (
                    last.get("message")
                    or last.get("msg")
                    or last.get("text")
                    or last.get("title")
                )
                if isinstance(message_any, str) and message_any.strip():
                    msg = message_any.strip()
                    m = re.search(r"(?:^|\b)Statement:\s*(?P<s>.+)$", msg)
                    if m:
                        stmt = m.group("s").strip()
                        return {"last_statement": stmt or None, "last_message": msg}
                    return {"last_statement": None, "last_message": msg}

            if isinstance(last_any, str) and last_any.strip():
                msg = last_any.strip()
                m = re.search(r"(?:^|\b)Statement:\s*(?P<s>.+)$", msg)
                if m:
                    stmt = m.group("s").strip()
                    return {"last_statement": stmt or None, "last_message": msg}
                return {"last_statement": None, "last_message": msg}

        return {"last_statement": None, "last_message": None}

    def _parse_feed() -> dict[str, Any] | None:
        """Extract feed-mode status from common REST payload variants.

        Returns:
            Feed-mode dict when present, otherwise None.
        """

        def _to_int(v: Any) -> int | None:
            if isinstance(v, int):
                return v
            if isinstance(v, float) and v.is_integer():
                return int(v)
            if isinstance(v, str):
                t = v.strip()
                if t.isdigit():
                    return int(t)
            return None

        feed_any: Any = _find_field(status_obj, "feed")
        if feed_any is None:
            feed_any = _find_field(status_obj, "feeds")

        if isinstance(feed_any, (int, float, str)):
            feed_id = _to_int(feed_any)
            if feed_id is None:
                return None
            return {"name": feed_id, "active": bool(feed_id), "active_raw": None}

        if isinstance(feed_any, dict):
            feed = cast(dict[str, Any], feed_any)
            feed_id = _to_int(feed.get("name") or feed.get("id") or feed.get("sel"))

            active_raw: Any = feed.get("active")
            active: bool | None = None
            if isinstance(active_raw, bool):
                active = active_raw
            else:
                active_int = _to_int(active_raw)
                if active_int is not None:
                    active = active_int == 1

            if active is None and feed_id is not None:
                active = feed_id in (1, 2, 3, 4)

            return {"name": feed_id, "active": active, "active_raw": active_raw}

        if isinstance(feed_any, list):
            active_id: int | None = None
            active_raw: Any = None
            for item_any in cast(list[Any], feed_any):
                if not isinstance(item_any, dict):
                    continue
                item = cast(dict[str, Any], item_any)
                item_id = _to_int(item.get("name") or item.get("id"))
                item_active_raw: Any = item.get("active") or item.get("running")
                item_active: bool | None = None
                if isinstance(item_active_raw, bool):
                    item_active = item_active_raw
                else:
                    item_active_int = _to_int(item_active_raw)
                    if item_active_int is not None:
                        item_active = item_active_int == 1

                if item_active:
                    active_id = item_id
                    active_raw = item_active_raw
                    break

            return {
                "name": active_id or 0,
                "active": bool(active_id),
                "active_raw": active_raw,
            }

        return None

    return {
        "meta": meta,
        "network": network,
        "probes": probes,
        "outlets": outlets,
        "feed": _parse_feed(),
        "alerts": _parse_last_alert_statement(),
        "trident": _parse_trident_from_modules(),
        "raw": status_obj,
    }


def parse_status_cgi_json(status_obj: dict[str, Any]) -> dict[str, Any]:
    """Parse `/cgi-bin/status.json` into a normalized dict.

    Args:
        status_obj: Parsed JSON dict from `/cgi-bin/status.json`.

    Returns:
        Normalized dict containing at least: meta, probes, outlets, raw.
    """
    istat_any: Any = status_obj.get("istat")
    istat: dict[str, Any] = {}
    if isinstance(istat_any, dict):
        istat = cast(dict[str, Any], istat_any)

    def _find_serial() -> str | None:
        for candidate in (
            istat.get("serial"),
            istat.get("serialNo"),
            istat.get("serialNO"),
            istat.get("serial_number"),
            status_obj.get("serial"),
            status_obj.get("serialNo"),
        ):
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
            if isinstance(candidate, int):
                return str(candidate)

        system_any: Any = status_obj.get("system")
        if isinstance(system_any, dict):
            system = cast(dict[str, Any], system_any)
            candidate = system.get("serial")
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
            if isinstance(candidate, int):
                return str(candidate)

        return None

    meta: dict[str, Any] = {
        "software": None,
        "hardware": (str(istat.get("hardware") or "").strip() or None),
        "hostname": (str(istat.get("hostname") or "").strip() or None),
        "serial": _find_serial(),
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

            module_abaddr: int | None = None
            module_abaddr_any: Any = (
                item.get("module_abaddr") or item.get("abaddr") or item.get("abAddr")
            )
            if isinstance(module_abaddr_any, int):
                module_abaddr = module_abaddr_any

            if module_abaddr is None:
                module_abaddr = module_abaddr_from_input_did(did)

            module_hwtype: str | None = None
            module_hwtype_any: Any = (
                item.get("module_hwtype") or item.get("hwtype") or item.get("hwType")
            )
            if isinstance(module_hwtype_any, str) and module_hwtype_any.strip():
                module_hwtype = module_hwtype_any.strip().upper()

            value: Any = item.get("value")
            probes[did] = {
                "name": (str(item.get("name") or did)).strip(),
                "type": (str(item.get("type") or "")).strip() or None,
                "value_raw": value,
                "value": value,
                "module_abaddr": module_abaddr,
                "module_hwtype": module_hwtype,
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

            module_abaddr: int | None = None
            module_abaddr_any: Any = (
                item.get("module_abaddr") or item.get("abaddr") or item.get("abAddr")
            )
            if isinstance(module_abaddr_any, int):
                module_abaddr = module_abaddr_any
            if module_abaddr is None:
                module_abaddr = module_abaddr_from_input_did(did)

            module_hwtype: str | None = None
            module_hwtype_any: Any = (
                item.get("module_hwtype") or item.get("hwtype") or item.get("hwType")
            )
            if isinstance(module_hwtype_any, str) and module_hwtype_any.strip():
                module_hwtype = module_hwtype_any.strip().upper()

            outlets.append(
                {
                    "name": (str(item.get("name") or did)).strip(),
                    "output_id": str(item.get("ID") or "").strip() or None,
                    "state": (state or "").strip() or None,
                    "device_id": did,
                    "type": (output_type or "").strip() or None,
                    "gid": (gid or "").strip() or None,
                    "status": status_any if isinstance(status_any, list) else None,
                    "module_abaddr": module_abaddr,
                    "module_hwtype": module_hwtype,
                }
            )

    def _parse_feed() -> dict[str, Any] | None:
        def _to_int(v: Any) -> int | None:
            if isinstance(v, int):
                return v
            if isinstance(v, float) and v.is_integer():
                return int(v)
            if isinstance(v, str):
                t = v.strip()
                if t.isdigit():
                    return int(t)
            return None

        feed_any: Any = istat.get("feed")
        if feed_any is None:
            feed_any = status_obj.get("feed")

        if isinstance(feed_any, (int, float, str)):
            feed_id = _to_int(feed_any)
            if feed_id is None:
                return None
            return {"name": feed_id, "active": bool(feed_id), "active_raw": None}

        if isinstance(feed_any, dict):
            feed = cast(dict[str, Any], feed_any)
            feed_id = _to_int(feed.get("name") or feed.get("id") or feed.get("sel"))

            active_raw: Any = feed.get("active")
            active: bool | None = None
            if isinstance(active_raw, bool):
                active = active_raw
            else:
                active_int = _to_int(active_raw)
                if active_int is not None:
                    active = active_int == 1

            if active is None and feed_id is not None:
                active = feed_id in (1, 2, 3, 4)

            return {"name": feed_id, "active": active, "active_raw": active_raw}

        return None

    return {
        "meta": meta,
        "probes": probes,
        "outlets": outlets,
        "feed": _parse_feed(),
        "alerts": {"last_statement": None, "last_message": None},
        "trident": {"status": None, "is_testing": None},
        "raw": status_obj,
    }

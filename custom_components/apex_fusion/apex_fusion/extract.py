"""Schema-tolerant extraction helpers for coordinator payloads.

The Apex controller may nest status data under common container keys. This
module provides conservative accessors that avoid guessing.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, cast

# -----------------------------------------------------------------------------
# Raw Containers
# -----------------------------------------------------------------------------


RAW_CONTAINER_KEYS: tuple[str, ...] = ("data", "status", "istat", "systat", "result")


def find_in_raw_containers(raw: Mapping[str, Any], key: str) -> Any | None:
    """Find a key in a raw payload, supporting common nested containers.

    Args:
        raw: Raw status mapping.
        key: Key to look up.

    Returns:
        The value if found at the top level or inside a known container.
    """

    direct = raw.get(key)
    if direct is not None:
        return direct

    for container_key in RAW_CONTAINER_KEYS:
        container_any: Any = raw.get(container_key)
        if isinstance(container_any, Mapping) and key in container_any:
            return cast(Mapping[str, Any], container_any).get(key)

    return None


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    """Coerce a list of items to a list of dicts.

    Args:
        value: Value to coerce.

    Returns:
        List containing only the dict items from the input list.
    """

    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for item_any in cast(list[Any], value):
        if isinstance(item_any, dict):
            out.append(cast(dict[str, Any], item_any))
    return out


def raw_modules_from_data(data: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Extract module dicts from coordinator data.

    Args:
        data: Coordinator data.

    Returns:
        A list of module dicts.
    """

    raw_any: Any = (data or {}).get("raw")
    if not isinstance(raw_any, Mapping):
        return []

    modules_any: Any = find_in_raw_containers(
        cast(Mapping[str, Any], raw_any), "modules"
    )
    return _list_of_dicts(modules_any)


def raw_modules_from_raw(raw: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Extract modules from an already-unwrapped raw dict.

    Args:
        raw: Raw payload mapping.

    Returns:
        A list of module dicts.
    """

    return _list_of_dicts(find_in_raw_containers(raw or {}, "modules"))


def raw_nstat_from_data(data: Mapping[str, Any] | None) -> dict[str, Any]:
    """Extract the nstat dict from coordinator data.

    Args:
        data: Coordinator data.

    Returns:
        Normalized nstat mapping.
    """

    raw_any: Any = (data or {}).get("raw")
    if not isinstance(raw_any, Mapping):
        return {}

    nstat_any: Any = find_in_raw_containers(cast(Mapping[str, Any], raw_any), "nstat")
    return cast(dict[str, Any], nstat_any) if isinstance(nstat_any, dict) else {}


def mconf_modules_from_data(data: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Extract module candidates from controller config (mconf).

    Args:
        data: Coordinator data.

    Returns:
        List of module mappings.
    """

    config_any: Any = (data or {}).get("config")
    if not isinstance(config_any, Mapping):
        return []

    mconf_any: Any = cast(Mapping[str, Any], config_any).get("mconf")
    return _list_of_dicts(mconf_any)


def iter_present_module_items(modules: Iterable[Any]) -> Iterable[dict[str, Any]]:
    """Yield dict modules that are marked present.

    Args:
        modules: Iterable of module-like values.

    Yields:
        Module dicts with `present` not explicitly set to False.
    """

    for module_any in modules:
        if not isinstance(module_any, Mapping):
            continue
        module = cast(dict[str, Any], module_any)
        present_any: Any = module.get("present")
        present = bool(present_any) if isinstance(present_any, bool) else True
        if present:
            yield module

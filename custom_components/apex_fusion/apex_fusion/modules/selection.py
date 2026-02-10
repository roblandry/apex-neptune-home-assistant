"""Apex Fusion module selection helpers.

This module provides conservative helpers for identifying Aquabus modules from
coordinator payloads.
"""

from __future__ import annotations

from typing import Any, Mapping, cast

from ..extract import mconf_modules_from_data, raw_modules_from_data


def hwtype_from_module(module: Mapping[str, Any]) -> str | None:
    """Extract a normalized hwtype token from a module mapping."""

    hwtype_any: Any = module.get("hwtype") or module.get("hwType") or module.get("type")
    if isinstance(hwtype_any, (str, int, float)):
        t = str(hwtype_any).strip().upper()
        return t or None
    return None


def best_module_candidates_by_abaddr(
    data: Mapping[str, Any] | None,
    *,
    include_trident: bool = True,
) -> dict[int, dict[str, Any]]:
    """Return best-effort module candidates keyed by Aquabus address."""

    candidates_by_abaddr: dict[int, dict[str, Any]] = {}

    def _add_candidate(m: dict[str, Any]) -> None:
        abaddr_any: Any = m.get("abaddr")
        if not isinstance(abaddr_any, int):
            return

        present_any: Any = m.get("present")
        present = bool(present_any) if isinstance(present_any, bool) else True
        if not present:
            return

        current = candidates_by_abaddr.get(abaddr_any)
        if current is None:
            candidates_by_abaddr[abaddr_any] = m
            return

        cur_hw = hwtype_from_module(current)
        new_hw = hwtype_from_module(m)

        if cur_hw is None and new_hw is not None:
            candidates_by_abaddr[abaddr_any] = m

    for module in raw_modules_from_data(data):
        _add_candidate(module)
    for module in mconf_modules_from_data(data):
        _add_candidate(module)

    if include_trident:
        trident_any: Any = (data or {}).get("trident")
        if isinstance(trident_any, dict):
            trident = cast(dict[str, Any], trident_any)
            if trident.get("present") and isinstance(trident.get("abaddr"), int):
                _add_candidate(
                    {
                        "abaddr": trident.get("abaddr"),
                        "hwtype": trident.get("hwtype") or "TRI",
                        "present": True,
                        "name": "Trident",
                    }
                )

    return candidates_by_abaddr

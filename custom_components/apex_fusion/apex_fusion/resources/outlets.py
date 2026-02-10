"""Outlet resource.

This module intentionally avoids Home Assistant imports.
"""

from __future__ import annotations

from typing import Any, cast

from .base import ResourceSpec


def extract_outlets(status: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the normalized outlets list."""
    outlets_any: Any = (status or {}).get("outlets")
    if not isinstance(outlets_any, list):
        return []

    out: list[dict[str, Any]] = []
    for item_any in cast(list[Any], outlets_any):
        if isinstance(item_any, dict):
            out.append(cast(dict[str, Any], item_any))
    return out


SPEC = ResourceSpec(name="outlets", extract=extract_outlets)

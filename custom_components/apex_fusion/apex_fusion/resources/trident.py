"""Trident resource.

This module intentionally avoids Home Assistant imports.
"""

from __future__ import annotations

from typing import Any, cast

from .base import ResourceSpec


def extract_trident(status: dict[str, Any]) -> dict[str, Any]:
    """Return the normalized trident mapping."""
    trident_any: Any = (status or {}).get("trident")
    return cast(dict[str, Any], trident_any) if isinstance(trident_any, dict) else {}


SPEC = ResourceSpec(name="trident", extract=extract_trident)

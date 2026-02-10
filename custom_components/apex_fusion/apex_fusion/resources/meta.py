"""Meta resource.

This module intentionally avoids Home Assistant imports.
"""

from __future__ import annotations

from typing import Any, cast

from .base import ResourceSpec


def extract_meta(status: dict[str, Any]) -> dict[str, Any]:
    """Return the controller meta mapping."""
    meta_any: Any = (status or {}).get("meta")
    return cast(dict[str, Any], meta_any) if isinstance(meta_any, dict) else {}


SPEC = ResourceSpec(name="meta", extract=extract_meta)

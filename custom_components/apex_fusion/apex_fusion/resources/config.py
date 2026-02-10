"""Config resource.

The client may populate `config` from REST (`/rest/config`) either inline or via
its cache.

This module intentionally avoids Home Assistant imports.
"""

from __future__ import annotations

from typing import Any, cast

from .base import ResourceSpec


def extract_config(status: dict[str, Any]) -> dict[str, Any]:
    """Return the normalized config mapping."""
    config_any: Any = (status or {}).get("config")
    return cast(dict[str, Any], config_any) if isinstance(config_any, dict) else {}


SPEC = ResourceSpec(name="config", extract=extract_config)

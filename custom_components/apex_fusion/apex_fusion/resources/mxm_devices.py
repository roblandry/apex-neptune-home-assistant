"""MXM devices resource.

This module intentionally avoids Home Assistant imports.
"""

from __future__ import annotations

from typing import Any, cast

from .base import ResourceSpec


def extract_mxm_devices(status: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Return MXM attached-device metadata when available."""
    any_devices: Any = (status or {}).get("mxm_devices")
    if not isinstance(any_devices, dict):
        return {}

    out: dict[str, dict[str, str]] = {}
    for name, meta_any in cast(dict[str, Any], any_devices).items():
        if not name:
            continue
        if isinstance(meta_any, dict):
            meta = cast(dict[str, Any], meta_any)
            out[name] = {
                "rev": str(meta.get("rev") or ""),
                "serial": str(meta.get("serial") or ""),
                "status": str(meta.get("status") or ""),
            }
    return out


SPEC = ResourceSpec(name="mxm_devices", extract=extract_mxm_devices)

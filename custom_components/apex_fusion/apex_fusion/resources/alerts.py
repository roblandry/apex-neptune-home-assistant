"""Alerts resource.

This module intentionally avoids Home Assistant imports.
"""

from __future__ import annotations

from typing import Any, cast

from .base import ResourceSpec


def extract_alerts(status: dict[str, Any]) -> dict[str, Any]:
    """Return the normalized alerts mapping."""
    alerts_any: Any = (status or {}).get("alerts")
    return cast(dict[str, Any], alerts_any) if isinstance(alerts_any, dict) else {}


SPEC = ResourceSpec(name="alerts", extract=extract_alerts)

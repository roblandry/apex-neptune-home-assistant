"""Network resource.

This module intentionally avoids Home Assistant imports.
"""

from __future__ import annotations

from typing import Any, cast

from .base import ResourceSpec


def extract_network(status: dict[str, Any]) -> dict[str, Any]:
    """Return the controller network mapping."""
    network_any: Any = (status or {}).get("network")
    return cast(dict[str, Any], network_any) if isinstance(network_any, dict) else {}


SPEC = ResourceSpec(name="network", extract=extract_network)

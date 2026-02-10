"""Probe resource.

This module intentionally avoids Home Assistant imports.
"""

from __future__ import annotations

from typing import Any, cast

from .base import ResourceSpec


def extract_probes(status: dict[str, Any]) -> dict[str, Any]:
    """Return the normalized probes mapping."""
    probes_any: Any = (status or {}).get("probes")
    return cast(dict[str, Any], probes_any) if isinstance(probes_any, dict) else {}


SPEC = ResourceSpec(name="probes", extract=extract_probes)

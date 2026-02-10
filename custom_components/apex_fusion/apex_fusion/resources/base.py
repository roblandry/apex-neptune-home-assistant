"""Resource (module) interface for the internal API.

A "resource" is a named view onto the normalized status payload. Resources are
intended for standalone usage where callers want a single JSON subtree (for
example, probes/outlets/trident) without Home Assistant concerns.

This module intentionally avoids Home Assistant imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

Extractor = Callable[[dict[str, Any]], Any]


@dataclass(frozen=True)
class ResourceSpec:
    """Spec for a resource extractable from the normalized status payload."""

    name: str
    extract: Extractor

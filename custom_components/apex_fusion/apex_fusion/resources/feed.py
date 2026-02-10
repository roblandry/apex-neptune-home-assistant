"""Feed resource.

This module intentionally avoids Home Assistant imports.
"""

from __future__ import annotations

from typing import Any, cast

from .base import ResourceSpec


def extract_feed(status: dict[str, Any]) -> dict[str, Any] | None:
    """Return the normalized feed mapping (or None)."""
    feed_any: Any = (status or {}).get("feed")
    if feed_any is None:
        return None
    return cast(dict[str, Any], feed_any) if isinstance(feed_any, dict) else None


SPEC = ResourceSpec(name="feed", extract=extract_feed)

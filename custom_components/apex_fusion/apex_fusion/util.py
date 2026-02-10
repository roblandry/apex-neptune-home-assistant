"""Small utility helpers used across the integration.

This module intentionally avoids Home Assistant imports so it can be reused by
the internal API package.
"""

from __future__ import annotations

import re
from typing import Any

# -----------------------------------------------------------------------------
# Conversions
# -----------------------------------------------------------------------------


def to_int(value: Any) -> int | None:
    """Best-effort conversion to int.

    Args:
        value: Value to convert.

    Returns:
        An int when the input is a real int, an integer-valued float, or a
        digit-only string; otherwise `None`.
    """
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        t = value.strip()
        if t.isdigit():
            return int(t)
    return None


def slugify_label(value: str) -> str:
    """Convert a label to a stable slug.

    The internal API package uses this helper instead of Home Assistant's
    `homeassistant.util.slugify` to keep the package free of HA dependencies.

    Args:
        value: Label to slugify.

    Returns:
        A lowercase string containing only ASCII letters, digits, and
        underscores.
    """
    text = (value or "").strip().lower()
    if not text:
        return ""
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text

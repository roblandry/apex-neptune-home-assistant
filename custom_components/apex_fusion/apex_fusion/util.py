"""Small utility helpers used across the integration."""

from __future__ import annotations

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

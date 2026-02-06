"""Network helpers for Apex Fusion coordinator data.

These helpers return small extractor callables used by entity platforms.
"""

from __future__ import annotations

from typing import Any, Callable, cast

# -----------------------------------------------------------------------------
# Extractors
# -----------------------------------------------------------------------------


def network_field(field: str) -> Callable[[dict[str, Any]], Any]:
    """Build a value extractor for the coordinator's `network` section.

    Args:
        field: Key within the `network` dict.

    Returns:
        Callable that accepts the coordinator `data` dict and returns
        `data["network"][field]` when present.
    """

    def _get(data: dict[str, Any]) -> Any:
        network_any = data.get("network")
        if isinstance(network_any, dict):
            network = cast(dict[str, Any], network_any)
            return network.get(field)
        return None

    return _get


def network_bool(field: str) -> Callable[[dict[str, Any]], bool | None]:
    """Build a bool-ish extractor for a `network` field.

    Args:
        field: Key within the `network` dict.

    Returns:
        Callable that returns `bool | None`:
        - `True/False` when the value is bool (or int coercible)
        - `None` when missing or not coercible.
    """

    def _get(data: dict[str, Any]) -> bool | None:
        network_any: Any = data.get("network")
        if not isinstance(network_any, dict):
            return None
        network = cast(dict[str, Any], network_any)
        value: Any = network.get(field)
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return bool(value)
        return None

    return _get

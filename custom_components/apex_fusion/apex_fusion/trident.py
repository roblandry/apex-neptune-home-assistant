"""Trident-specific helpers.

These helpers operate on the coordinator's `data["trident"]` section.
"""

from typing import Any, Callable, cast

# -----------------------------------------------------------------------------
# Status / booleans
# -----------------------------------------------------------------------------


def trident_is_testing(data: dict[str, Any]) -> bool | None:
    """Return whether the Trident is currently testing.

    Args:
        data: Coordinator data dict.

    Returns:
        `True/False` when present, otherwise `None`.
    """
    trident_any: Any = data.get("trident")
    if not isinstance(trident_any, dict):
        return None
    trident = cast(dict[str, Any], trident_any)
    value: Any = trident.get("is_testing")
    if isinstance(value, bool):
        return value
    return None


def trident_waste_full(data: dict[str, Any]) -> bool | None:
    """Return whether the Trident waste container is full.

    Args:
        data: Coordinator data dict.

    Returns:
        `True/False` when present, otherwise `None`.
    """
    trident_any: Any = data.get("trident")
    if not isinstance(trident_any, dict):
        return None
    trident = cast(dict[str, Any], trident_any)
    value: Any = trident.get("waste_full")
    if isinstance(value, bool):
        return value
    return None


def trident_reagent_empty(field: str) -> Callable[[dict[str, Any]], bool | None]:
    """Build an extractor for a reagent-empty flag.

    Args:
        field: Key within the `trident` section (e.g. `reagent_a_empty`).

    Returns:
        Callable that returns `bool | None`.
    """

    def _get(data: dict[str, Any]) -> bool | None:
        trident_any: Any = data.get("trident")
        if not isinstance(trident_any, dict):
            return None
        trident = cast(dict[str, Any], trident_any)
        value: Any = trident.get(field)
        if isinstance(value, bool):
            return value
        return None

    return _get


def trident_level_ml(index: int) -> Callable[[dict[str, Any]], Any]:
    """Build an extractor for a Trident container level by index.

    Args:
        index: Index into the `levels_ml` list.

    Returns:
        Callable that accepts coordinator `data` and returns the indexed level
        value when present.
    """

    def _get(data: dict[str, Any]) -> Any:
        trident_any: Any = data.get("trident")
        if not isinstance(trident_any, dict):
            return None
        trident = cast(dict[str, Any], trident_any)
        levels_any: Any = trident.get("levels_ml")
        if not isinstance(levels_any, list):
            return None
        levels = cast(list[Any], levels_any)
        if index < 0 or index >= len(levels):
            return None
        return levels[index]

    return _get

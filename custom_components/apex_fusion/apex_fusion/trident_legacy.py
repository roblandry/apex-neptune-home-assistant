"""Trident-specific helpers.

These helpers operate on the normalized `data["trident"]` section.
"""

from __future__ import annotations

from typing import Any, Callable, cast

TRIDENT_WASTE_FULL_MARGIN_ML = 20.0
TRIDENT_REAGENT_EMPTY_THRESHOLD_ML = 20.0


def finalize_trident(data: dict[str, Any]) -> None:
    """Compute derived Trident fields from raw status + config.

    Args:
        data: Normalized data dict.

    Returns:
        None.
    """
    trident_any: Any = data.get("trident")
    if not isinstance(trident_any, dict):
        return
    trident = cast(dict[str, Any], trident_any)

    levels_any: Any = trident.get("levels_ml")
    waste_used_ml: float | None = None
    reagent_a_ml: float | None = None
    reagent_b_ml: float | None = None
    reagent_c_ml: float | None = None
    if isinstance(levels_any, list) and levels_any:
        levels = cast(list[Any], levels_any)
        first = levels[0]
        if isinstance(first, (int, float)) and not isinstance(first, bool):
            waste_used_ml = float(first)

        idx_a: int | None = None
        idx_b: int | None = None
        idx_c: int | None = None
        if len(levels) >= 5:
            idx_c, idx_b, idx_a = 2, 3, 4
        elif len(levels) == 4:
            idx_c, idx_b, idx_a = 1, 2, 3

        def _read_ml(idx: int | None) -> float | None:
            if idx is None:
                return None
            v = levels[idx]
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return float(v)
            return None

        reagent_a_ml = _read_ml(idx_a)
        reagent_b_ml = _read_ml(idx_b)
        reagent_c_ml = _read_ml(idx_c)

    trident["waste_used_ml"] = waste_used_ml

    trident["reagent_a_remaining_ml"] = reagent_a_ml
    trident["reagent_b_remaining_ml"] = reagent_b_ml
    trident["reagent_c_remaining_ml"] = reagent_c_ml

    trident["reagent_a_empty"] = (
        (reagent_a_ml <= TRIDENT_REAGENT_EMPTY_THRESHOLD_ML)
        if reagent_a_ml is not None
        else None
    )
    trident["reagent_b_empty"] = (
        (reagent_b_ml <= TRIDENT_REAGENT_EMPTY_THRESHOLD_ML)
        if reagent_b_ml is not None
        else None
    )
    trident["reagent_c_empty"] = (
        (reagent_c_ml <= TRIDENT_REAGENT_EMPTY_THRESHOLD_ML)
        if reagent_c_ml is not None
        else None
    )

    waste_size_any: Any = trident.get("waste_size_ml")
    waste_size_ml: float | None = None
    if isinstance(waste_size_any, (int, float)) and not isinstance(
        waste_size_any, bool
    ):
        if float(waste_size_any) > 0:
            waste_size_ml = float(waste_size_any)
    trident["waste_size_ml"] = waste_size_ml

    if waste_used_ml is None or waste_size_ml is None:
        trident["waste_percent"] = None
        trident["waste_full"] = None
        trident["waste_remaining_ml"] = None
        return

    remaining = max(0.0, waste_size_ml - waste_used_ml)
    percent = (waste_used_ml / waste_size_ml) * 100.0
    trident["waste_percent"] = percent
    trident["waste_remaining_ml"] = remaining
    trident["waste_full"] = remaining <= TRIDENT_WASTE_FULL_MARGIN_ML


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

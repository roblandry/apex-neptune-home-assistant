"""Generic coordinator-data field extractors.

These helpers keep entity platforms thin by encapsulating safe dict access.
"""

from __future__ import annotations

from typing import Any, Callable, cast

# -----------------------------------------------------------------------------
# Extractors
# -----------------------------------------------------------------------------


def section_field(section: str, field: str) -> Callable[[dict[str, Any]], Any]:
    """Build an extractor for a nested section field.

    Args:
        section: Top-level key in coordinator data.
        field: Key within the nested dict at `data[section]`.

    Returns:
        Callable that accepts coordinator `data` and returns the nested value
        when present.
    """

    def _get(data: dict[str, Any]) -> Any:
        section_any = data.get(section)
        if isinstance(section_any, dict):
            section_dict = cast(dict[str, Any], section_any)
            return section_dict.get(field)
        return None

    return _get

"""Aquabus hardware module helpers.

This package groups module-specific logic in a standard, discoverable place.

Today it contains:
  - conservative module candidate selection (`selection.py`)
  - Trident helpers (`trident.py`)
"""

from __future__ import annotations

from .selection import best_module_candidates_by_abaddr, hwtype_from_module

__all__ = [
    "best_module_candidates_by_abaddr",
    "hwtype_from_module",
]

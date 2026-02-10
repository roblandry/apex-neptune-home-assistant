"""Tests for internal module selection helpers."""

from __future__ import annotations

from custom_components.apex_fusion.apex_fusion.modules import (
    best_module_candidates_by_abaddr,
)


def test_best_module_candidates_by_abaddr_skips_invalid_abaddr_types() -> None:
    candidates = best_module_candidates_by_abaddr(
        {"raw": {"modules": [{"abaddr": "1", "present": True, "hwtype": "FMM"}]}},
        include_trident=False,
    )
    assert candidates == {}


def test_best_module_candidates_by_abaddr_skips_not_present_modules() -> None:
    candidates = best_module_candidates_by_abaddr(
        {"raw": {"modules": [{"abaddr": 1, "present": False, "hwtype": "FMM"}]}},
        include_trident=False,
    )
    assert candidates == {}

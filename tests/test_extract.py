"""Tests for schema-tolerant extraction helpers."""

from __future__ import annotations

from custom_components.apex_fusion.apex_fusion.extract import (
    iter_present_module_items,
    raw_modules_from_raw,
)


def test_raw_modules_from_raw_extracts_modules_list() -> None:
    raw = {
        "modules": [
            {"abaddr": 1},
            "nope",
            {"hwtype": "FMM"},
        ]
    }

    assert raw_modules_from_raw(raw) == [{"abaddr": 1}, {"hwtype": "FMM"}]


def test_iter_present_module_items_filters_not_present_and_non_mappings() -> None:
    modules = [
        {"abaddr": 1, "present": True},
        {"abaddr": 2, "present": False},
        {"abaddr": 3, "present": "unknown"},
        "nope",
    ]

    items = list(iter_present_module_items(modules))
    assert items == [
        {"abaddr": 1, "present": True},
        {"abaddr": 3, "present": "unknown"},
    ]

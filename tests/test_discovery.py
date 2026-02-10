"""Tests for discovery helpers in the internal apex_fusion package."""

from __future__ import annotations

from custom_components.apex_fusion.apex_fusion.discovery import ApexDiscovery


def test_new_probe_refs_returns_empty_when_probes_container_invalid() -> None:
    refs, seen = ApexDiscovery.new_probe_refs(
        {"probes": []},
        already_added_keys=set(),
    )
    assert refs == []
    assert seen == set()


def test_new_outlet_intensity_refs_returns_empty_when_outlets_container_invalid() -> (
    None
):
    refs, seen = ApexDiscovery.new_outlet_intensity_refs(
        {"outlets": {}},
        already_added_dids=set(),
    )
    assert refs == []
    assert seen == set()


def test_new_outlet_select_refs_returns_empty_when_outlets_container_invalid() -> None:
    refs, seen = ApexDiscovery.new_outlet_select_refs(
        {"outlets": "nope"},
        already_added_dids=set(),
    )
    assert refs == []
    assert seen == set()

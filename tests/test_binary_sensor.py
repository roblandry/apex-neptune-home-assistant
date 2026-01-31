"""Tests for Apex Fusion binary sensor platform."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, cast

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.apex_fusion.const import CONF_HOST, DOMAIN


@dataclass
class _CoordinatorStub:
    data: dict[str, Any]
    last_update_success: bool = True
    device_identifier: str = "TEST"

    def async_add_listener(
        self, update_callback: Callable[[], None]
    ) -> Callable[[], None]:
        # Immediately callable unsub.
        def _unsub() -> None:
            return None

        return _unsub


async def test_binary_sensor_setup_and_updates(hass, enable_custom_integrations):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: "1.2.3.4"},
        unique_id="1.2.3.4",
        title="Apex (1.2.3.4)",
    )
    entry.add_to_hass(hass)

    coordinator = _CoordinatorStub(
        data={
            "meta": {"serial": "ABC"},
            "network": {"dhcp": True, "wifi_enable": 1},
        },
        last_update_success=True,
        device_identifier="ABC",
    )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    added: list[Any] = []

    def _add_entities(new_entities, update_before_add: bool = False):
        added.extend(list(new_entities))

    from custom_components.apex_fusion import binary_sensor

    await binary_sensor.async_setup_entry(hass, cast(Any, entry), _add_entities)

    assert len(added) == 2

    for ent in added:
        # Avoid requiring full entity platform state machine.
        ent.async_write_ha_state = lambda *args, **kwargs: None
        await ent.async_added_to_hass()

    # Drive coordinator update branches: bool, int->bool, and unsupported -> None.
    coordinator.last_update_success = False
    coordinator.data["network"]["dhcp"] = False
    coordinator.data["network"]["wifi_enable"] = "yes"  # unsupported

    for ent in added:
        ent._handle_coordinator_update()

    # Cover branch where network section is not a dict.
    coordinator.data["network"] = "nope"
    for ent in added:
        ent._handle_coordinator_update()

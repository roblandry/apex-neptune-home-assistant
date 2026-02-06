"""Buttons for Apex Fusion (Local).

This platform exposes controller/module refresh and Trident consumables controls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, cast

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import slugify

from .const import CONF_HOST, CONF_PASSWORD, DOMAIN
from .coordinator import (
    ApexNeptuneDataUpdateCoordinator,
    build_aquabus_child_device_info_from_data,
    build_device_info,
    build_trident_device_info,
    clean_hostname_display,
)


def _raw_modules_from_data(data: dict[str, Any]) -> list[dict[str, Any]]:
    raw_any: Any = (data or {}).get("raw")
    if not isinstance(raw_any, dict):
        return []

    raw = cast(dict[str, Any], raw_any)

    def _find_container(root: dict[str, Any], key: str) -> Any:
        direct = root.get(key)
        if direct is not None:
            return direct
        for container_key in ("data", "status", "istat", "systat", "result"):
            container_any: Any = root.get(container_key)
            if isinstance(container_any, dict) and key in container_any:
                container = cast(dict[str, Any], container_any)
                return container.get(key)
        return None

    modules_any: Any = _find_container(raw, "modules")
    if not isinstance(modules_any, list):
        return []

    out: list[dict[str, Any]] = []
    for item_any in cast(list[Any], modules_any):
        if isinstance(item_any, dict):
            out.append(cast(dict[str, Any], item_any))
    return out


def _mconf_modules_from_data(data: dict[str, Any]) -> list[dict[str, Any]]:
    config_any: Any = (data or {}).get("config")
    if not isinstance(config_any, dict):
        return []

    mconf_any: Any = cast(dict[str, Any], config_any).get("mconf")
    if not isinstance(mconf_any, list):
        return []

    out: list[dict[str, Any]] = []
    for item_any in cast(list[Any], mconf_any):
        if isinstance(item_any, dict):
            out.append(cast(dict[str, Any], item_any))
    return out


@dataclass(frozen=True)
class _TridentButtonRef:
    key: str
    name: str
    icon: str
    press_fn: Callable[[ApexNeptuneDataUpdateCoordinator], Any]


@dataclass(frozen=True)
class _ControllerButtonRef:
    key: str
    name: str
    icon: str
    press_fn: Callable[[ApexNeptuneDataUpdateCoordinator], Any]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up controller/module buttons."""
    coordinator: ApexNeptuneDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Hide controls when password is not configured.
    if not str(entry.data.get(CONF_PASSWORD, "") or ""):
        return

    # Manual refresh for cached config (/rest/config). This helps when config
    # polling is slower than status polling.
    async_add_entities(
        [
            ApexControllerButton(
                coordinator,
                entry,
                ref=_ControllerButtonRef(
                    key="refresh_config_now",
                    name="Refresh Config Now",
                    icon="mdi:refresh",
                    press_fn=lambda c: c.async_refresh_config_now(),
                ),
            )
        ]
    )

    added_module_refresh: set[int] = set()

    def _add_module_refresh_buttons() -> None:
        data = coordinator.data or {}
        meta_any: Any = data.get("meta", {})
        meta = cast(dict[str, Any], meta_any) if isinstance(meta_any, dict) else {}

        new: list[ButtonEntity] = []

        # Build best-effort module candidates per abaddr.
        # Preference order: explicit hwtype > implicit/no hwtype.
        candidates_by_abaddr: dict[int, dict[str, Any]] = {}

        def _hwtype_from_module(m: dict[str, Any]) -> str | None:
            hwtype_any: Any = m.get("hwtype") or m.get("hwType") or m.get("type")
            if isinstance(hwtype_any, (str, int, float)):
                t = str(hwtype_any).strip().upper()
                return t or None
            return None

        def _add_candidate(m: dict[str, Any]) -> None:
            abaddr_any: Any = m.get("abaddr")
            if not isinstance(abaddr_any, int):
                return

            present_any: Any = m.get("present")
            present = bool(present_any) if isinstance(present_any, bool) else True
            if not present:
                return

            current = candidates_by_abaddr.get(abaddr_any)
            if current is None:
                candidates_by_abaddr[abaddr_any] = m
                return

            cur_hw = _hwtype_from_module(current)
            new_hw = _hwtype_from_module(m)

            # Prefer a candidate with an explicit hwtype.
            if cur_hw is None and new_hw is not None:
                candidates_by_abaddr[abaddr_any] = m

        for module in _raw_modules_from_data(data):
            _add_candidate(module)
        for module in _mconf_modules_from_data(data):
            _add_candidate(module)

        # Ensure Trident gets a module refresh button when present.
        trident_any: Any = (data or {}).get("trident")
        if isinstance(trident_any, dict):
            trident = cast(dict[str, Any], trident_any)
            if trident.get("present") and isinstance(trident.get("abaddr"), int):
                _add_candidate(
                    {
                        "abaddr": trident.get("abaddr"),
                        "hwtype": trident.get("hwtype") or "TRI",
                        "present": True,
                        "name": "Trident",
                    }
                )

        for abaddr, module in candidates_by_abaddr.items():
            abaddr_any: Any = module.get("abaddr")
            if not isinstance(abaddr_any, int):
                continue

            present_any: Any = module.get("present")
            present = bool(present_any) if isinstance(present_any, bool) else True
            if not present:
                continue

            hwtype = _hwtype_from_module(module)

            if abaddr in added_module_refresh:
                continue

            module_name_hint: str | None = None
            name_any: Any = module.get("name")
            if isinstance(name_any, str) and name_any.strip():
                module_name_hint = name_any.strip()

            # Only add when we can resolve module device info without guessing.
            di = build_aquabus_child_device_info_from_data(
                host=str(entry.data.get(CONF_HOST, "")),
                controller_meta=meta,
                controller_device_identifier=coordinator.device_identifier,
                data=data,
                module_abaddr=abaddr_any,
                module_hwtype_hint=hwtype,
                module_name_hint=module_name_hint,
            )
            if not di:
                continue

            hwtype_final = str(di.get("model") or hwtype or "").strip().upper() or None

            # Only mark as added once we successfully create the module-attached button.
            added_module_refresh.add(abaddr)

            new.append(
                ApexModuleRefreshConfigButton(
                    coordinator,
                    entry,
                    module_abaddr=abaddr_any,
                    module_hwtype=hwtype_final,
                )
            )

        if new:
            async_add_entities(new)

    _add_module_refresh_buttons()
    entry.async_on_unload(coordinator.async_add_listener(_add_module_refresh_buttons))

    added = False

    def _add_trident_buttons() -> None:
        nonlocal added
        if added:
            return

        data = coordinator.data or {}
        trident_any: Any = data.get("trident")
        if not isinstance(trident_any, dict):
            return
        trident = cast(dict[str, Any], trident_any)
        if not trident.get("present"):
            return
        if not isinstance(trident.get("abaddr"), int):
            return

        refs: list[_TridentButtonRef] = [
            _TridentButtonRef(
                key="trident_prime_reagent_a",
                name="Prime Reagent A",
                icon="mdi:pump",
                press_fn=lambda c: c.async_trident_prime_channel(channel_index=0),
            ),
            _TridentButtonRef(
                key="trident_prime_reagent_b",
                name="Prime Reagent B",
                icon="mdi:pump",
                press_fn=lambda c: c.async_trident_prime_channel(channel_index=1),
            ),
            _TridentButtonRef(
                key="trident_prime_reagent_c",
                name="Prime Reagent C",
                icon="mdi:pump",
                press_fn=lambda c: c.async_trident_prime_channel(channel_index=2),
            ),
            _TridentButtonRef(
                key="trident_prime_sample",
                name="Prime Sample",
                icon="mdi:pump",
                press_fn=lambda c: c.async_trident_prime_channel(channel_index=3),
            ),
            _TridentButtonRef(
                key="trident_reset_reagent_a",
                name="Reset Reagent A",
                icon="mdi:flask-empty-plus-outline",
                press_fn=lambda c: c.async_trident_reset_reagent(reagent_index=0),
            ),
            _TridentButtonRef(
                key="trident_reset_reagent_b",
                name="Reset Reagent B",
                icon="mdi:flask-empty-plus-outline",
                press_fn=lambda c: c.async_trident_reset_reagent(reagent_index=1),
            ),
            _TridentButtonRef(
                key="trident_reset_reagent_c",
                name="Reset Reagent C",
                icon="mdi:flask-empty-plus-outline",
                press_fn=lambda c: c.async_trident_reset_reagent(reagent_index=2),
            ),
            _TridentButtonRef(
                key="trident_reset_waste",
                name="Reset Waste",
                icon="mdi:cup-outline",
                press_fn=lambda c: c.async_trident_reset_waste(),
            ),
        ]

        async_add_entities([ApexTridentButton(coordinator, entry, ref=r) for r in refs])
        added = True

    _add_trident_buttons()
    remove = coordinator.async_add_listener(_add_trident_buttons)
    entry.async_on_unload(remove)


class ApexTridentButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: ApexNeptuneDataUpdateCoordinator,
        entry: ConfigEntry,
        *,
        ref: _TridentButtonRef,
    ) -> None:
        super().__init__()
        self._coordinator = coordinator
        self._entry = entry
        self._ref = ref
        self._unsub: Callable[[], None] | None = None

        host = str(entry.data.get(CONF_HOST, ""))
        meta_any: Any = (coordinator.data or {}).get("meta", {})
        meta = cast(dict[str, Any], meta_any) if isinstance(meta_any, dict) else {}
        serial = str(meta.get("serial") or host or "apex").replace(":", "_")

        self._attr_unique_id = f"{serial}_{ref.key}".lower()
        self._attr_name = ref.name
        self._attr_icon = ref.icon
        data = coordinator.data or {}
        trident_any: Any = data.get("trident")
        trident_abaddr_any: Any = (
            cast(dict[str, Any], trident_any).get("abaddr")
            if isinstance(trident_any, dict)
            else None
        )
        if isinstance(trident_abaddr_any, int):
            trident_hwtype_any: Any = (
                cast(dict[str, Any], trident_any).get("hwtype")
                if isinstance(trident_any, dict)
                else None
            )
            trident_hwrev_any: Any = (
                cast(dict[str, Any], trident_any).get("hwrev")
                if isinstance(trident_any, dict)
                else None
            )
            trident_swrev_any: Any = (
                cast(dict[str, Any], trident_any).get("swrev")
                if isinstance(trident_any, dict)
                else None
            )
            trident_serial_any: Any = (
                cast(dict[str, Any], trident_any).get("serial")
                if isinstance(trident_any, dict)
                else None
            )
            self._attr_device_info = build_trident_device_info(
                host=host,
                meta=meta,
                controller_device_identifier=coordinator.device_identifier,
                trident_abaddr=trident_abaddr_any,
                trident_hwtype=(
                    str(trident_hwtype_any).strip().upper()
                    if isinstance(trident_hwtype_any, str)
                    and trident_hwtype_any.strip()
                    else None
                ),
                trident_hwrev=(
                    str(trident_hwrev_any).strip() or None
                    if trident_hwrev_any is not None
                    else None
                ),
                trident_swrev=(
                    str(trident_swrev_any).strip() or None
                    if trident_swrev_any is not None
                    else None
                ),
                trident_serial=(
                    str(trident_serial_any).strip() or None
                    if trident_serial_any is not None
                    else None
                ),
            )

            meta_any: Any = (coordinator.data or {}).get("meta")
            meta = cast(dict[str, Any], meta_any) if isinstance(meta_any, dict) else {}
            hostname_disp = clean_hostname_display(str(meta.get("hostname") or ""))
            tank_slug = slugify(
                hostname_disp or str(meta.get("hostname") or "").strip() or "tank"
            )
            suffix = str(ref.key).removeprefix("trident_")
            self._attr_suggested_object_id = (
                f"{tank_slug}_trident_addr{trident_abaddr_any}_{suffix}"
            )
        else:
            self._attr_device_info = build_device_info(
                host=host,
                meta=meta,
                device_identifier=coordinator.device_identifier,
            )

        self._attr_available = bool(
            getattr(self._coordinator, "last_update_success", True)
        )

    async def async_press(self) -> None:
        try:
            await cast(Any, self._ref.press_fn)(self._coordinator)
        except HomeAssistantError:
            raise
        except Exception as err:
            raise HomeAssistantError(f"Error running {self._ref.name}: {err}") from err

    def _handle_coordinator_update(self) -> None:
        self._attr_available = bool(
            getattr(self._coordinator, "last_update_success", True)
        )
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        self._unsub = self._coordinator.async_add_listener(
            self._handle_coordinator_update
        )
        self._handle_coordinator_update()

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None


class ApexControllerButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: ApexNeptuneDataUpdateCoordinator,
        entry: ConfigEntry,
        *,
        ref: _ControllerButtonRef,
    ) -> None:
        super().__init__()
        self._coordinator = coordinator
        self._entry = entry
        self._ref = ref
        self._unsub: Callable[[], None] | None = None

        host = str(entry.data.get(CONF_HOST, ""))
        meta_any: Any = (coordinator.data or {}).get("meta", {})
        meta = cast(dict[str, Any], meta_any) if isinstance(meta_any, dict) else {}
        serial = str(meta.get("serial") or host or "apex").replace(":", "_")

        self._attr_unique_id = f"{serial}_{ref.key}".lower()
        self._attr_name = ref.name
        self._attr_icon = ref.icon
        self._attr_device_info = build_device_info(
            host=host,
            meta=meta,
            device_identifier=coordinator.device_identifier,
        )

        self._attr_available = bool(
            getattr(self._coordinator, "last_update_success", True)
        )

    async def async_press(self) -> None:
        try:
            await cast(Any, self._ref.press_fn)(self._coordinator)
        except HomeAssistantError:
            raise
        except Exception as err:
            raise HomeAssistantError(f"Error running {self._ref.name}: {err}") from err

    def _handle_coordinator_update(self) -> None:
        self._attr_available = bool(
            getattr(self._coordinator, "last_update_success", True)
        )
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        self._unsub = self._coordinator.async_add_listener(
            self._handle_coordinator_update
        )
        self._handle_coordinator_update()

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None


class ApexModuleRefreshConfigButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: ApexNeptuneDataUpdateCoordinator,
        entry: ConfigEntry,
        *,
        module_abaddr: int,
        module_hwtype: str | None,
    ) -> None:
        super().__init__()
        self._coordinator = coordinator
        self._entry = entry
        self._unsub: Callable[[], None] | None = None
        self._module_abaddr = module_abaddr
        self._module_hwtype = (module_hwtype or "").strip().upper() or None

        host = str(entry.data.get(CONF_HOST, ""))
        meta_any: Any = (coordinator.data or {}).get("meta", {})
        meta = cast(dict[str, Any], meta_any) if isinstance(meta_any, dict) else {}
        serial = str(meta.get("serial") or host or "apex").replace(":", "_")

        self._attr_unique_id = f"{serial}_module_{self._module_hwtype or 'module'}_{module_abaddr}_refresh_config".lower()
        self._attr_name = "Refresh Config Now"
        self._attr_icon = "mdi:refresh"

        hostname_disp = clean_hostname_display(str(meta.get("hostname") or ""))
        tank_slug = slugify(
            hostname_disp or str(meta.get("hostname") or "").strip() or "tank"
        )
        self._attr_suggested_object_id = (
            f"{tank_slug}_addr{module_abaddr}_refresh_config"
        )

        module_device_info = build_aquabus_child_device_info_from_data(
            host=host,
            controller_meta=meta,
            controller_device_identifier=coordinator.device_identifier,
            data=coordinator.data or {},
            module_abaddr=module_abaddr,
            module_hwtype_hint=self._module_hwtype,
        )
        self._attr_device_info = module_device_info or build_device_info(
            host=host,
            meta=meta,
            device_identifier=coordinator.device_identifier,
        )

        self._attr_available = bool(
            getattr(self._coordinator, "last_update_success", True)
        )

    async def async_press(self) -> None:
        try:
            await self._coordinator.async_refresh_config_now()
        except HomeAssistantError:
            raise
        except Exception as err:
            raise HomeAssistantError(
                f"Error running Refresh Config Now: {err}"
            ) from err

    def _handle_coordinator_update(self) -> None:
        self._attr_available = bool(
            getattr(self._coordinator, "last_update_success", True)
        )
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        self._unsub = self._coordinator.async_add_listener(
            self._handle_coordinator_update
        )
        self._handle_coordinator_update()

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None

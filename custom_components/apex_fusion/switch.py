"""Switch entities for Apex Fusion (Local).

This is intentionally conservative: we only create switches for outputs that
look like simple on/off outlets (not MXM pumps/lights).

Control is via the local REST API:
- POST /rest/login -> connect.sid
- PUT  /rest/status/outputs/<did>
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, cast

import aiohttp
import async_timeout
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
    DEFAULT_TIMEOUT_SECONDS,
    DOMAIN,
)
from .coordinator import ApexNeptuneDataUpdateCoordinator, build_base_url

_LOGGER = logging.getLogger(DOMAIN)


def _pretty_model(s: str) -> str:
    """Prettify model tokens like 'Nero5' -> 'Nero 5'."""
    t = (s or "").strip()
    if not t:
        return t

    split_at: int | None = None
    for idx, ch in enumerate(t):
        if ch.isdigit():
            split_at = idx
            break

    if split_at is None or split_at == 0:
        return t

    prefix = t[:split_at]
    suffix = t[split_at:]
    if suffix.isdigit() and prefix.isalpha():
        return f"{prefix} {suffix}"
    return t


def _friendly_outlet_name(*, outlet_name: str, outlet_type: str | None) -> str:
    """Return a better entity name for an outlet/output."""
    raw_name = (outlet_name or "").strip()
    raw_type = (outlet_type or "").strip()
    if not raw_name:
        return raw_name

    parts = [p.strip() for p in raw_type.split("|") if p.strip()]
    if len(parts) >= 3 and parts[0].upper().startswith("MXM"):
        vendor = parts[1]
        model = _pretty_model(parts[2])
        pretty_name = raw_name.replace("_", " ").strip()
        label = f"{vendor} {model}".strip()
        if pretty_name and pretty_name.lower() not in label.lower():
            return f"{label} ({pretty_name})"
        return label

    return raw_name.replace("_", " ").strip()


@dataclass(frozen=True)
class _OutletRef:
    """Reference to an Apex output/outlet."""

    did: str
    name: str


def _build_device_info(*, host: str, meta: dict[str, Any]) -> DeviceInfo:
    """Build DeviceInfo for this controller.

    Args:
        host: Controller host/IP.
        meta: Coordinator meta dict.

    Returns:
        DeviceInfo instance.
    """
    serial = str(meta.get("serial") or "").strip() or None
    model = str(meta.get("type") or meta.get("hardware") or "Apex").strip() or "Apex"
    name = str(meta.get("hostname") or f"Apex ({host})")

    identifiers = {(DOMAIN, serial or host)}
    return DeviceInfo(
        identifiers=identifiers,
        name=name,
        manufacturer="Neptune Systems",
        model=model,
        serial_number=serial,
        hw_version=(str(meta.get("hardware") or "").strip() or None),
        sw_version=(str(meta.get("software") or "").strip() or None),
        configuration_url=f"http://{host}",
    )


def _is_simple_switchable_outlet(outlet: dict[str, Any]) -> bool:
    """Return True if an output looks like a basic on/off outlet.

    Args:
        outlet: Outlet dict from the coordinator.

    Returns:
        True if the outlet is safe to expose as a switch.
    """
    state = str(outlet.get("state") or "").strip().upper()
    if state not in {"AON", "AOF", "ON", "OFF"}:
        return False

    outlet_type = str(outlet.get("type") or "").strip()
    # Exclude MXM-controlled devices (pumps/lights/etc) for now.
    if (
        "MXM" in outlet_type
        or "MXMLIGHT" in outlet_type.upper()
        or "MXMPUMP" in outlet_type.upper()
    ):
        return False

    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Apex Fusion switches from a config entry.

    Args:
        hass: Home Assistant instance.
        entry: The config entry.
        async_add_entities: Callback to add entities.
    """
    coordinator: ApexNeptuneDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SwitchEntity] = []
    data = coordinator.data or {}
    outlets_any = data.get("outlets", [])

    if isinstance(outlets_any, list):
        for outlet_any in cast(list[Any], outlets_any):
            if not isinstance(outlet_any, dict):
                continue
            outlet = cast(dict[str, Any], outlet_any)
            did_any = outlet.get("device_id")
            did = did_any if isinstance(did_any, str) else None
            if not did:
                continue
            if not _is_simple_switchable_outlet(outlet):
                continue

            outlet_type_any: Any = outlet.get("type")
            outlet_type = outlet_type_any if isinstance(outlet_type_any, str) else None
            outlet_name = _friendly_outlet_name(
                outlet_name=str(outlet.get("name") or did),
                outlet_type=outlet_type,
            )

            entities.append(
                ApexOutletSwitch(
                    hass,
                    coordinator,
                    entry,
                    ref=_OutletRef(did=did, name=outlet_name),
                )
            )

    async_add_entities(entities)


class ApexOutletSwitch(SwitchEntity):
    """Switch controlling a basic on/off Apex outlet via REST."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: ApexNeptuneDataUpdateCoordinator,
        entry: ConfigEntry,
        *,
        ref: _OutletRef,
    ) -> None:
        """Initialize the switch.

        Args:
            hass: Home Assistant instance.
            coordinator: Data coordinator.
            entry: The config entry.
            ref: Outlet reference.
        """
        super().__init__()
        self.hass = hass
        self._coordinator = coordinator
        self._entry = entry
        self._ref = ref
        self._unsub: Callable[[], None] | None = None

        host = str(entry.data.get(CONF_HOST, ""))
        meta = cast(dict[str, Any], (coordinator.data or {}).get("meta", {}))
        serial = str(meta.get("serial") or host or "apex").replace(":", "_")

        self._attr_unique_id = f"{serial}_switch_{ref.did}".lower()
        self._attr_name = ref.name

        self._attr_device_info = _build_device_info(host=host, meta=meta)

        self._attr_available = bool(
            getattr(self._coordinator, "last_update_success", True)
        )
        self._attr_is_on = self._read_is_on()

        self._attr_extra_state_attributes = self._read_extra_attrs()

    def _find_outlet(self) -> dict[str, Any]:
        """Find this outlet in the coordinator outlets list."""
        data = self._coordinator.data or {}
        outlets_any = data.get("outlets", [])
        if not isinstance(outlets_any, list):
            return {}
        for outlet_any in cast(list[Any], outlets_any):
            if not isinstance(outlet_any, dict):
                continue
            outlet = cast(dict[str, Any], outlet_any)
            if str(outlet.get("device_id") or "") == self._ref.did:
                return outlet
        return {}

    def _read_is_on(self) -> bool:
        """Return True if the outlet state indicates ON."""
        outlet = self._find_outlet()
        state = str(outlet.get("state") or "").strip().upper()
        return state in {"AON", "ON"}

    def _read_extra_attrs(self) -> dict[str, Any]:
        """Expose extra outlet metadata and MXM info when available."""
        outlet = self._find_outlet()
        attrs: dict[str, Any] = {}
        for key in ("output_id", "type", "gid", "status"):
            if key in outlet:
                attrs[key] = outlet.get(key)

        name_any: Any = outlet.get("name")
        outlet_name = str(name_any).strip() if name_any is not None else ""
        mxm_any: Any = (self._coordinator.data or {}).get("mxm_devices")
        if outlet_name and isinstance(mxm_any, dict):
            mxm_devices = cast(dict[str, Any], mxm_any)
            dev_any: Any = mxm_devices.get(outlet_name)
            if isinstance(dev_any, dict):
                dev = cast(dict[str, Any], dev_any)
                attrs["mxm_rev"] = dev.get("rev")
                attrs["mxm_serial"] = dev.get("serial")
                attrs["mxm_status"] = dev.get("status")
        return attrs

    def _handle_coordinator_update(self) -> None:
        """Update state from coordinator data."""
        self._attr_available = bool(
            getattr(self._coordinator, "last_update_success", True)
        )
        self._attr_is_on = self._read_is_on()
        self._attr_extra_state_attributes = self._read_extra_attrs()
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Register coordinator update listener."""
        self._unsub = self._coordinator.async_add_listener(
            self._handle_coordinator_update
        )
        self._handle_coordinator_update()

    async def async_will_remove_from_hass(self) -> None:
        """Remove coordinator listener."""
        if self._unsub is not None:
            self._unsub()
            self._unsub = None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the outlet on."""
        await self._async_set_state("ON")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the outlet off."""
        await self._async_set_state("OFF")

    async def _async_set_state(self, state: str) -> None:
        """Set the outlet state via REST and refresh coordinator.

        Args:
            state: "ON" or "OFF".

        Raises:
            HomeAssistantError: If login or control fails.
        """
        host = str(self._entry.data.get(CONF_HOST, ""))
        username = str(self._entry.data.get(CONF_USERNAME, "") or "admin")
        password = str(self._entry.data.get(CONF_PASSWORD, "") or "")

        if not password:
            raise HomeAssistantError("Password is required to control outlets via REST")

        base_url = build_base_url(host)
        session = async_get_clientsession(self.hass)
        timeout_seconds = DEFAULT_TIMEOUT_SECONDS

        _LOGGER.debug(
            "Setting outlet state host=%s did=%s state=%s",
            host,
            self._ref.did,
            state,
        )

        # Login to get connect.sid.
        sid: str | None = None
        try:
            async with async_timeout.timeout(timeout_seconds):
                async with session.post(
                    f"{base_url}/rest/login",
                    json={
                        "login": username or "admin",
                        "password": password,
                        "remember_me": False,
                    },
                    headers={"Accept": "application/json"},
                ) as resp:
                    _LOGGER.debug("REST login for control HTTP %s", resp.status)
                    if resp.status == 404:
                        raise HomeAssistantError(
                            "REST API not supported on this device"
                        )
                    if resp.status in (401, 403):
                        raise HomeAssistantError("Invalid authentication")
                    resp.raise_for_status()
                    login_text = await resp.text()

            login_any: Any = json.loads(login_text) if login_text else {}
            if isinstance(login_any, dict):
                login_obj = cast(dict[str, Any], login_any)
                sid_any: Any = login_obj.get("connect.sid")
                if isinstance(sid_any, str) and sid_any:
                    sid = sid_any
        except (asyncio.TimeoutError, aiohttp.ClientError, json.JSONDecodeError) as err:
            raise HomeAssistantError(
                f"Error logging into Apex REST API: {err}"
            ) from err

        headers: dict[str, str] = {"Accept": "application/json"}
        if sid:
            headers["Cookie"] = f"connect.sid={sid}"

        payload = {
            "did": self._ref.did,
            "status": [state, "", "OK", ""],
            "type": "outlet",
        }

        try:
            async with async_timeout.timeout(timeout_seconds):
                async with session.put(
                    f"{base_url}/rest/status/outputs/{self._ref.did}",
                    json=payload,
                    headers=headers,
                ) as resp:
                    _LOGGER.debug("REST output PUT HTTP %s", resp.status)
                    if resp.status in (401, 403):
                        raise HomeAssistantError("Not authorized to control output")
                    resp.raise_for_status()
                    # Read body to complete request.
                    await resp.text()
        except (asyncio.TimeoutError, aiohttp.ClientError) as err:
            raise HomeAssistantError(f"Error setting output state: {err}") from err

        await self._coordinator.async_request_refresh()

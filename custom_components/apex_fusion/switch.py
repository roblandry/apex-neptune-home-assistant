"""Switch entities for Apex Fusion (Local).

For each outlet/output we expose two switches:
- "Auto": True when the outlet is in AUTO mode (AON/AOF)
- "State": True when the outlet is energized (AON/ON)

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
from yarl import URL

from .const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
    DEFAULT_TIMEOUT_SECONDS,
    DOMAIN,
    LOGGER_NAME,
)
from .coordinator import ApexNeptuneDataUpdateCoordinator, build_base_url

_LOGGER = logging.getLogger(LOGGER_NAME)


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


def _build_device_info(
    *, host: str, meta: dict[str, Any], device_identifier: str
) -> DeviceInfo:
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

    identifiers = {(DOMAIN, device_identifier)}
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


def _is_switchable_outlet(outlet: dict[str, Any]) -> bool:
    """Return True if an outlet exposes a supported state."""
    state = str(outlet.get("state") or "").strip().upper()
    # TBL indicates an output controlled by a schedule/table (AUTO).
    return state in {"AON", "AOF", "ON", "OFF", "TBL"}


def _is_auto_state(state: str) -> bool:
    return (state or "").strip().upper() in {"AON", "AOF", "TBL"}


def _is_energized_state(state: str) -> bool:
    # For scheduled/table-driven outputs the controller reports TBL; treat as
    # "on" for purposes of preserving state when leaving AUTO.
    return (state or "").strip().upper() in {"AON", "ON", "TBL"}


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

    added_dids: set[str] = set()

    def _add_outlet_switches() -> None:
        data = coordinator.data or {}
        outlets_any = data.get("outlets", [])
        new_entities: list[SwitchEntity] = []

        if isinstance(outlets_any, list):
            for outlet_any in cast(list[Any], outlets_any):
                if not isinstance(outlet_any, dict):
                    continue
                outlet = cast(dict[str, Any], outlet_any)
                did_any = outlet.get("device_id")
                did = did_any if isinstance(did_any, str) else None
                if not did or did in added_dids:
                    continue
                if not _is_switchable_outlet(outlet):
                    continue

                outlet_type_any: Any = outlet.get("type")
                outlet_type = (
                    outlet_type_any if isinstance(outlet_type_any, str) else None
                )
                outlet_name = _friendly_outlet_name(
                    outlet_name=str(outlet.get("name") or did),
                    outlet_type=outlet_type,
                )

                ref = _OutletRef(did=did, name=outlet_name)
                new_entities.append(
                    ApexOutletAutoSwitch(hass, coordinator, entry, ref=ref)
                )
                new_entities.append(
                    ApexOutletStateSwitch(hass, coordinator, entry, ref=ref)
                )
                added_dids.add(did)

        if new_entities:
            async_add_entities(new_entities)

    _add_outlet_switches()
    remove = coordinator.async_add_listener(_add_outlet_switches)
    entry.async_on_unload(remove)


class _ApexOutletBaseSwitch(SwitchEntity):
    """Common base for outlet control switches."""

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
        """Initialize the switch."""
        super().__init__()
        self.hass = hass
        self._coordinator = coordinator
        self._entry = entry
        self._ref = ref
        self._unsub: Callable[[], None] | None = None

        host = str(entry.data.get(CONF_HOST, ""))
        meta = cast(dict[str, Any], (coordinator.data or {}).get("meta", {}))
        serial = str(meta.get("serial") or host or "apex").replace(":", "_")

        self._serial_for_ids = serial

        self._attr_device_info = _build_device_info(
            host=host,
            meta=meta,
            device_identifier=coordinator.device_identifier,
        )

        self._attr_available = bool(
            getattr(self._coordinator, "last_update_success", True)
        )
        self._attr_is_on = False
        self._attr_extra_state_attributes = {}

    def _find_outlet(self) -> dict[str, Any]:
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

    def _read_raw_state(self) -> str:
        outlet = self._find_outlet()
        return str(outlet.get("state") or "").strip().upper()

    async def _async_set_mode(self, mode: str) -> None:
        host = str(self._entry.data.get(CONF_HOST, ""))
        username = str(self._entry.data.get(CONF_USERNAME, "") or "admin")
        password = str(self._entry.data.get(CONF_PASSWORD, "") or "")

        if not password:
            raise HomeAssistantError("Password is required to control outlets via REST")

        base_url = build_base_url(host)
        session = async_get_clientsession(self.hass)
        timeout_seconds = DEFAULT_TIMEOUT_SECONDS

        desired = (mode or "").strip().upper()
        if desired not in {"AUTO", "ON", "OFF"}:
            raise HomeAssistantError(f"Invalid outlet mode: {mode}")

        # Prefer existing cookie (reduces session churn / accidental invalidation).
        sid: str | None = None
        sid_morsel = session.cookie_jar.filter_cookies(URL(base_url)).get("connect.sid")
        if sid_morsel is not None and sid_morsel.value:
            sid = sid_morsel.value

        def _retry_after_seconds(headers: Any) -> float | None:
            try:
                value = headers.get("Retry-After")
                if value is None:
                    return None
                t = str(value).strip()
                if not t:
                    return None
                return float(int(t))
            except Exception:
                return None

        def _note_rate_limited(*, seconds: float) -> None:
            try:
                # Coordinator implements backoff for REST polling.
                disable = getattr(self._coordinator, "_disable_rest", None)
                if callable(disable):
                    disable(seconds=seconds, reason="rate_limited_control")
            except Exception:
                pass

        try:
            if not sid:
                login_candidates: list[str] = []
                if username:
                    login_candidates.append(username)
                if "admin" not in login_candidates:
                    login_candidates.append("admin")

                login_text = ""
                for login_user in login_candidates:
                    async with async_timeout.timeout(timeout_seconds):
                        async with session.post(
                            f"{base_url}/rest/login",
                            json={
                                "login": login_user,
                                "password": password,
                                "remember_me": False,
                            },
                            headers={
                                "Accept": "*/*",
                                "Content-Type": "application/json",
                            },
                        ) as resp:
                            _LOGGER.debug(
                                "REST login for control host=%s HTTP %s user=%s",
                                host,
                                resp.status,
                                login_user,
                            )
                            if resp.status == 404:
                                raise HomeAssistantError(
                                    "REST API not supported on this device"
                                )
                            if resp.status in (401, 403):
                                continue
                            if resp.status == 429:
                                retry_after = _retry_after_seconds(resp.headers)
                                backoff = (
                                    float(retry_after)
                                    if retry_after is not None
                                    else 300.0
                                )
                                _note_rate_limited(seconds=backoff)
                                raise HomeAssistantError(
                                    f"Controller rate limited REST login; retry after ~{int(backoff)}s"
                                )
                            resp.raise_for_status()
                            login_text = await resp.text()
                            break

                login_any: Any = json.loads(login_text) if login_text else {}
                if isinstance(login_any, dict):
                    sid_any: Any = cast(dict[str, Any], login_any).get("connect.sid")
                    if isinstance(sid_any, str) and sid_any:
                        sid = sid_any
        except (asyncio.TimeoutError, aiohttp.ClientError, json.JSONDecodeError) as err:
            raise HomeAssistantError(
                f"Error logging into Apex REST API: {err}"
            ) from err

        headers: dict[str, str] = {"Accept": "*/*"}
        if sid:
            headers["Cookie"] = f"connect.sid={sid}"

        payload = {
            "did": self._ref.did,
            "status": [desired, "", "OK", ""],
            "type": "outlet",
        }

        _LOGGER.debug(
            "Setting outlet mode host=%s did=%s mode=%s", host, self._ref.did, desired
        )

        try:
            async with async_timeout.timeout(timeout_seconds):
                async with session.put(
                    f"{base_url}/rest/status/outputs/{self._ref.did}",
                    json=payload,
                    headers=headers,
                ) as resp:
                    _LOGGER.debug("REST output PUT host=%s HTTP %s", host, resp.status)
                    if resp.status in (401, 403):
                        raise HomeAssistantError("Not authorized to control output")
                    if resp.status == 429:
                        retry_after = _retry_after_seconds(resp.headers)
                        backoff = (
                            float(retry_after) if retry_after is not None else 300.0
                        )
                        _note_rate_limited(seconds=backoff)
                        raise HomeAssistantError(
                            f"Controller rate limited REST control; retry after ~{int(backoff)}s"
                        )
                    resp.raise_for_status()
                    await resp.text()
        except (asyncio.TimeoutError, aiohttp.ClientError) as err:
            raise HomeAssistantError(f"Error setting output mode: {err}") from err

        await self._coordinator.async_request_refresh()

    def _read_extra_attrs(self) -> dict[str, Any]:
        outlet = self._find_outlet()
        raw_state = str(outlet.get("state") or "").strip().upper()
        return {
            "raw_state": raw_state or None,
            "auto": _is_auto_state(raw_state),
            "energized": _is_energized_state(raw_state) if raw_state else None,
        }

    def _read_is_on(self) -> bool:
        raise NotImplementedError

    def _handle_coordinator_update(self) -> None:
        self._attr_available = bool(
            getattr(self._coordinator, "last_update_success", True)
        )
        self._attr_is_on = self._read_is_on()
        self._attr_extra_state_attributes = self._read_extra_attrs()
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


class ApexOutletAutoSwitch(_ApexOutletBaseSwitch):
    """Switch representing AUTO mode (AON/AOF)."""

    _attr_has_entity_name = True

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: ApexNeptuneDataUpdateCoordinator,
        entry: ConfigEntry,
        *,
        ref: _OutletRef,
    ) -> None:
        super().__init__(hass, coordinator, entry, ref=ref)
        self._attr_unique_id = f"{self._serial_for_ids}_auto_{ref.did}".lower()
        self._attr_name = f"{ref.name} Auto"
        # Do not call async_write_ha_state() in __init__ (entity has no platform yet).
        self._attr_available = bool(
            getattr(self._coordinator, "last_update_success", True)
        )
        self._attr_is_on = self._read_is_on()
        self._attr_extra_state_attributes = self._read_extra_attrs()

    def _read_is_on(self) -> bool:
        return _is_auto_state(self._read_raw_state())

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set_mode("AUTO")

    async def async_turn_off(self, **kwargs: Any) -> None:
        # Leaving AUTO should preserve the current energized state.
        raw = self._read_raw_state()
        await self._async_set_mode("ON" if _is_energized_state(raw) else "OFF")


class ApexOutletStateSwitch(_ApexOutletBaseSwitch):
    """Switch representing energized state (always ON/OFF)."""

    _attr_has_entity_name = True

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: ApexNeptuneDataUpdateCoordinator,
        entry: ConfigEntry,
        *,
        ref: _OutletRef,
    ) -> None:
        super().__init__(hass, coordinator, entry, ref=ref)
        self._attr_unique_id = f"{self._serial_for_ids}_switch_{ref.did}".lower()
        self._attr_name = f"{ref.name} State"
        # Do not call async_write_ha_state() in __init__ (entity has no platform yet).
        self._attr_available = bool(
            getattr(self._coordinator, "last_update_success", True)
        )
        self._attr_is_on = self._read_is_on()
        self._attr_extra_state_attributes = self._read_extra_attrs()

    def _read_is_on(self) -> bool:
        return _is_energized_state(self._read_raw_state())

    async def async_turn_on(self, **kwargs: Any) -> None:
        # Forcing state implies leaving AUTO.
        await self._async_set_mode("ON")

    async def async_turn_off(self, **kwargs: Any) -> None:
        # Forcing state implies leaving AUTO.
        await self._async_set_mode("OFF")

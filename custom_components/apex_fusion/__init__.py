"""The Apex Fusion (Local) integration.

This integration communicates with Neptune Apex controllers over the local
network.
"""

from __future__ import annotations

import logging
from typing import Any, cast

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.util import slugify

from .apex_fusion.context import context_from_status
from .const import CONF_HOST, DOMAIN, LOGGER_NAME, PLATFORMS
from .coordinator import ApexNeptuneDataUpdateCoordinator

_LOGGER = logging.getLogger(LOGGER_NAME)


async def _async_prefix_entity_ids_with_tank(
    hass: HomeAssistant,
    entry: ConfigEntry,
    *,
    tank_slug: str,
) -> None:
    """Ensure entity_ids are tank-prefixed.

    Home Assistant uses `suggested_object_id` only when an entity is first
    created. This helper updates entity registry entries so their object ids
    include the tank slug.

    Args:
        hass: Home Assistant instance.
        entry: Config entry.
        tank_slug: Slug used to prefix object ids.

    Returns:
        None.
    """

    if not tank_slug:
        return

    try:
        from homeassistant.helpers import entity_registry as er

        ent_reg = er.async_get(hass)
        reg_entries = er.async_entries_for_config_entry(ent_reg, entry.entry_id)
        if not reg_entries:
            return

        for reg_entry in reg_entries:
            domain, _, old_object_id = str(reg_entry.entity_id).partition(".")
            if not domain or not old_object_id:
                continue
            if old_object_id.startswith(f"{tank_slug}_"):
                continue
            new_object_id = f"{tank_slug}_{old_object_id}"

            # Make a valid, unique entity_id.
            new_object_id = slugify(new_object_id) or new_object_id
            new_entity_id = f"{domain}.{new_object_id}"
            if ent_reg.async_get(new_entity_id) is not None:
                i = 2
                while True:
                    candidate = f"{domain}.{new_object_id}_{i}"
                    if ent_reg.async_get(candidate) is None:
                        new_entity_id = candidate
                        break
                    i += 1

            if new_entity_id != reg_entry.entity_id:
                ent_reg.async_update_entity(
                    reg_entry.entity_id, new_entity_id=new_entity_id
                )
    except Exception:  # noqa: BLE001
        _LOGGER.exception(
            "Failed to migrate Apex entity_ids for entry_id=%s", entry.entry_id
        )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Apex Fusion from a config entry.

    Args:
        hass: Home Assistant instance.
        entry: The config entry.

    Returns:
        True if setup succeeds.
    """
    coordinator = ApexNeptuneDataUpdateCoordinator(hass, entry=entry)
    await coordinator.async_config_entry_first_refresh()

    # Prefer the controller-reported hostname as the tank name.
    host = str(entry.data.get(CONF_HOST, ""))
    data: dict[str, Any] = coordinator.data or {}
    meta_any: Any = data.get("meta")
    meta = cast(dict[str, Any], meta_any) if isinstance(meta_any, dict) else {}
    hostname = str(meta.get("hostname") or "").strip() or None
    if not hostname:
        config_any: Any = data.get("config")
        if isinstance(config_any, dict):
            nconf_any: Any = cast(dict[str, Any], config_any).get("nconf")
            if isinstance(nconf_any, dict):
                hostname = (
                    str(cast(dict[str, Any], nconf_any).get("hostname") or "").strip()
                    or None
                )

    desired_title = (
        f"{hostname} ({host})"
        if hostname
        else str(entry.title or "").strip() or f"Apex ({host})"
    )
    if desired_title and str(entry.title or "") != desired_title:
        hass.config_entries.async_update_entry(entry, title=desired_title)

    # Prefer controller serial as a stable, non-IP unique_id.
    # This prevents duplicate entries (and entity collisions) when the same
    # controller is added under different hostnames/IPs.
    serial: str | None = str(meta.get("serial") or "").strip() or None

    if serial and entry.unique_id != serial:
        other_entries = hass.config_entries.async_entries(DOMAIN)
        if any(
            e.entry_id != entry.entry_id and str(e.unique_id or "") == serial
            for e in other_entries
        ):
            _LOGGER.warning(
                "Duplicate Apex config entries detected for serial=%s; remove extra entries to avoid inconsistent entities",
                serial,
            )
        else:
            hass.config_entries.async_update_entry(entry, unique_id=serial)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Ensure tank slug shows up in entity_ids even when entities already exist.
    ctx = context_from_status(
        host=host,
        entry_title=entry.title,
        controller_device_identifier=coordinator.device_identifier,
        status=coordinator.data,
    )
    tank_slug = ctx.tank_slug_with_entry_title(entry.title)
    await _async_prefix_entity_ids_with_tank(hass, entry, tank_slug=tank_slug)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry.

    Args:
        hass: Home Assistant instance.
        entry: The config entry.

    Returns:
        True if the entry was unloaded.
    """
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unload_ok

"""Apex Fusion identity/context helpers.

This module derives stable identifiers and naming slugs from a config entry and
coordinator data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from homeassistant.config_entries import ConfigEntry
from homeassistant.util import slugify

from ..const import CONF_HOST
from ..coordinator import ApexNeptuneDataUpdateCoordinator, clean_hostname_display

# -----------------------------------------------------------------------------
# Context
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class ApexFusionContext:
    """Common identity context derived from a config entry and coordinator data.

    Attributes:
        host: Controller host/IP from the config entry.
        meta: Controller meta dict (serial/hostname/type/hardware/etc.).
        controller_device_identifier: Stable identifier used for HA DeviceInfo.
        serial_for_ids: Stable token used for unique ids (prefer serial).
        hostname_disp: Display-friendly hostname.
        tank_slug: Slugified tank/controller name used in suggested object ids.
    """

    host: str
    meta: dict[str, Any]
    controller_device_identifier: str
    serial_for_ids: str
    hostname_disp: str
    tank_slug: str

    @classmethod
    def from_entry_and_coordinator(
        cls, entry: ConfigEntry, coordinator: ApexNeptuneDataUpdateCoordinator
    ) -> "ApexFusionContext":
        """Create an identity context from HA objects.

        Args:
            entry: Home Assistant config entry for this integration.
            coordinator: Data update coordinator for this entry.

        Returns:
            A populated `ApexFusionContext` instance.
        """
        host = str(entry.data.get(CONF_HOST, ""))

        data = coordinator.data or {}
        meta_any: Any = data.get("meta", {})
        meta = cast(dict[str, Any], meta_any) if isinstance(meta_any, dict) else {}

        serial_for_ids = str(meta.get("serial") or host or "apex").replace(":", "_")

        hostname_raw = str(meta.get("hostname") or "")
        hostname_disp = clean_hostname_display(hostname_raw) or ""

        # Preserve the existing preference order used throughout the integration.
        tank_slug = slugify(hostname_disp or hostname_raw.strip() or "tank")

        return cls(
            host=host,
            meta=meta,
            controller_device_identifier=coordinator.device_identifier,
            serial_for_ids=serial_for_ids,
            hostname_disp=hostname_disp,
            tank_slug=tank_slug,
        )

    def tank_slug_with_entry_title(self, entry_title: str | None) -> str:
        """Return a tank slug with an optional title fallback.

        Args:
            entry_title: The config entry title.

        Returns:
            A slug string suitable for suggested object ids.
        """

        hostname_raw = str(self.meta.get("hostname") or "").strip()
        title = str(entry_title or "").strip()
        return (
            slugify(self.hostname_disp or hostname_raw or title or "tank")
            or title
            or "tank"
        )

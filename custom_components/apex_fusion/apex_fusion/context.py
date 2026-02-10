"""Apex Fusion identity/context helpers.

This module is part of the internal API package and intentionally avoids
Home Assistant imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, cast

from .util import slugify_label


def clean_hostname_display(hostname: str | None) -> str | None:
    """Return a display-friendly hostname/tank name.

    Controllers commonly report hostnames with underscores. UIs read better with
    spaces, so normalize for display only.
    """

    h = str(hostname or "").strip()
    if not h:
        return None
    return h.replace("_", " ").strip() or None


def context_from_status(
    *,
    host: str,
    entry_title: str | None,
    controller_device_identifier: str,
    status: Mapping[str, Any] | None,
) -> "ApexFusionContext":
    """Build an `ApexFusionContext` from primitive inputs and normalized status.

    This is intentionally HA-free so the internal API package can be used from
    the CLI and so the HA integration can stay thin.
    """

    data = status or {}
    meta_any: Any = data.get("meta", {})
    meta = cast(dict[str, Any], meta_any) if isinstance(meta_any, Mapping) else {}

    hostname_raw = str(meta.get("hostname") or "")
    hostname_disp = clean_hostname_display(hostname_raw) or ""

    return ApexFusionContext.from_meta(
        host=host,
        meta=meta,
        controller_device_identifier=controller_device_identifier,
        hostname_disp=hostname_disp,
        entry_title=entry_title,
    )


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
    def from_meta(
        cls,
        *,
        host: str,
        meta: Mapping[str, Any] | None,
        controller_device_identifier: str,
        hostname_disp: str | None = None,
        entry_title: str | None = None,
    ) -> "ApexFusionContext":
        """Create an identity context from controller meta and host information.

        Args:
            host: Controller host/IP.
            meta: Controller meta mapping (serial/hostname/type/hardware/etc.).
            controller_device_identifier: Stable identifier used for HA DeviceInfo.
            hostname_disp: Display-friendly hostname (optional).
            entry_title: Config entry title (optional).

        Returns:
            A populated `ApexFusionContext` instance.
        """
        meta_any: Any = meta or {}
        if isinstance(meta_any, Mapping):
            meta_map = cast(Mapping[str, Any], meta_any)
            meta_dict = dict(meta_map)
        else:
            meta_dict = {}

        host_s = str(host or "")
        serial_for_ids = str(meta_dict.get("serial") or host_s or "apex").replace(
            ":", "_"
        )

        hostname_raw = str(meta_dict.get("hostname") or "").strip()
        hostname_disp_s = str(hostname_disp or "").strip()

        tank_slug = slugify_label(
            hostname_disp_s or hostname_raw or str(entry_title or "") or "tank"
        )
        if not tank_slug:
            tank_slug = slugify_label(str(entry_title or "")) or "tank"

        return cls(
            host=host_s,
            meta=meta_dict,
            controller_device_identifier=str(controller_device_identifier or ""),
            serial_for_ids=serial_for_ids,
            hostname_disp=hostname_disp_s,
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
            slugify_label(self.hostname_disp or hostname_raw or title or "tank")
            or slugify_label(title)
            or "tank"
        )

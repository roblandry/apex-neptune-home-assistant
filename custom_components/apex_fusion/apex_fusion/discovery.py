"""Entity discovery helpers for Apex Fusion.

Entity platforms should avoid interpreting coordinator payloads directly.
This module centralizes schema-tolerant extraction of entity references
(lightweight dataclasses describing what to create).

This module does not perform network I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, cast

from .outputs import OutletMode, friendly_outlet_name
from .probes import friendly_probe_name

# -----------------------------------------------------------------------------
# Entity References
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class ProbeRef:
    """Reference to a non-digital probe sensor.

    Attributes:
        key: Probe key from the controller payload.
        name: Friendly name for display in Home Assistant.
    """

    key: str
    name: str


@dataclass(frozen=True)
class DigitalProbeRef:
    """Reference to a digital probe (open/closed) binary sensor.

    Attributes:
        key: Probe key from the controller payload.
        name: Friendly name for display in Home Assistant.
    """

    key: str
    name: str


@dataclass(frozen=True)
class OutletIntensityRef:
    """Reference to an outlet intensity sensor.

    Attributes:
        did: Outlet device id from the controller payload.
        name: Friendly name for display in Home Assistant.
    """

    did: str
    name: str


@dataclass(frozen=True)
class OutletRef:
    """Reference to an outlet mode SelectEntity.

    Attributes:
        did: Outlet device id from the controller payload.
        name: Friendly name for display in Home Assistant.
    """

    did: str
    name: str


# -----------------------------------------------------------------------------
# Discovery
# -----------------------------------------------------------------------------


class ApexDiscovery:
    """Discover entities from coordinator data.

    Methods return (new_refs, new_ids) so callers can maintain per-platform
    deduplication without this module mutating caller-owned sets.
    """

    @staticmethod
    def new_probe_refs(
        data: Mapping[str, Any] | None,
        *,
        already_added_keys: set[str],
    ) -> tuple[list[ProbeRef], set[str]]:
        """Discover new non-digital probes.

        Args:
            data: Coordinator data.
            already_added_keys: Keys that have already been used to create
                entities.

        Returns:
            Tuple of:
              - A list of discovered probe references.
              - A set of probe keys discovered during this call.
        """

        coordinator_data = data or {}
        probes_any: Any = coordinator_data.get("probes")
        if not isinstance(probes_any, dict):
            return [], set()

        refs: list[ProbeRef] = []
        seen: set[str] = set()

        for key, probe_any in cast(dict[str, Any], probes_any).items():
            key_str = str(key)
            if not key_str or key_str in already_added_keys or key_str in seen:
                continue
            probe: dict[str, Any] = (
                cast(dict[str, Any], probe_any) if isinstance(probe_any, dict) else {}
            )
            probe_type = str(probe.get("type") or "")
            if probe_type.strip().lower() == "digital":
                seen.add(key_str)
                continue

            probe_name = str(probe.get("name") or key_str)
            refs.append(
                ProbeRef(
                    key=key_str,
                    name=friendly_probe_name(name=probe_name, probe_type=probe_type),
                )
            )
            seen.add(key_str)

        return refs, seen

    @staticmethod
    def new_digital_probe_refs(
        data: Mapping[str, Any] | None,
        *,
        already_added_keys: set[str],
    ) -> tuple[list[DigitalProbeRef], set[str]]:
        """Discover new digital probes.

        Args:
            data: Coordinator data.
            already_added_keys: Keys that have already been used to create
                entities.

        Returns:
            Tuple of:
              - A list of discovered digital probe references.
              - A set of probe keys discovered during this call.
        """

        coordinator_data = data or {}
        probes_any: Any = coordinator_data.get("probes")
        if not isinstance(probes_any, dict):
            return [], set()

        refs: list[DigitalProbeRef] = []
        seen: set[str] = set()

        for key, probe_any in cast(dict[str, Any], probes_any).items():
            key_str = str(key)
            if not key_str or key_str in already_added_keys or key_str in seen:
                continue
            if not isinstance(probe_any, Mapping):
                continue

            probe = cast(Mapping[str, Any], probe_any)
            probe_type = str(probe.get("type") or "").strip().lower()
            if probe_type != "digital":
                continue

            probe_name = str(probe.get("name") or key_str).strip() or key_str
            friendly = probe_name.replace("_", " ").strip()

            refs.append(DigitalProbeRef(key=key_str, name=friendly))
            seen.add(key_str)

        return refs, seen

    @staticmethod
    def new_outlet_intensity_refs(
        data: Mapping[str, Any] | None,
        *,
        already_added_dids: set[str],
    ) -> tuple[list[OutletIntensityRef], set[str]]:
        """Discover new outlet intensity sensors.

        Args:
            data: Coordinator data.
            already_added_dids: Outlet DIDs that have already been used to
                create entities.

        Returns:
            Tuple of:
              - A list of discovered outlet intensity references.
              - A set of outlet DIDs discovered during this call.
        """

        coordinator_data = data or {}
        outlets_any: Any = coordinator_data.get("outlets")
        if not isinstance(outlets_any, list):
            return [], set()

        refs: list[OutletIntensityRef] = []
        seen: set[str] = set()

        for outlet_any in cast(list[Any], outlets_any):
            if not isinstance(outlet_any, Mapping):
                continue

            outlet = cast(Mapping[str, Any], outlet_any)
            did_any: Any = outlet.get("device_id")
            did = did_any if isinstance(did_any, str) else None
            if not did or did in already_added_dids or did in seen:
                continue

            intensity_any: Any = outlet.get("intensity")
            if not isinstance(intensity_any, (int, float)) or isinstance(
                intensity_any, bool
            ):
                continue

            outlet_type_any: Any = outlet.get("type")
            outlet_type = outlet_type_any if isinstance(outlet_type_any, str) else None
            outlet_name = friendly_outlet_name(
                outlet_name=str(outlet.get("name") or did),
                outlet_type=outlet_type,
            )

            refs.append(OutletIntensityRef(did=did, name=f"{outlet_name} Intensity"))
            seen.add(did)

        return refs, seen

    @staticmethod
    def new_outlet_select_refs(
        data: Mapping[str, Any] | None,
        *,
        already_added_dids: set[str],
    ) -> tuple[list[OutletRef], set[str]]:
        """Discover new outlet select references.

        Args:
            data: Coordinator data.
            already_added_dids: Outlet DIDs that have already been used to
                create entities.

        Returns:
            Tuple of:
              - A list of discovered outlet references.
              - A set of outlet DIDs discovered during this call.
        """

        coordinator_data = data or {}
        outlets_any: Any = coordinator_data.get("outlets")
        if not isinstance(outlets_any, list):
            return [], set()

        refs: list[OutletRef] = []
        seen: set[str] = set()

        for outlet_any in cast(list[Any], outlets_any):
            if not isinstance(outlet_any, Mapping):
                continue

            outlet = cast(dict[str, Any], outlet_any)
            did_any: Any = outlet.get("device_id")
            did = did_any if isinstance(did_any, str) else None
            if not did or did in already_added_dids or did in seen:
                continue
            if not OutletMode.is_selectable_outlet(outlet):
                continue

            outlet_type_any: Any = outlet.get("type")
            outlet_type = outlet_type_any if isinstance(outlet_type_any, str) else None
            outlet_name = friendly_outlet_name(
                outlet_name=str(outlet.get("name") or did),
                outlet_type=outlet_type,
            )

            refs.append(OutletRef(did=did, name=outlet_name))
            seen.add(did)

        return refs, seen

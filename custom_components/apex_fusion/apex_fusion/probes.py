"""Apex Fusion probe helpers.

Centralized probe naming, icons, and unit/metadata selection.

This module is part of the internal API package and intentionally avoids
Home Assistant imports.
"""

from __future__ import annotations

from typing import Any

ICON_THERMOMETER = "mdi:thermometer"
ICON_PH = "mdi:ph"
ICON_SHAKER_OUTLINE = "mdi:shaker-outline"
ICON_FLASH = "mdi:flash"
ICON_CURRENT_AC = "mdi:current-ac"
ICON_TEST_TUBE = "mdi:test-tube"
ICON_FLASK = "mdi:flask"
ICON_FLASK_OUTLINE = "mdi:flask-outline"
ICON_GAUGE = "mdi:gauge"

# -----------------------------------------------------------------------------
# Conversions
# -----------------------------------------------------------------------------


def as_float(value: Any) -> float | None:
    """Convert a value to a float when possible.

    Args:
        value: Value to convert.

    Returns:
        A float when the input is numeric or a numeric string; otherwise `None`.
    """

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        t = value.strip()
        if not t:
            return None
        try:
            return float(t)
        except ValueError:
            return None
    return None


class ProbeMetaResolver:
    """Resolve icons, friendly names, and metadata for probe values."""

    @staticmethod
    def icon_for_probe_type(probe_type: str, probe_name: str) -> str | None:
        """Return an icon for a probe type/name.

        Args:
            probe_type: Probe type token.
            probe_name: Probe name.

        Returns:
            A Material Design Icon string.
        """
        t = (probe_type or "").strip().lower()
        n = (probe_name or "").strip().lower()

        if t in {"temp", "tmp"}:
            return ICON_THERMOMETER
        if t == "ph":
            return ICON_PH
        if t == "cond":
            return ICON_SHAKER_OUTLINE if n.startswith("salt") else ICON_FLASH
        if t == "amps":
            return ICON_CURRENT_AC
        if t == "alk":
            return ICON_TEST_TUBE
        if t == "ca":
            return ICON_FLASK
        if t == "mg":
            return ICON_FLASK_OUTLINE
        return ICON_GAUGE

    @staticmethod
    def friendly_probe_name(*, name: str, probe_type: str | None) -> str:
        """Return a friendly display name for a probe.

        Args:
            name: Raw probe name.
            probe_type: Raw probe type token.

        Returns:
            Friendly probe name for display.
        """
        n = (name or "").strip()
        t = (probe_type or "").strip().lower()

        if t == "ph":
            return "pH"
        if t == "temp":
            return "Temperature"
        if t == "cond":
            return "Conductivity"
        if t == "orp":
            return "ORP"

        if t == "alk":
            return "Alkalinity"
        if t == "ca":
            return "Calcium"
        if t == "mg":
            return "Magnesium"

        # TODO: validate with real Trident NP data. (Issue: https://github.com/roblandry/apex-fusion-home-assistant/issues/8)
        if t in {"no3", "nitrate", "nitrogen"}:
            return "Nitrogen"
        if t in {"po4", "phosphate"}:
            return "Phosphate"

        return n

    @staticmethod
    def temp_unit(value: float | None) -> str:
        """Choose a temperature unit based on the numeric value.

        Args:
            value: Numeric temperature reading.

        Returns:
            Temperature unit selected from the numeric range.
        """
        # TODO: see if there is a better way to determine this; maybe there is a unit
        # field somewhere in the data?
        # Values <= 45 are treated as Celsius; higher values as Fahrenheit.
        if value is not None and value <= 45:
            return "°C"
        return "°F"

    @staticmethod
    def units_and_meta(
        *,
        probe_name: str,
        probe_type: str,
        value: float | None,
    ) -> tuple[str | None, str | None, str | None]:
        """Resolve unit and neutral metadata for a probe reading.

        Args:
            probe_name: Probe name.
            probe_type: Probe type token.
            value: Parsed numeric value.

        Returns:
            Tuple of (unit, device_class_token, state_class_token).
        """
        t = (probe_type or "").strip().lower()
        _ = (probe_name or "").strip().lower()

        if t == "ph":
            return None, None, "measurement"
        if t == "temp":
            return (
                ProbeMetaResolver.temp_unit(value),
                "temperature",
                "measurement",
            )
        if t == "cond":
            return "ppt", None, "measurement"
        if t == "orp":
            return "mV", None, "measurement"

        if t == "alk":
            return "dKH", None, "measurement"
        if t in ("ca", "mg"):
            return "ppm", None, "measurement"

        # TODO: validate with real Trident NP data. (Issue: https://github.com/roblandry/apex-fusion-home-assistant/issues/8)
        if t in {"no3", "nitrate"} or t in {"po4", "phosphate"}:
            return "ppm", None, "measurement"

        return None, None, "measurement"


def icon_for_probe_type(probe_type: str, probe_name: str) -> str | None:
    """Return an icon for a probe type/name.

    Args:
        probe_type: Probe type token.
        probe_name: Probe name.

    Returns:
        A Material Design Icon string.
    """
    return ProbeMetaResolver.icon_for_probe_type(probe_type, probe_name)


def friendly_probe_name(*, name: str, probe_type: str | None) -> str:
    """Return a friendly display name for a probe.

    Args:
        name: Raw probe name.
        probe_type: Raw probe type token.

    Returns:
        Friendly probe name for display.
    """
    return ProbeMetaResolver.friendly_probe_name(name=name, probe_type=probe_type)


def units_and_meta(
    *,
    probe_name: str,
    probe_type: str,
    value: float | None,
) -> tuple[str | None, str | None, str | None]:
    """Resolve unit and neutral metadata for a probe reading.

    Args:
        probe_name: Probe name.
        probe_type: Probe type token.
        value: Parsed numeric value.

    Returns:
        Tuple of (unit, device_class_token, state_class_token).
    """
    return ProbeMetaResolver.units_and_meta(
        probe_name=probe_name, probe_type=probe_type, value=value
    )

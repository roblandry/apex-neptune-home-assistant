"""Apex Fusion output helpers.

Centralized outlet/output naming, icons, and mode/state normalization.
"""

from __future__ import annotations

from typing import Any

ICON_PUMP = "mdi:pump"
ICON_LIGHTBULB = "mdi:lightbulb"
ICON_RADIATOR = "mdi:radiator"
ICON_POWER_SOCKET_US = "mdi:power-socket-us"
ICON_ALARM = "mdi:alarm"
ICON_TOGGLE_SWITCH_OUTLINE = "mdi:toggle-switch-outline"

# -----------------------------------------------------------------------------
# Formatting
# -----------------------------------------------------------------------------


def pretty_model(s: str) -> str:
    """Prettify a model token.

    Args:
        s: Raw model token from controller payloads.

    Returns:
        A human-friendly model string (for example, `"Nero5"` -> `"Nero 5"`).
    """
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


def friendly_outlet_name(*, outlet_name: str, outlet_type: str | None) -> str:
    """Return a better display name for an outlet/output.

    Args:
        outlet_name: Raw outlet name.
        outlet_type: Raw outlet type token.

    Returns:
        A friendly outlet name for display.
    """
    raw_name = (outlet_name or "").strip()
    raw_type = (outlet_type or "").strip()
    if not raw_name:
        return raw_name

    if raw_type.strip().lower() == "selector":
        head = raw_name.split("_", 1)[0].strip().lower()
        if head == "trident":
            return "Combined Testing"
        if head == "alk":
            return "Alkalinity Testing"

        # TODO: validate with real Trident NP data; may need more mappings. (Issue: https://github.com/roblandry/apex-fusion-home-assistant/issues/7)
        if head in {"tnp", "np"}:
            return "Trident NP"

    parts = [p.strip() for p in raw_type.split("|") if p.strip()]
    if len(parts) >= 3 and parts[0].upper().startswith("MXM"):
        vendor = parts[1]
        model = pretty_model(parts[2])
        pretty_name = raw_name.replace("_", " ").strip()
        label = f"{vendor} {model}".strip()
        if pretty_name and pretty_name.lower() not in label.lower():
            return f"{label} ({pretty_name})"
        return label

    return raw_name.replace("_", " ").strip()


def icon_for_outlet_type(outlet_type: str | None) -> str | None:
    """Return an icon for an outlet based on its device type.

    Args:
        outlet_type: Raw outlet type token.

    Returns:
        A Material Design Icon string.
    """
    t = (outlet_type or "").strip().upper()
    if "PUMP" in t:
        return ICON_PUMP
    if "LIGHT" in t:
        return ICON_LIGHTBULB
    if "HEATER" in t:
        return ICON_RADIATOR
    return ICON_POWER_SOCKET_US


class OutletMode:
    """Encode/decode Apex outlet states and HA Select options."""

    OPTIONS: list[str] = ["Off", "Auto", "On"]

    @staticmethod
    def is_energized_state(raw_state: str) -> bool:
        """Return True when a controller state implies the outlet is energized.

        Args:
            raw_state: Raw controller state token.

        Returns:
            True when the state token implies power is energized.
        """
        return (raw_state or "").strip().upper() in {"AON", "ON", "TBL"}

    @staticmethod
    def is_selectable_outlet(outlet: dict[str, Any]) -> bool:
        """Return True when an outlet exposes a 3-way mode select.

        Args:
            outlet: Outlet dict from coordinator data.

        Returns:
            True when the current `state` is one of the known selectable tokens.
        """
        raw_state = str(outlet.get("state") or "").strip().upper()
        return raw_state in {"AON", "AOF", "TBL", "ON", "OFF"}

    @staticmethod
    def option_from_raw_state(raw_state: str) -> str | None:
        """Convert a controller state token to a Home Assistant option label.

        Args:
            raw_state: Raw controller state token.

        Returns:
            Home Assistant option label, or `None` if the token is unknown.
        """
        t = (raw_state or "").strip().upper()
        if t in {"ON"}:
            return "On"
        if t in {"OFF"}:
            return "Off"
        if t in {"AON", "AOF", "TBL"}:
            return "Auto"
        return None

    @staticmethod
    def effective_state_from_raw_state(raw_state: str) -> str | None:
        """Return an effective On/Off state for a raw token.

        Args:
            raw_state: Raw controller state token.

        Returns:
            `"On"`, `"Off"`, or `None` if the token is empty.
        """
        t = (raw_state or "").strip().upper()
        if not t:
            return None
        return "On" if OutletMode.is_energized_state(t) else "Off"

    @staticmethod
    def mode_from_option(option: str) -> str:
        """Convert a Home Assistant option label to a controller command token.

        Args:
            option: Home Assistant select option label.

        Returns:
            Controller mode token suitable for REST commands.

        Raises:
            ValueError: If the option label is invalid.
        """
        t = (option or "").strip().lower()
        if t == "auto":
            return "AUTO"
        if t == "on":
            return "ON"
        if t == "off":
            return "OFF"
        raise ValueError(f"Invalid option: {option}")

    @staticmethod
    def icon_for_outlet_select(outlet_name: str, outlet_type: str | None) -> str | None:
        """Choose an icon for an outlet mode SelectEntity.

        Args:
            outlet_name: Outlet name.
            outlet_type: Outlet type token.

        Returns:
            A Material Design Icon string.
        """
        name = (outlet_name or "").strip().lower()
        t = (outlet_type or "").strip().upper()

        if any(token in name for token in ("alarm", "warn")):
            return ICON_ALARM
        if "PUMP" in t:
            return ICON_PUMP
        if "LIGHT" in t:
            return ICON_LIGHTBULB
        if "HEATER" in t:
            return ICON_RADIATOR
        return ICON_TOGGLE_SWITCH_OUTLINE

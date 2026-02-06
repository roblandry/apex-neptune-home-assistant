"""Constants for the Apex Fusion (Local) integration.

This module centralizes configuration keys, defaults, and platform registration.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "apex_fusion"

# Use a stable logger name so users can configure logging via
# `logger: default: ... logs: { custom_components.apex_fusion: debug }`.
LOGGER_NAME: Final = f"custom_components.{DOMAIN}"

CONF_HOST: Final = "host"
CONF_USERNAME: Final = "username"
CONF_PASSWORD: Final = "password"
CONF_STATUS_PATH: Final = "status_path"

DEFAULT_USERNAME: Final = "admin"
DEFAULT_PASSWORD: Final = ""
DEFAULT_STATUS_PATH: Final = "/cgi-bin/status.xml"

DEFAULT_SCAN_INTERVAL: Final = timedelta(seconds=30)
DEFAULT_TIMEOUT_SECONDS: Final[int] = 10

PLATFORMS: Final[list[Platform]] = [
    Platform.SENSOR,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.UPDATE,
]

# Friendly module names for Aquabus hardware types.
#
# These are used for Home Assistant device naming (not for identifiers), so the
# UI shows descriptive names instead of short hwtype tokens.
MODULE_HWTYPE_FRIENDLY_NAMES: Final[dict[str, str]] = {
    "FMM": "Fluid Monitoring Module",
    "PM2": "Salinity Probe Module",
    "PM1": "pH/ORP Probe Module",
    "MXM": "Mobius Wireless Control Module",
    "VDM": "LED & Pump Control Module",
    "PM3": "Dissolved Oxygen Module",
    "AFS": "Automatic Feeding System",
    "LSM": "Lunar Simulator Module",
    # Common/related modules (not explicitly requested, but keeps naming tidy).
    "TRI": "Trident",
    "TNP": "Trident NP",
}

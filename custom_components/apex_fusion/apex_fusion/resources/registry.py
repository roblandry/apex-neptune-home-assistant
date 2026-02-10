"""Resource registry.

To add a new resource:
    1) Create a new module file in this package.
    2) Define `SPEC = ResourceSpec(name=..., extract=...)`.

The registry auto-discovers resource modules so callers don't need to maintain a
manual import list.

This module intentionally avoids Home Assistant imports.
"""

from __future__ import annotations

import pkgutil
from importlib import import_module
from typing import Any

from .base import ResourceSpec


def _load_resources() -> dict[str, ResourceSpec]:
    resources: dict[str, ResourceSpec] = {}

    package_name = __name__.rsplit(".", 1)[0]
    package = import_module(package_name)

    for module_info in pkgutil.iter_modules(package.__path__):  # type: ignore[attr-defined]
        name = module_info.name
        if name.startswith("_") or name in {
            "base",
            "registry",
            "config",
            "mxm_devices",
        }:
            continue

        module = import_module(f"{package_name}.{name}")
        spec_any: Any = getattr(module, "SPEC", None)
        if not isinstance(spec_any, ResourceSpec):
            continue

        spec = spec_any
        key = (spec.name or "").strip().lower()
        if not key:
            continue
        resources[key] = spec

    return resources


RESOURCES: dict[str, ResourceSpec] = _load_resources()


def get_resource(name: str) -> ResourceSpec:
    """Lookup a resource by name.

    Args:
        name: Resource name.

    Returns:
        The registered `ResourceSpec`.

    Raises:
        KeyError: When no resource is registered.
    """
    key = (name or "").strip().lower()
    if not key:
        raise KeyError("Resource name is required")

    spec = RESOURCES.get(key)
    if spec is None:
        raise KeyError(f"Unknown resource: {name}")
    return spec


def extract_resource(name: str, status: dict[str, Any]) -> Any:
    """Extract a resource from a normalized status payload."""
    return get_resource(name).extract(status)

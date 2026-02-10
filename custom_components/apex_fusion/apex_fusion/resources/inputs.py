"""Input resource.

In the normalized payload, controller "inputs" are stored under the `probes`
section (because the Apex payloads treat probe readings and digital inputs in a
similar way).

This module intentionally avoids Home Assistant imports.
"""

from __future__ import annotations

from .base import ResourceSpec
from .probes import extract_probes


def extract_inputs(status: dict[str, object]):
    """Alias for `probes` for callers that prefer the term "inputs"."""
    # Keep the return JSON identical to probes.
    return extract_probes(status)  # type: ignore[arg-type]


SPEC = ResourceSpec(name="inputs", extract=extract_inputs)

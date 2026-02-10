"""Internal API exception types.

These exceptions are raised by the standalone API client and helpers. The Home
Assistant integration should translate these into HA-specific exception types.

This module intentionally avoids Home Assistant imports.
"""

from __future__ import annotations


class ApexFusionError(Exception):
    """Base exception for Apex Fusion API failures."""


class ApexFusionAuthError(ApexFusionError):
    """Authentication rejected or missing for an operation."""


class ApexFusionNotSupportedError(ApexFusionError):
    """Endpoint not available on the controller."""


class ApexFusionRateLimitedError(ApexFusionError):
    """Controller rate-limited a request.

    Attributes:
        retry_after_seconds: Optional backoff value derived from Retry-After.
    """

    def __init__(
        self, message: str, *, retry_after_seconds: float | None = None
    ) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class ApexFusionRestDisabledError(ApexFusionError):
    """REST is temporarily disabled due to prior rate limiting."""

    def __init__(
        self, message: str, *, retry_after_seconds: float | None = None
    ) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class ApexFusionTransportError(ApexFusionError):
    """Network or protocol error communicating with the controller."""


class ApexFusionParseError(ApexFusionError):
    """Payload could not be parsed or normalized."""

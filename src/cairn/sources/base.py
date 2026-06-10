"""DeviceSource contract that every MDM/EDR provider implements.

A source knows how to authenticate to one upstream system and yield
NormalizedDevice records. Two access patterns are supported:

  * fetch_all()        -> full fleet pull (server/fleet mode)
  * find_by_serial(s)  -> single-device lookup (agent mode on an endpoint)

Subclasses MUST implement `fetch_all`. `find_by_serial` has a safe default that
filters `fetch_all`, but providers should override it with a server-side query
when the API supports one (cheaper, faster).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Iterable, Optional

from ..models import NormalizedDevice

logger = logging.getLogger(__name__)


class SourceConfigError(Exception):
    """Raised when a provider is enabled but misconfigured."""


class DeviceSource(ABC):
    #: Stable, lowercase key used in config and the registry (e.g. "jamf").
    key: str = "base"
    #: Human-friendly name for logs/notifications.
    display_name: str = "Device Source"

    def __init__(self, config: dict):
        self.config = config or {}
        self.validate_config()
        self.setup()

    # --- lifecycle hooks -------------------------------------------------
    def validate_config(self) -> None:
        """Raise SourceConfigError if required keys are missing. Override."""

    def setup(self) -> None:
        """Build sessions / token managers. Override."""

    def require(self, *keys: str) -> None:
        missing = [k for k in keys if not self.config.get(k)]
        if missing:
            raise SourceConfigError(
                f"{self.display_name} missing required config: {', '.join(missing)}"
            )

    # --- data access -----------------------------------------------------
    @abstractmethod
    def fetch_all(self) -> Iterable[NormalizedDevice]:
        """Yield every device this source knows about (paginated internally)."""

    def find_by_serial(self, serial: str) -> Optional[NormalizedDevice]:
        """Default: linear scan of fetch_all. Override with a server-side query."""
        target = (serial or "").strip().upper()
        for device in self.fetch_all():
            if device.serial == target:
                return device
        return None

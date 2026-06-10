"""AssetSink contract: where reconciled devices get written (CMDB/ITAM)."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Optional

from ..models import NormalizedDevice

logger = logging.getLogger(__name__)


class SinkConfigError(Exception):
    pass


class SyncResult:
    """Outcome of a single upsert, for notifications and reporting."""

    CREATED = "created"
    UPDATED = "updated"
    SKIPPED = "skipped"
    FAILED = "failed"

    def __init__(self, action: str, serial: str, identifier: str = "", detail: str = ""):
        self.action = action
        self.serial = serial
        self.identifier = identifier  # asset tag / id in the sink
        self.detail = detail

    def __repr__(self) -> str:
        return f"SyncResult({self.action} {self.serial} {self.identifier})"


class AssetSink(ABC):
    key: str = "base"
    display_name: str = "Asset Sink"

    def __init__(self, config: dict):
        self.config = config or {}
        self.validate_config()
        self.setup()

    def validate_config(self) -> None:
        pass

    def setup(self) -> None:
        pass

    def require(self, *keys: str) -> None:
        missing = [k for k in keys if not self.config.get(k)]
        if missing:
            raise SinkConfigError(
                f"{self.display_name} missing required config: {', '.join(missing)}"
            )

    @abstractmethod
    def upsert(self, device: NormalizedDevice, dry_run: bool = False) -> SyncResult:
        """Create or update the asset record for `device`. Honor dry_run."""

"""Writeback contract: push Snipe-IT values back into an MDM (reverse sync).

Where a source READS device data into Snipe-IT, a writeback WRITES a chosen field
(today: the Snipe-IT asset tag) back into the MDM that manages the device — the
`snipe2jamf` / Snipe-IT→Intune direction.

Writeback mutates a system you may not fully own, so:
  * it is dry-run-first (the orchestrator defaults writeback to preview),
  * it honors a conflict policy (`snipe_wins` | `only_if_empty`),
  * it never invents devices: if the MDM has no device with that serial, it skips.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from ..models import NormalizedDevice

logger = logging.getLogger(__name__)

# Conflict policies for an MDM field that already has a value.
SNIPE_WINS = "snipe_wins"        # overwrite the MDM value with Snipe-IT's
ONLY_IF_EMPTY = "only_if_empty"  # only set the MDM field when it is currently blank


class WritebackConfigError(Exception):
    pass


class WritebackResult:
    UPDATED = "updated"
    SKIPPED = "skipped"   # no change needed / policy declined / no match
    FAILED = "failed"

    def __init__(self, action: str, serial: str, detail: str = ""):
        self.action = action
        self.serial = serial
        self.detail = detail

    def __repr__(self) -> str:
        return f"WritebackResult({self.action} {self.serial} {self.detail})"


class Writeback(ABC):
    key: str = "base"
    display_name: str = "Writeback"

    def __init__(self, config: dict):
        self.config = config or {}
        self.conflict = self.config.get("conflict", SNIPE_WINS)
        if self.conflict not in (SNIPE_WINS, ONLY_IF_EMPTY):
            raise WritebackConfigError(
                f"{self.display_name}: conflict must be '{SNIPE_WINS}' or '{ONLY_IF_EMPTY}'"
            )
        self.validate_config()
        self.setup()

    def validate_config(self) -> None:
        pass

    def setup(self) -> None:
        pass

    def require(self, *keys: str) -> None:
        missing = [k for k in keys if not self.config.get(k)]
        if missing:
            raise WritebackConfigError(
                f"{self.display_name} missing required config: {', '.join(missing)}"
            )

    def _resolve_policy(self, current: str | None, desired: str) -> bool:
        """Return True if we should write `desired` given the `current` MDM value."""
        if not desired:
            return False
        if (current or "") == desired:
            return False  # already correct
        if self.conflict == ONLY_IF_EMPTY and (current or "").strip():
            return False
        return True

    @abstractmethod
    def push(self, device: NormalizedDevice, dry_run: bool = True) -> WritebackResult:
        """Push the Snipe-IT asset tag (device.asset_tag) into the MDM device that
        matches device.serial. Honor dry_run and the conflict policy."""

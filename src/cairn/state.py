"""Incremental-sync state: skip devices that haven't changed since last run.

On a schedule, most devices don't change between runs. Re-writing every asset
every time wastes API calls, rate-limit budget, and Snipe-IT load. Cairn keeps a
small JSON map of `serial -> content-hash`; if a device hashes the same as last
time, the upsert is skipped.

Volatile fields (default: `last_seen`) are excluded from the hash so a device
that merely checked in again doesn't count as "changed" and trigger a needless
write. Override via config `incremental_ignore_fields`.

The state file is tiny (one short line per device) and written atomically.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from typing import Any, Iterable, Optional

from .models import NormalizedDevice

logger = logging.getLogger(__name__)

# Fields included in the change hash. last_seen is intentionally excluded by
# default (it ticks on every check-in and would defeat the optimization).
_HASHED_FIELDS = (
    "hostname", "os_name", "os_version", "os_build", "model", "manufacturer",
    "primary_user", "primary_user_email", "logged_in_users", "compliance",
    "encrypted", "mac_addresses",
)
_DEFAULT_IGNORE = ("last_seen",)


def default_state_path() -> str:
    """Platform-appropriate default location for the state file."""
    env = os.environ.get("CAIRN_STATE")
    if env:
        return env
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        return os.path.join(base, "Cairn", "state.json")
    return os.path.join(os.path.expanduser("~"), ".cairn", "state.json")


class SyncState:
    def __init__(
        self,
        path: Optional[str] = None,
        enabled: bool = True,
        ignore_fields: Optional[Iterable[str]] = None,
    ):
        self.path = path or default_state_path()
        self.enabled = enabled
        ignore = set(ignore_fields if ignore_fields is not None else _DEFAULT_IGNORE)
        self.fields = tuple(f for f in _HASHED_FIELDS if f not in ignore)
        self._hashes: dict[str, str] = {}
        self._dirty = False
        if self.enabled:
            self._load()

    def _load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("devices"), dict):
                self._hashes = {str(k): str(v) for k, v in data["devices"].items()}
                logger.debug("Loaded sync state: %d devices from %s",
                             len(self._hashes), self.path)
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as e:
            # Corrupt or unreadable state must never block a sync; start fresh.
            logger.warning("Could not read state %s (%s); starting fresh.", self.path, e)
            self._hashes = {}

    def device_hash(self, device: NormalizedDevice) -> str:
        parts: list[str] = []
        for field in self.fields:
            value: Any = getattr(device, field, None)
            if isinstance(value, list):
                value = ",".join(sorted(str(x) for x in value))
            parts.append(f"{field}={value if value is not None else ''}")
        blob = "|".join(parts)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    def is_unchanged(self, device: NormalizedDevice) -> bool:
        if not self.enabled:
            return False
        return self._hashes.get(device.serial) == self.device_hash(device)

    def mark_synced(self, device: NormalizedDevice) -> None:
        if not self.enabled:
            return
        self._hashes[device.serial] = self.device_hash(device)
        self._dirty = True

    def save(self) -> None:
        if not self.enabled or not self._dirty:
            return
        directory = os.path.dirname(self.path) or "."
        os.makedirs(directory, exist_ok=True)
        # Atomic write: temp file in the same dir, then rename.
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".cairn-state-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"version": 1, "devices": self._hashes}, f)
            os.replace(tmp, self.path)
            if os.name != "nt":
                os.chmod(self.path, 0o600)
            self._dirty = False
            logger.debug("Saved sync state: %d devices to %s", len(self._hashes), self.path)
        except OSError as e:
            logger.warning("Could not write state %s: %s", self.path, e)
            try:
                os.unlink(tmp)
            except OSError:
                pass

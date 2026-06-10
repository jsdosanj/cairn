"""Kandji device source.

Reads the Apple-device fleet from the Kandji API (``/api/v1/devices``) using a
static API token (``Authorization: Bearer ...``) -- Kandji does not use OAuth.
The devices endpoint returns a bare JSON list of device objects, so pagination
is offset/limit based: keep advancing the offset until a short page arrives.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable, Optional
from urllib.parse import quote

from ..models import NormalizedDevice
from ..http import (
    build_session,
    request_json,
    require_https,
    HttpError,
    DEFAULT_TIMEOUT,
)
from .base import DeviceSource, SourceConfigError

logger = logging.getLogger(__name__)

# Kandji caps the devices endpoint at 300 records per page.
_MAX_PAGE_SIZE = 300

# Map Kandji's `platform` value to a normalized OS name and asset class.
_PLATFORM_OS = {
    "Mac": "macOS",
    "iPhone": "iOS",
    "iPod": "iOS",
    "iPad": "iPadOS",
    "AppleTV": "tvOS",
}
_PLATFORM_ASSET_TYPE = {
    "Mac": "computer",
    "iPhone": "mobile",
    "iPad": "mobile",
    "iPod": "mobile",
}


class KandjiSource(DeviceSource):
    key = "kandji"
    display_name = "Kandji"

    # --- lifecycle -------------------------------------------------------
    def validate_config(self) -> None:
        api_url = self.config.get("api_url")
        if not api_url:
            raise SourceConfigError(
                f"{self.display_name} missing required config: api_url"
            )
        if not self.config.get("api_token"):
            raise SourceConfigError(
                f"{self.display_name} missing required config: api_token"
            )
        require_https(api_url, f"{self.display_name} api_url")

    def setup(self) -> None:
        self.base_url = str(self.config["api_url"]).rstrip("/")
        page_size = int(self.config.get("page_size", _MAX_PAGE_SIZE) or _MAX_PAGE_SIZE)
        self.page_size = min(page_size, _MAX_PAGE_SIZE)
        self.session = build_session(
            headers={
                "Authorization": f"Bearer {self.config['api_token']}",
                "Accept": "application/json",
            }
        )

    # --- helpers ---------------------------------------------------------
    def _to_device(self, device: dict[str, Any]) -> Optional[NormalizedDevice]:
        """Map one Kandji device record to a NormalizedDevice; None if unusable."""
        try:
            platform = device.get("platform")
            os_name = _PLATFORM_OS.get(platform, platform)
            asset_type = _PLATFORM_ASSET_TYPE.get(platform, "computer")

            # `user` may be a dict {"name", "email"}, a bare string, or null.
            user = device.get("user")
            primary_user: Optional[str] = None
            primary_user_email: Optional[str] = None
            if isinstance(user, dict):
                primary_user = user.get("name")
                primary_user_email = user.get("email")
            elif isinstance(user, str):
                primary_user = user

            macs: list[str] = []
            mac = device.get("mac_address")
            if mac:
                macs.append(mac)

            device_id = device.get("device_id")

            return NormalizedDevice(
                serial=device.get("serial_number"),
                source="kandji",
                source_id=str(device_id) if device_id is not None else None,
                asset_type=asset_type,
                hostname=device.get("device_name"),
                mac_addresses=macs,
                os_name=os_name,
                os_version=device.get("os_version"),
                model=device.get("model"),
                manufacturer="Apple",
                primary_user=primary_user,
                primary_user_email=primary_user_email,
                last_seen=device.get("last_check_in"),
                raw=device,
            )
        except Exception as e:  # never let one bad record kill the pull
            logger.warning(
                "%s: skipping malformed device record id=%r: %s",
                self.display_name,
                device.get("device_id") if isinstance(device, dict) else "?",
                e,
            )
            return None

    # --- data access -----------------------------------------------------
    def fetch_all(self) -> Iterable[NormalizedDevice]:
        offset = 0
        while True:
            url = (
                f"{self.base_url}/api/v1/devices"
                f"?limit={self.page_size}&offset={offset}"
            )
            payload = request_json(self.session, "GET", url, timeout=DEFAULT_TIMEOUT)
            devices = payload or []
            if not isinstance(devices, list):
                logger.warning(
                    "%s: expected a list of devices, got %s",
                    self.display_name,
                    type(devices).__name__,
                )
                break
            if not devices:
                break

            for device in devices:
                if not isinstance(device, dict):
                    logger.warning(
                        "%s: skipping non-dict device record", self.display_name
                    )
                    continue
                normalized = self._to_device(device)
                if normalized is not None:
                    yield normalized

            # A short page means we've reached the end of the fleet.
            if len(devices) < self.page_size:
                break
            offset += self.page_size

    def find_by_serial(self, serial: str) -> Optional[NormalizedDevice]:
        target = (serial or "").strip()
        if not target:
            return None

        url = f"{self.base_url}/api/v1/devices?serial_number={quote(target)}"
        try:
            payload = request_json(self.session, "GET", url, timeout=DEFAULT_TIMEOUT)
        except HttpError as e:
            logger.warning(
                "%s: serial lookup failed for %r, falling back to scan: %s",
                self.display_name,
                target,
                e,
            )
            return super().find_by_serial(serial)

        if isinstance(payload, list) and payload:
            first = payload[0]
            if isinstance(first, dict):
                device = self._to_device(first)
                if device is not None:
                    return device

        # Empty/unexpected response: fall back to the linear scan.
        return super().find_by_serial(serial)

"""JumpCloud System API source.

JumpCloud authenticates with an API key header (`x-api-key`), not OAuth. Multi-
tenant orgs scope requests with an `x-org-id` header. We page the `/systems`
endpoint with limit/skip until a short page signals the end.

Note: JumpCloud serial numbers can be absent on some platforms (e.g. certain
Linux distros or VMs report no hardware serial). Such records still map to a
NormalizedDevice; the model substitutes "UNKNOWN" for the serial, so callers
should not assume every JumpCloud system is correlatable by serial.
"""

from __future__ import annotations

import logging
from typing import Iterable, Optional

from ..http import HttpError, build_session, request_json, require_https
from ..models import NormalizedDevice
from .base import DeviceSource, SourceConfigError

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://console.jumpcloud.com/api"
_MAX_PAGE_SIZE = 100
_DEFAULT_PAGE_SIZE = 100
_LOOPBACK_MAC = "00:00:00:00:00:00"


class JumpCloudSource(DeviceSource):
    key = "jumpcloud"
    display_name = "JumpCloud"

    def validate_config(self) -> None:
        self.require("api_key")

    def setup(self) -> None:
        self.api_key = self.config["api_key"]
        self.org_id = self.config.get("org_id")
        self.base_url = (self.config.get("base_url") or _DEFAULT_BASE_URL).rstrip("/")
        require_https(self.base_url, f"{self.display_name} base_url")

        page_size = self.config.get("page_size") or _DEFAULT_PAGE_SIZE
        try:
            page_size = int(page_size)
        except (TypeError, ValueError):
            page_size = _DEFAULT_PAGE_SIZE
        self.page_size = max(1, min(page_size, _MAX_PAGE_SIZE))

        headers = {"x-api-key": self.api_key, "Content-Type": "application/json"}
        if self.org_id:
            headers["x-org-id"] = str(self.org_id)
        self.session = build_session(headers=headers)

    # --- data access -----------------------------------------------------
    def fetch_all(self) -> Iterable[NormalizedDevice]:
        url = f"{self.base_url}/systems"
        skip = 0
        while True:
            params = {"limit": self.page_size, "skip": skip}
            payload = request_json(self.session, "GET", url, params=params)
            results = (payload or {}).get("results") or []
            for system in results:
                device = self._map_system(system)
                if device is not None:
                    yield device
            if len(results) < self.page_size:
                break
            skip += self.page_size

    def find_by_serial(self, serial: str) -> Optional[NormalizedDevice]:
        target = (serial or "").strip()
        if not target:
            return None
        url = f"{self.base_url}/systems"
        params = {"filter": f"serialNumber:eq:{target}", "limit": 1}
        try:
            payload = request_json(self.session, "GET", url, params=params)
        except HttpError as e:
            logger.warning(
                "%s server-side serial filter failed for %r, falling back to scan: %s",
                self.display_name,
                target,
                e,
            )
            return super().find_by_serial(serial)
        results = (payload or {}).get("results") or []
        if not results:
            return None
        return self._map_system(results[0])

    # --- mapping ---------------------------------------------------------
    def _map_system(self, system: dict) -> Optional[NormalizedDevice]:
        if not isinstance(system, dict):
            logger.warning("%s skipping non-dict system record", self.display_name)
            return None
        try:
            serial = system.get("serialNumber")
            hostname = system.get("displayName") or system.get("hostname")
            os_name = self._normalize_os(system.get("os"))
            model = system.get("hardwareModel")
            manufacturer = system.get("systemModelName") or system.get("vendor")

            encrypted = None
            if "fdeActive" in system:
                encrypted = bool(system.get("fdeActive"))
            elif "fileVaultActive" in system:
                encrypted = bool(system.get("fileVaultActive"))

            return NormalizedDevice(
                serial=serial,
                source="jumpcloud",
                source_id=system.get("_id"),
                hostname=hostname,
                mac_addresses=self._extract_macs(system),
                os_name=os_name,
                os_version=system.get("version"),
                model=model,
                manufacturer=manufacturer,
                last_seen=system.get("lastContact"),
                encrypted=encrypted,
                raw=system,
            )
        except Exception as e:  # defensive: never let one bad record kill the pull
            logger.warning(
                "%s skipping unmappable system %r: %s",
                self.display_name,
                system.get("_id"),
                e,
            )
            return None

    @staticmethod
    def _normalize_os(os_value: Optional[str]) -> Optional[str]:
        if not os_value:
            return None
        lowered = str(os_value).strip().lower()
        if "mac" in lowered:  # "Mac OS X", "macOS"
            return "macOS"
        if "windows" in lowered:
            return "Windows"
        # Linux / distro names (ubuntu, debian, centos, rhel, fedora, etc.)
        return "Linux"

    @staticmethod
    def _extract_macs(system: dict) -> list[str]:
        macs: list[str] = []
        for iface in system.get("networkInterfaces") or []:
            if not isinstance(iface, dict):
                continue
            addr = iface.get("address")
            if addr:
                macs.append(addr)
        top = system.get("macAddress")
        if top:
            macs.append(top)
        return [m for m in macs if str(m).strip().upper() != _LOOPBACK_MAC]

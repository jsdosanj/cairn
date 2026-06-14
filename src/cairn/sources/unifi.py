"""UniFi Network Integration API source (self-hosted UniFi OS controller).

Targets the UniFi Network *Integration* API exposed on a local/self-hosted
controller at `/proxy/network/integration/v1`. Auth is an `X-API-KEY` header.
Because these controllers (UDM, Cloud Key, self-hosted) ship a self-signed TLS
certificate by default, point the optional `ca_bundle` config key at the
controller's CA so verification still happens against a trusted root.

Note: UniFi devices are network gear (asset_type "network") and frequently
report no hardware serial number. Such records still map to a NormalizedDevice;
the model substitutes "UNKNOWN" for the serial, so these devices are best
correlated by MAC address rather than serial.
"""

from __future__ import annotations

import logging
from typing import Iterable

from ..http import build_session, request_json, require_https, resolve_verify
from ..models import NormalizedDevice
from .base import DeviceSource, SourceConfigError

logger = logging.getLogger(__name__)

_DEFAULT_PAGE_SIZE = 200


class UniFiSource(DeviceSource):
    key = "unifi"
    display_name = "UniFi"

    def validate_config(self) -> None:
        if not self.config.get("host"):
            raise SourceConfigError(f"{self.display_name} missing required config: host")
        if not self.config.get("api_key"):
            raise SourceConfigError(
                f"{self.display_name} missing required config: api_key"
            )
        require_https(self.config["host"], f"{self.display_name} host")

    def setup(self) -> None:
        host = str(self.config["host"]).rstrip("/")
        self.base = host + "/proxy/network/integration/v1"

        self.site = self.config.get("site")

        page_size = self.config.get("page_size") or _DEFAULT_PAGE_SIZE
        try:
            page_size = int(page_size)
        except (TypeError, ValueError):
            page_size = _DEFAULT_PAGE_SIZE
        self.page_size = max(1, page_size)

        self.session = build_session(
            headers={"X-API-KEY": self.config["api_key"], "Accept": "application/json"}
        )
        # Self-signed certs are the norm on local UniFi OS controllers; point
        # ca_bundle at the controller's CA rather than disabling verification.
        self.session.verify = resolve_verify(self.config, host)

    # --- data access -----------------------------------------------------
    def fetch_all(self) -> Iterable[NormalizedDevice]:
        for site_id in self._site_ids():
            yield from self._fetch_site_devices(site_id)

    def _site_ids(self) -> list[str]:
        if self.site:
            return [self.site]
        payload = request_json(self.session, "GET", f"{self.base}/sites")
        sites = (payload or {}).get("data") or []
        ids: list[str] = []
        for site in sites:
            if not isinstance(site, dict):
                logger.warning("%s skipping non-dict site record", self.display_name)
                continue
            site_id = site.get("id")
            if site_id:
                ids.append(site_id)
        return ids

    def _fetch_site_devices(self, site_id: str) -> Iterable[NormalizedDevice]:
        url = f"{self.base}/sites/{site_id}/devices"
        offset = 0
        collected = 0
        while True:
            params = {"offset": offset, "limit": self.page_size}
            payload = request_json(self.session, "GET", url, params=params) or {}
            data = payload.get("data") or []
            for device in data:
                normalized = self._map_device(device, site_id)
                if normalized is not None:
                    yield normalized
            collected += len(data)
            total = payload.get("totalCount")
            if isinstance(total, int) and collected >= total:
                break
            if len(data) < self.page_size:
                break
            offset += self.page_size

    # --- mapping ---------------------------------------------------------
    def _map_device(self, device: dict, site_id: str):
        if not isinstance(device, dict):
            logger.warning(
                "%s skipping non-dict device record (site %s)",
                self.display_name,
                site_id,
            )
            return None
        try:
            serial = device.get("serialNumber") or device.get("serial")
            mac = device.get("macAddress") or device.get("mac")
            mac_addresses = [mac] if mac else []
            os_version = device.get("firmwareVersion") or device.get("version")
            last_seen = device.get("lastSeen") or device.get("uptime")

            return NormalizedDevice(
                serial=serial,
                source="unifi",
                source_id=device.get("id"),
                asset_type="network",
                hostname=device.get("name"),
                mac_addresses=mac_addresses,
                os_name=None,
                os_version=os_version,
                model=device.get("model"),
                manufacturer="Ubiquiti",
                last_seen=last_seen,
                extra={
                    "state": device.get("state"),
                    "ipAddress": device.get("ipAddress"),
                    "type": device.get("type"),
                },
                raw=device,
            )
        except Exception as e:  # defensive: never let one bad record kill the pull
            logger.warning(
                "%s skipping unmappable device %r (site %s): %s",
                self.display_name,
                device.get("id"),
                site_id,
                e,
            )
            return None

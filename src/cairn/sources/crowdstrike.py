"""CrowdStrike Falcon device source.

Falcon authenticates with OAuth2 client credentials and exposes a two-step
device API: a query endpoint that returns device-id pages and an entities
endpoint that hydrates ids into full device records.

The API base URL is region-specific. Pick the one for your Falcon cloud:

  * US-1 (default): https://api.crowdstrike.com
  * US-2:           https://api.us-2.crowdstrike.com
  * EU-1:           https://api.eu-1.crowdstrike.com
  * US-Gov-1:       https://api.laggar.gcw.crowdstrike.com
"""

from __future__ import annotations

import logging
from typing import Iterable, Optional

from ..http import OAuth2ClientCredentials, build_session, request_json
from ..models import NormalizedDevice
from .base import DeviceSource, SourceConfigError

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.crowdstrike.com"
#: CrowdStrike caps device-id queries at 5000 ids per page.
MAX_QUERY_LIMIT = 5000
#: The entities endpoint hydrates at most 100 ids per request.
HYDRATE_BATCH = 100

#: Map Falcon's platform_name onto Cairn's canonical os_name values.
_PLATFORM_MAP = {
    "Mac": "macOS",
    "Windows": "Windows",
    "Linux": "Linux",
}


class CrowdStrikeSource(DeviceSource):
    """Pulls the device fleet from CrowdStrike Falcon (region-specific base_url)."""

    key = "crowdstrike"
    display_name = "CrowdStrike Falcon"

    def validate_config(self) -> None:
        self.require("client_id", "client_secret")

    def setup(self) -> None:
        self.base_url = str(
            self.config.get("base_url") or DEFAULT_BASE_URL
        ).rstrip("/")
        try:
            self.page_size = int(self.config.get("page_size", MAX_QUERY_LIMIT))
        except (TypeError, ValueError):
            raise SourceConfigError(
                f"{self.display_name} page_size must be an integer"
            )
        if self.page_size <= 0:
            self.page_size = MAX_QUERY_LIMIT

        self.oauth = OAuth2ClientCredentials(
            token_url=f"{self.base_url}/oauth2/token",
            client_id=self.config["client_id"],
            client_secret=self.config["client_secret"],
            # Falcon expects client_id/client_secret in the form body.
            auth_in_header=False,
        )
        self.session = build_session()

    # --- internal helpers ------------------------------------------------
    def _query_device_ids(self, **params) -> tuple[list[str], int]:
        """Run a single device-query call; return (ids, total)."""
        url = f"{self.base_url}/devices/queries/devices/v1"
        payload = request_json(
            self.session,
            "GET",
            url,
            params=params,
            headers=self.oauth.bearer_header(),
        ) or {}
        ids = payload.get("resources") or []
        meta = payload.get("meta") or {}
        pagination = meta.get("pagination") or {}
        try:
            total = int(pagination.get("total", len(ids)))
        except (TypeError, ValueError):
            total = len(ids)
        return list(ids), total

    def _hydrate(self, ids: list[str]) -> Iterable[NormalizedDevice]:
        """Hydrate device ids (any count) in batches of HYDRATE_BATCH."""
        url = f"{self.base_url}/devices/entities/devices/v2"
        for start in range(0, len(ids), HYDRATE_BATCH):
            batch = ids[start:start + HYDRATE_BATCH]
            if not batch:
                continue
            payload = request_json(
                self.session,
                "POST",
                url,
                json={"ids": batch},
                headers=self.oauth.bearer_header(),
            ) or {}
            for device in payload.get("resources") or []:
                normalized = self._normalize(device)
                if normalized is not None:
                    yield normalized

    def _normalize(self, device: dict) -> Optional[NormalizedDevice]:
        """Map a Falcon device dict onto a NormalizedDevice; skip junk."""
        if not isinstance(device, dict):
            logger.warning("crowdstrike: skipping non-dict device record")
            return None
        try:
            platform = device.get("platform_name")
            os_name = _PLATFORM_MAP.get(platform, platform)

            mac = device.get("mac_address")
            macs = [mac] if mac else []

            # machine_domain is a domain, not a user; only surface a real user
            # when last_login_user is present.
            primary_user = device.get("last_login_user") or None

            return NormalizedDevice(
                serial=device.get("serial_number"),
                source="crowdstrike",
                source_id=device.get("device_id"),
                hostname=device.get("hostname"),
                mac_addresses=macs,
                os_name=os_name,
                os_version=device.get("os_version"),
                os_build=device.get("os_build"),
                model=device.get("system_product_name"),
                manufacturer=device.get("system_manufacturer"),
                primary_user=primary_user,
                last_seen=device.get("last_seen"),
                raw=device,
            )
        except Exception:  # defensive: never let one bad record kill the pull
            logger.warning(
                "crowdstrike: skipping malformed device %r",
                device.get("device_id"),
                exc_info=True,
            )
            return None

    # --- data access -----------------------------------------------------
    def fetch_all(self) -> Iterable[NormalizedDevice]:
        limit = min(self.page_size, MAX_QUERY_LIMIT)
        offset = 0
        collected = 0
        total = None

        while True:
            ids, page_total = self._query_device_ids(limit=limit, offset=offset)
            if total is None:
                total = page_total
            if not ids:
                break

            yield from self._hydrate(ids)

            collected += len(ids)
            offset += len(ids)
            if total is not None and collected >= total:
                break

    def find_by_serial(self, serial: str) -> Optional[NormalizedDevice]:
        serial = (serial or "").strip()
        if not serial:
            return None
        ids, _ = self._query_device_ids(filter=f"serial_number:'{serial}'")
        if not ids:
            return None
        for device in self._hydrate(ids):
            return device
        return None

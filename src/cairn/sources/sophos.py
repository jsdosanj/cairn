"""Sophos Central source via the Sophos Central API.

Auth is a three-step dance: (1) OAuth2 client-credentials against id.sophos.com
yields a bearer token; (2) a `GET /whoami/v1` resolves the tenant id and the
*regional* API host (`apiHosts.dataRegion`, e.g. https://api-us03...) that all
subsequent endpoint calls must target; (3) endpoint calls carry both the bearer
token and an `X-Tenant-ID` header. The whoami lookup is done lazily on first
fetch via `_ensure_tenant()` so constructing the source does no network I/O.

Note: Sophos endpoint records frequently lack a serial number, so the
NormalizedDevice serial often falls through to "UNKNOWN" and cross-provider
correlation then relies on hostname/MAC instead of the serial join key.
"""

from __future__ import annotations

import logging
from typing import Iterable, Optional

from ..models import NormalizedDevice
from ..http import build_session, request_json, OAuth2ClientCredentials
from .base import DeviceSource, SourceConfigError

logger = logging.getLogger(__name__)

_TOKEN_URL = "https://id.sophos.com/api/v2/oauth2/token"
_WHOAMI_URL = "https://api.central.sophos.com/whoami/v1"
_PAGE_SIZE = 500


def _normalize_os(os_obj: dict) -> Optional[str]:
    """Map Sophos `os.platform`/`os.name` onto Cairn's canonical OS names."""
    if not isinstance(os_obj, dict):
        return None
    platform = (os_obj.get("platform") or "").strip().lower()
    if platform == "macos":
        return "macOS"
    if platform == "windows":
        return "Windows"
    if platform == "linux":
        return "Linux"
    return os_obj.get("name") or (os_obj.get("platform") or None)


class SophosSource(DeviceSource):
    key = "sophos"
    display_name = "Sophos Central"

    def validate_config(self) -> None:
        self.require("client_id", "client_secret")

    def setup(self) -> None:
        self.client_id = self.config["client_id"]
        self.client_secret = self.config["client_secret"]

        self.oauth = OAuth2ClientCredentials(
            token_url=_TOKEN_URL,
            client_id=self.client_id,
            client_secret=self.client_secret,
            scope="token",
        )
        self.session = build_session()
        # Resolved lazily by _ensure_tenant() on first fetch.
        self.tenant_id: Optional[str] = None
        self.api_host: Optional[str] = None

    # --- tenant resolution ----------------------------------------------
    def _ensure_tenant(self) -> None:
        """Resolve tenant id + regional API host via /whoami (cached)."""
        if self.tenant_id and self.api_host:
            return
        payload = request_json(
            self.session, "GET", _WHOAMI_URL, headers=self.oauth.bearer_header()
        )
        payload = payload or {}
        self.tenant_id = payload.get("id")
        api_host = (payload.get("apiHosts") or {}).get("dataRegion")
        if not self.tenant_id or not api_host:
            raise SourceConfigError(
                f"{self.display_name} whoami returned no tenant id / data region"
            )
        self.api_host = str(api_host).rstrip("/")

    def _endpoint_headers(self) -> dict[str, str]:
        headers = self.oauth.bearer_header()
        headers["X-Tenant-ID"] = self.tenant_id or ""
        return headers

    # --- mapping ---------------------------------------------------------
    def _to_device(self, item: dict) -> Optional[NormalizedDevice]:
        """Map one Sophos endpoint payload to a NormalizedDevice."""
        if not isinstance(item, dict):
            logger.warning("Sophos: skipping non-dict endpoint record")
            return None

        os_obj = item.get("os") or {}
        os_version = None
        if isinstance(os_obj, dict):
            os_version = os_obj.get("version") or os_obj.get("build")

        person = item.get("associatedPerson") or {}
        primary_user = None
        if isinstance(person, dict):
            primary_user = person.get("viaLogin") or person.get("name")

        macs = item.get("macAddresses")
        mac_addresses = list(macs) if isinstance(macs, list) else []

        compliance = None
        health = item.get("health")
        if isinstance(health, dict) and health.get("overall"):
            compliance = (
                "compliant"
                if str(health.get("overall")).strip().lower() == "good"
                else "noncompliant"
            )

        encrypted = None
        if item.get("encryption") is not None:
            enc = item.get("encryption")
            if isinstance(enc, dict):
                # Some payloads nest an overall status under encryption.
                status = (enc.get("overall") or "").strip().lower()
                encrypted = status == "encrypted" if status else None
            else:
                encrypted = bool(enc)

        return NormalizedDevice(
            serial=item.get("serialNumber"),
            source="sophos",
            source_id=item.get("id"),
            hostname=item.get("hostname"),
            mac_addresses=mac_addresses,
            os_name=_normalize_os(os_obj),
            os_version=os_version,
            primary_user=primary_user,
            last_seen=item.get("lastSeenAt"),
            compliance=compliance,
            encrypted=encrypted,
            raw=item,
        )

    # --- data access -----------------------------------------------------
    def fetch_all(self) -> Iterable[NormalizedDevice]:
        self._ensure_tenant()
        base = f"{self.api_host}/endpoint/v1/endpoints"
        next_key: Optional[str] = None
        while True:
            url = f"{base}?pageSize={_PAGE_SIZE}"
            if next_key:
                url = f"{base}?pageFromKey={next_key}"
            payload = request_json(
                self.session, "GET", url, headers=self._endpoint_headers()
            )
            payload = payload or {}
            for item in payload.get("items") or []:
                device = self._to_device(item)
                if device is not None:
                    yield device
            next_key = (payload.get("pages") or {}).get("nextKey")
            if not next_key:
                break

    # find_by_serial: inherit base-class linear scan; Sophos endpoint listing
    # does not reliably filter by serial.

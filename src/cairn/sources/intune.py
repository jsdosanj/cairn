"""Microsoft Intune source via the Microsoft Graph API.

Authenticates with OAuth2 client credentials against Azure AD and pulls
managed devices from `/deviceManagement/managedDevices`, mapping each Graph
payload into a NormalizedDevice. Token fetching/caching is delegated to the
shared OAuth2ClientCredentials helper.
"""

from __future__ import annotations

import logging
from typing import Iterable, Optional
from urllib.parse import quote

from ..models import NormalizedDevice
from ..http import build_session, request_json, OAuth2ClientCredentials
from .base import DeviceSource, SourceConfigError

logger = logging.getLogger(__name__)

_DEFAULT_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_DEFAULT_LOGIN_BASE = "https://login.microsoftonline.com"


def _normalize_os(raw_os: Optional[str]) -> Optional[str]:
    """Map Graph's `operatingSystem` onto Cairn's canonical OS names."""
    if not raw_os:
        return None
    value = str(raw_os).strip().lower()
    if value in ("macos", "macmdm", "mac os", "os x"):
        return "macOS"
    if value == "windows":
        return "Windows"
    if value == "ios":
        return "iOS"
    if value == "android":
        return "Android"
    if value == "linux":
        return "Linux"
    return raw_os


def _normalize_compliance(state: Optional[str]) -> Optional[str]:
    """Graph reports many compliance states; collapse to Cairn's vocabulary."""
    if not state:
        return None
    value = str(state).strip().lower()
    if value == "compliant":
        return "compliant"
    if value == "unknown":
        return "unknown"
    return "noncompliant"


class IntuneSource(DeviceSource):
    key = "intune"
    display_name = "Microsoft Intune"

    def validate_config(self) -> None:
        self.require("tenant_id", "client_id", "client_secret")

    def setup(self) -> None:
        self.tenant_id = self.config["tenant_id"]
        self.client_id = self.config["client_id"]
        self.client_secret = self.config["client_secret"]
        self.graph_base = (
            self.config.get("graph_base") or _DEFAULT_GRAPH_BASE
        ).rstrip("/")
        self.login_base = (
            self.config.get("login_base") or _DEFAULT_LOGIN_BASE
        ).rstrip("/")

        self.oauth = OAuth2ClientCredentials(
            token_url=f"{self.login_base}/{self.tenant_id}/oauth2/v2.0/token",
            client_id=self.client_id,
            client_secret=self.client_secret,
            scope="https://graph.microsoft.com/.default",
        )
        self.session = build_session()

    # --- mapping ---------------------------------------------------------
    def _to_device(self, item: dict) -> Optional[NormalizedDevice]:
        """Map one Graph managedDevice payload to a NormalizedDevice."""
        if not isinstance(item, dict):
            logger.warning("Intune: skipping non-dict managedDevice record")
            return None

        macs: list[str] = []
        for key in ("wiFiMacAddress", "ethernetMacAddress"):
            mac = item.get(key)
            if mac:
                macs.append(mac)

        email = item.get("emailAddress") or item.get("userPrincipalName")

        return NormalizedDevice(
            serial=item.get("serialNumber"),
            source="intune",
            source_id=item.get("id"),
            hostname=item.get("deviceName"),
            mac_addresses=macs,
            os_name=_normalize_os(item.get("operatingSystem")),
            os_version=item.get("osVersion"),
            model=item.get("model"),
            manufacturer=item.get("manufacturer"),
            primary_user=item.get("userPrincipalName"),
            primary_user_email=email,
            last_seen=item.get("lastSyncDateTime"),
            compliance=_normalize_compliance(item.get("complianceState")),
            encrypted=bool(item.get("isEncrypted"))
            if item.get("isEncrypted") is not None
            else None,
            raw=item,
        )

    # --- data access -----------------------------------------------------
    def fetch_all(self) -> Iterable[NormalizedDevice]:
        url: Optional[str] = (
            f"{self.graph_base}/deviceManagement/managedDevices?$top=1000"
        )
        while url:
            payload = request_json(
                self.session, "GET", url, headers=self.oauth.bearer_header()
            )
            for item in (payload or {}).get("value", []) or []:
                device = self._to_device(item)
                if device is not None:
                    yield device
            url = (payload or {}).get("@odata.nextLink")

    def find_by_serial(self, serial: str) -> Optional[NormalizedDevice]:
        value = (serial or "").strip()
        if not value:
            return None
        filter_expr = quote(f"serialNumber eq '{value}'", safe="")
        url = (
            f"{self.graph_base}/deviceManagement/managedDevices"
            f"?$filter={filter_expr}"
        )
        payload = request_json(
            self.session, "GET", url, headers=self.oauth.bearer_header()
        )
        records = (payload or {}).get("value", []) or []
        if not records:
            return None
        return self._to_device(records[0])

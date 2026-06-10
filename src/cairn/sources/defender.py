"""Microsoft Defender for Endpoint (WindowsDefenderATP) source.

Authenticates with OAuth2 client credentials against Azure AD and pulls the
machine inventory from the Defender for Endpoint API (`/api/machines`), mapping
each machine payload into a NormalizedDevice. Token fetching/caching is
delegated to the shared OAuth2ClientCredentials helper.

LIMITATION — read before relying on this source for correlation:
Defender for Endpoint is an EDR signal source, not an asset/MDM system. Its
`/api/machines` payload typically does NOT expose a hardware serial number, and
it does not list MAC addresses on the machines endpoint. Because Cairn joins
records across providers by serial number, Defender on its own correlates
poorly: most records will fall back to serial "UNKNOWN".

Defender's real value in Cairn is *enrichment*. When a device has already been
discovered by an MDM (Jamf, Intune, JumpCloud, ...) that supplies a real serial,
merging the Defender record onto it adds security posture — risk score, exposure
level, health status, and onboarding status (surfaced via `extra`). Treat this
source as a signal overlay, not a system of record.

Out of scope here: Defender's primary/logged-on user is only available via a
separate `/api/machines/{id}/logonusers` call (one request per machine), so we
do not populate `primary_user`. Adding it would mean an extra round-trip per
device.
"""

from __future__ import annotations

import logging
from typing import Iterable, Optional

from ..models import NormalizedDevice
from ..http import build_session, request_json, OAuth2ClientCredentials
from .base import DeviceSource, SourceConfigError

logger = logging.getLogger(__name__)

_DEFAULT_API_BASE = "https://api.securitycenter.microsoft.com"
_DEFAULT_LOGIN_BASE = "https://login.microsoftonline.com"


def _normalize_os(raw_os: Optional[str]) -> Optional[str]:
    """Map Defender's `osPlatform` onto Cairn's canonical OS names.

    Defender uses values like "Windows10", "Windows11", "WindowsServer2019",
    "macOS", and "Linux". Collapse the Windows family to a single name.
    """
    if not raw_os:
        return None
    value = str(raw_os).strip()
    lowered = value.lower()
    if lowered.startswith("windows"):
        return "Windows"
    if lowered == "macos":
        return "macOS"
    if lowered == "linux":
        return "Linux"
    return value


class DefenderSource(DeviceSource):
    key = "defender"
    display_name = "Microsoft Defender for Endpoint"

    def validate_config(self) -> None:
        # raises SourceConfigError if any required key is missing/empty
        self.require("tenant_id", "client_id", "client_secret")

    def setup(self) -> None:
        self.tenant_id = self.config["tenant_id"]
        self.client_id = self.config["client_id"]
        self.client_secret = self.config["client_secret"]
        self.api_base = (
            self.config.get("api_base") or _DEFAULT_API_BASE
        ).rstrip("/")
        self.login_base = (
            self.config.get("login_base") or _DEFAULT_LOGIN_BASE
        ).rstrip("/")

        self.oauth = OAuth2ClientCredentials(
            token_url=f"{self.login_base}/{self.tenant_id}/oauth2/v2.0/token",
            client_id=self.client_id,
            client_secret=self.client_secret,
            scope="https://api.securitycenter.microsoft.com/.default",
        )
        self.session = build_session()

    # --- mapping ---------------------------------------------------------
    def _to_device(self, item: dict) -> Optional[NormalizedDevice]:
        """Map one Defender machine payload to a NormalizedDevice."""
        if not isinstance(item, dict):
            logger.warning("Defender: skipping non-dict machine record")
            return None

        # Defender machine objects do not reliably expose a hardware serial.
        # We only check the one field that *might* carry it; in practice it is
        # usually absent, so NormalizedDevice will normalize to "UNKNOWN" and
        # this record will not correlate by serial on its own.
        serial = item.get("serialNumber")

        # The machines endpoint usually lacks MAC addresses; include them only
        # if present (Defender sometimes returns them in newer API versions).
        macs: list[str] = []
        for key in ("macAddress", "lastIpAddressMacAddress"):
            mac = item.get(key)
            if mac:
                macs.append(mac)

        # OS version: Defender uses `version`; fall back to `osVersion`.
        os_version = item.get("version") or item.get("osVersion")

        # Security posture: Defender's healthStatus ("Active", etc.) is a
        # liveness signal, NOT a compliance verdict, so we deliberately leave
        # compliance None and stash the EDR posture in `extra` for the merge
        # step to surface.
        extra: dict = {}
        for key in (
            "riskScore",
            "exposureLevel",
            "healthStatus",
            "onboardingStatus",
        ):
            value = item.get(key)
            if value is not None:
                extra[key] = value

        return NormalizedDevice(
            serial=serial,
            source="defender",
            source_id=item.get("id"),
            hostname=item.get("computerDnsName"),
            mac_addresses=macs,
            os_name=_normalize_os(item.get("osPlatform")),
            os_version=os_version,
            os_build=item.get("osBuild"),
            # No reliable manufacturer/model on the machines payload.
            manufacturer=None,
            model=None,
            # primary_user requires a separate /machines/{id}/logonusers call;
            # out of scope (see module docstring).
            primary_user=None,
            last_seen=item.get("lastSeen"),
            compliance=None,
            extra=extra,
            raw=item,
        )

    # --- data access -----------------------------------------------------
    def fetch_all(self) -> Iterable[NormalizedDevice]:
        url: Optional[str] = f"{self.api_base}/api/machines"
        while url:
            payload = request_json(
                self.session, "GET", url, headers=self.oauth.bearer_header()
            )
            for item in (payload or {}).get("value", []) or []:
                try:
                    device = self._to_device(item)
                except Exception:  # defensive: never let one bad record abort the pull
                    logger.exception("Defender: failed to map machine record; skipping")
                    continue
                if device is not None:
                    yield device
            # OData server-driven paging: follow nextLink until it is absent.
            url = (payload or {}).get("@odata.nextLink")

    # find_by_serial: intentionally NOT overridden. Defender cannot filter
    # machines by hardware serial, so we inherit the base-class linear scan.

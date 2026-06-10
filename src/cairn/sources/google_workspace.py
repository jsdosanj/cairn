"""Google Workspace (ChromeOS) source via the Admin SDK Directory API.

Pulls ChromeOS devices from
`/admin/directory/v1/customer/{customer}/devices/chromeos`, mapping each
payload into a NormalizedDevice.

Auth is OAuth2 via a *service account* with *domain-wide delegation*: we sign a
JWT bearer assertion (RS256) with the service account's private key, set `sub`
to an admin user to impersonate (`subject`), and exchange it for an access
token. The service account must be granted the
`admin.directory.device.chromeos.readonly` scope in the Workspace admin console,
and the impersonated `subject` must be a real admin.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Iterable, Optional

from ..models import NormalizedDevice
from ..http import build_session, request_json
from .base import DeviceSource, SourceConfigError

logger = logging.getLogger(__name__)

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_DIRECTORY_BASE = "https://admin.googleapis.com/admin/directory/v1"
_SCOPE = "https://www.googleapis.com/auth/admin.directory.device.chromeos.readonly"
_JWT_GRANT = "urn:ietf:params:oauth:grant-type:jwt-bearer"
_DEFAULT_PAGE_SIZE = 200
_MAX_PAGE_SIZE = 300


class GoogleWorkspaceSource(DeviceSource):
    key = "google_workspace"
    display_name = "Google Workspace (ChromeOS)"

    def validate_config(self) -> None:
        if not self.config.get("subject"):
            raise SourceConfigError(
                f"{self.display_name} missing required config: subject "
                "(admin email to impersonate for domain-wide delegation)"
            )
        if not (
            self.config.get("service_account_info")
            or self.config.get("service_account_file")
        ):
            raise SourceConfigError(
                f"{self.display_name} requires service_account_info (dict) or "
                "service_account_file (path to the service account JSON)"
            )

    def setup(self) -> None:
        self.customer_id = self.config.get("customer_id") or "my_customer"
        self.subject = self.config["subject"]

        info = self.config.get("service_account_info")
        if info:
            if not isinstance(info, dict):
                raise SourceConfigError(
                    f"{self.display_name}: service_account_info must be a dict"
                )
            self.sa = info
        else:
            path = self.config["service_account_file"]
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    self.sa = json.load(fh)
            except (OSError, ValueError) as e:
                raise SourceConfigError(
                    f"{self.display_name}: could not read service_account_file "
                    f"{path!r}: {e}"
                ) from e

        page_size = int(self.config.get("page_size") or _DEFAULT_PAGE_SIZE)
        self.page_size = max(1, min(page_size, _MAX_PAGE_SIZE))

        self.session = build_session()
        self._token: Optional[str] = None
        self._expires_at: float = 0.0

    # --- auth ------------------------------------------------------------
    def _get_access_token(self) -> str:
        """Mint (and cache) an access token via a signed JWT bearer grant.

        Kept deliberately small and side-effect-light so tests can monkeypatch
        it without standing up a real Google token endpoint.
        """
        if self._token and time.time() < self._expires_at:
            return self._token

        try:
            import jwt  # PyJWT
        except ImportError as e:
            raise SourceConfigError(
                "Google Workspace source needs PyJWT + cryptography: "
                "pip install 'cairn-sync[google]'"
            ) from e

        now = int(time.time())
        claims = {
            "iss": self.sa["client_email"],
            "sub": self.subject,
            "scope": _SCOPE,
            "aud": _TOKEN_URL,
            "iat": now,
            "exp": now + 3600,
        }
        assertion = jwt.encode(claims, self.sa["private_key"], algorithm="RS256")

        payload = request_json(
            self.session,
            "POST",
            _TOKEN_URL,
            data={"grant_type": _JWT_GRANT, "assertion": assertion},
        )
        token = (payload or {}).get("access_token")
        if not token:
            raise SourceConfigError(
                f"{self.display_name}: token endpoint returned no access_token"
            )
        expires_in = int((payload or {}).get("expires_in", 3600))
        self._token = token
        self._expires_at = now + max(expires_in - 60, 30)
        return token

    def _bearer_header(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._get_access_token()}"}

    # --- mapping ---------------------------------------------------------
    def _to_device(self, dev: dict) -> Optional[NormalizedDevice]:
        """Map one chromeosdevices payload to a NormalizedDevice."""
        if not isinstance(dev, dict):
            logger.warning("Google Workspace: skipping non-dict chromeos record")
            return None

        macs: list[str] = []
        for key in ("macAddress", "ethernetMacAddress"):
            mac = dev.get(key)
            if mac:
                macs.append(mac)

        # `status` is enrollment state (ACTIVE/DEPROVISIONED/...), not compliance,
        # so we surface it in extra and leave the compliance field None.
        extra = {}
        status = dev.get("status")
        if status is not None:
            extra["status"] = status

        return NormalizedDevice(
            serial=dev.get("serialNumber"),
            source="google_workspace",
            source_id=dev.get("deviceId"),
            asset_type="computer",
            hostname=dev.get("annotatedAssetId") or dev.get("serialNumber"),
            mac_addresses=macs,
            os_name="ChromeOS",
            os_version=dev.get("osVersion"),
            model=dev.get("model"),
            manufacturer="Google",
            primary_user=dev.get("annotatedUser"),
            last_seen=dev.get("lastSync"),
            compliance=None,
            extra=extra,
            raw=dev,
        )

    # --- data access -----------------------------------------------------
    def fetch_all(self) -> Iterable[NormalizedDevice]:
        base = (
            f"{_DIRECTORY_BASE}/customer/{self.customer_id}/devices/chromeos"
            f"?maxResults={self.page_size}"
        )
        page_token: Optional[str] = None
        while True:
            url = base
            if page_token:
                url = f"{base}&pageToken={page_token}"
            payload = request_json(
                self.session, "GET", url, headers=self._bearer_header()
            )
            payload = payload or {}
            for dev in payload.get("chromeosdevices", []) or []:
                device = self._to_device(dev)
                if device is not None:
                    yield device
            page_token = payload.get("nextPageToken")
            if not page_token:
                break

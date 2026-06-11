"""Microsoft Intune writeback via the Microsoft Graph API.

Writes the Snipe-IT asset tag (`device.asset_tag`) into a configurable property
of the matching Intune `managedDevice` (default: `notes`). It reuses the same
OAuth2 client-credentials auth as the Intune source, locates the device by
serial number, and honors the configured conflict policy before mutating.

Caveat: Intune's `managedDevice` exposes only a limited set of writable
properties via a Graph PATCH; `notes` is the safe default target. Some tenants
or fields may require the Graph **beta** endpoint and/or the
`DeviceManagementManagedDevices.ReadWrite.All` application permission. If you
point `target_field` at a property the v1.0 endpoint won't accept, the PATCH
will fail and the result will be FAILED.
"""

from __future__ import annotations

import logging
from urllib.parse import quote

from ..models import NormalizedDevice
from ..http import build_session, request_json, OAuth2ClientCredentials
from .base import Writeback, WritebackResult, WritebackConfigError

logger = logging.getLogger(__name__)

_DEFAULT_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_DEFAULT_LOGIN_BASE = "https://login.microsoftonline.com"
_DEFAULT_TARGET_FIELD = "notes"


class IntuneWriteback(Writeback):
    key = "intune"
    display_name = "Microsoft Intune (writeback)"

    def validate_config(self) -> None:
        missing = [
            k for k in ("tenant_id", "client_id", "client_secret")
            if not self.config.get(k)
        ]
        if missing:
            raise WritebackConfigError(
                f"{self.display_name} missing required config: {', '.join(missing)}"
            )

    def setup(self) -> None:
        tenant_id = self.config["tenant_id"]
        client_id = self.config["client_id"]
        client_secret = self.config["client_secret"]
        self.graph_base = (
            self.config.get("graph_base") or _DEFAULT_GRAPH_BASE
        ).rstrip("/")
        login_base = (
            self.config.get("login_base") or _DEFAULT_LOGIN_BASE
        ).rstrip("/")
        self.target_field = self.config.get("target_field") or _DEFAULT_TARGET_FIELD

        self.oauth = OAuth2ClientCredentials(
            token_url=f"{login_base}/{tenant_id}/oauth2/v2.0/token",
            client_id=client_id,
            client_secret=client_secret,
            scope="https://graph.microsoft.com/.default",
        )
        self.session = build_session()

    def push(
        self, device: NormalizedDevice, dry_run: bool = True
    ) -> WritebackResult:
        serial = (device.serial or "").strip()
        if not serial or serial == "UNKNOWN":
            return WritebackResult(WritebackResult.SKIPPED, serial, "no serial")

        desired = device.asset_tag
        if not desired:
            return WritebackResult(
                WritebackResult.SKIPPED, serial, "no asset tag in Snipe-IT"
            )

        try:
            filter_expr = quote(f"serialNumber eq '{serial}'", safe="")
            url = (
                f"{self.graph_base}/deviceManagement/managedDevices"
                f"?$filter={filter_expr}"
            )
            payload = request_json(
                self.session, "GET", url, headers=self.oauth.bearer_header()
            )
            records = (payload or {}).get("value", []) or []
            if not records:
                return WritebackResult(
                    WritebackResult.SKIPPED, serial, "not in Intune"
                )

            item = records[0]
            device_id = item.get("id")
            if not device_id:
                return WritebackResult(
                    WritebackResult.SKIPPED, serial, "Intune device has no id"
                )
            current = item.get(self.target_field)

            if not self._resolve_policy(current, desired):
                return WritebackResult(WritebackResult.SKIPPED, serial, "no change")

            if dry_run:
                return WritebackResult(
                    WritebackResult.UPDATED,
                    serial,
                    f"would set {self.target_field}={desired} (was {current!r})",
                )

            patch_url = (
                f"{self.graph_base}/deviceManagement/managedDevices/{device_id}"
            )
            request_json(
                self.session,
                "PATCH",
                patch_url,
                headers=self.oauth.bearer_header(),
                json={self.target_field: desired},
            )
            return WritebackResult(
                WritebackResult.UPDATED,
                serial,
                f"{self.target_field} -> {desired}",
            )
        except Exception as e:  # noqa: BLE001 - report any failure as FAILED
            logger.warning("Intune writeback failed for %s: %s", serial, e)
            return WritebackResult(WritebackResult.FAILED, serial, str(e)[:200])

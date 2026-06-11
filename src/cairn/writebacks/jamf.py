"""Jamf Pro asset-tag writeback (the ``snipe2jamf`` direction).

Pushes the Snipe-IT asset tag (``device.asset_tag``) into a Jamf computer's
``general.assetTag`` field, so the system of record's tag is reflected back in
the MDM. Targets the *modern* Jamf Pro API: a serial lookup via
``/api/v1/computers-inventory`` and a ``PATCH`` to
``/api/v1/computers-inventory-detail/{id}`` (not the legacy Classic XML API).

Authentication mirrors :class:`cairn.sources.jamf.JamfSource`:

  * API client credentials (``client_id`` + ``client_secret``) -- preferred,
    uses ``POST /api/oauth/token``.
  * Username/password basic auth (``username`` + ``password``) -- uses
    ``POST /api/v1/auth/token``.

The conflict policy (``snipe_wins`` | ``only_if_empty``) is enforced by the base
class via ``self._resolve_policy``.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from ..models import NormalizedDevice
from ..http import (
    build_session,
    request_json,
    require_https,
    HttpError,
    DEFAULT_TIMEOUT,
)
from .base import Writeback, WritebackResult, WritebackConfigError

logger = logging.getLogger(__name__)

# Refresh a token this many seconds before it actually expires so a long
# writeback run never fails mid-stream on an expired bearer token.
_TOKEN_SKEW = 60


class JamfWriteback(Writeback):
    key = "jamf"
    display_name = "Jamf Pro (writeback)"

    # --- lifecycle -------------------------------------------------------
    def validate_config(self) -> None:
        url = self.config.get("url")
        if not url:
            raise WritebackConfigError(
                f"{self.display_name} missing required config: url"
            )

        has_client = bool(self.config.get("client_id")) and bool(
            self.config.get("client_secret")
        )
        has_basic = bool(self.config.get("username")) and bool(
            self.config.get("password")
        )
        if not (has_client or has_basic):
            raise WritebackConfigError(
                f"{self.display_name} requires either client_id+client_secret "
                "or username+password"
            )

        require_https(url, f"{self.display_name} url")

    def setup(self) -> None:
        self.base_url = str(self.config["url"]).rstrip("/")
        self.verify_ssl = self.config.get("verify_ssl", True)

        self.client_id = self.config.get("client_id")
        self.client_secret = self.config.get("client_secret")
        self.username = self.config.get("username")
        self.password = self.config.get("password")
        # Prefer the modern API client when both happen to be present.
        self._use_client_creds = bool(self.client_id and self.client_secret)

        self.session = build_session()
        self.session.verify = self.verify_ssl

        self._token: Optional[str] = None
        self._expires_at: float = 0.0
        # Fetch once up front so misconfiguration fails fast at setup.
        self._fetch_token()

    # --- auth ------------------------------------------------------------
    def _fetch_token(self) -> None:
        if self._use_client_creds:
            url = f"{self.base_url}/api/oauth/token"
            data = {
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }
            payload = request_json(self.session, "POST", url, data=data)
            token = (payload or {}).get("access_token")
            expires_in = int((payload or {}).get("expires_in", 0) or 0)
            if not token:
                raise HttpError(
                    f"{self.display_name} token endpoint returned no access_token"
                )
            self._token = token
            # Fall back to a conservative 5 min cache if no lifetime is given.
            lifetime = expires_in if expires_in > 0 else 300
            self._expires_at = time.time() + max(lifetime - _TOKEN_SKEW, 30)
        else:
            url = f"{self.base_url}/api/v1/auth/token"
            payload = request_json(
                self.session,
                "POST",
                url,
                auth=(self.username, self.password),
            )
            token = (payload or {}).get("token")
            if not token:
                raise HttpError(
                    f"{self.display_name} auth endpoint returned no token"
                )
            self._token = token
            # Basic-auth tokens come back with an ISO ``expires`` timestamp we
            # don't reliably parse here; cache for 5 min and refresh on demand.
            self._expires_at = time.time() + (300 - _TOKEN_SKEW)

    def _auth_headers(self) -> dict[str, str]:
        if not self._token or time.time() >= self._expires_at:
            self._fetch_token()
        return {"Authorization": f"Bearer {self._token}"}

    # --- writeback -------------------------------------------------------
    def push(
        self, device: NormalizedDevice, dry_run: bool = True
    ) -> WritebackResult:
        serial = device.serial
        try:
            if not serial or serial == "UNKNOWN":
                return WritebackResult(WritebackResult.SKIPPED, serial, "no serial")

            desired = device.asset_tag
            if not desired:
                return WritebackResult(
                    WritebackResult.SKIPPED, serial, "no asset tag in Snipe-IT"
                )

            # Find the Jamf computer by serial (modern inventory API).
            params = [
                ("section", "GENERAL"),
                ("page", "0"),
                ("page-size", "1"),
                ("filter", f'hardware.serialNumber=="{serial}"'),
            ]
            payload = request_json(
                self.session,
                "GET",
                f"{self.base_url}/api/v1/computers-inventory",
                params=params,
                headers=self._auth_headers(),
                timeout=DEFAULT_TIMEOUT,
            ) or {}
            results = payload.get("results") or []
            if not results:
                return WritebackResult(
                    WritebackResult.SKIPPED, serial, "not in Jamf"
                )

            result = results[0] or {}
            computer_id = result.get("id")
            if computer_id is None:
                return WritebackResult(
                    WritebackResult.SKIPPED, serial, "not in Jamf"
                )
            current = (result.get("general") or {}).get("assetTag")

            if not self._resolve_policy(current, desired):
                return WritebackResult(WritebackResult.SKIPPED, serial, "no change")

            if dry_run:
                return WritebackResult(
                    WritebackResult.UPDATED,
                    serial,
                    f"would set assetTag={desired} (was {current!r})",
                )

            request_json(
                self.session,
                "PATCH",
                f"{self.base_url}/api/v1/computers-inventory-detail/{computer_id}",
                json={"general": {"assetTag": desired}},
                headers=self._auth_headers(),
                timeout=DEFAULT_TIMEOUT,
            )
            return WritebackResult(
                WritebackResult.UPDATED, serial, f"assetTag -> {desired}"
            )
        except Exception as e:  # never let one device kill the run
            logger.warning("%s: push failed for %s: %s", self.display_name, serial, e)
            return WritebackResult(WritebackResult.FAILED, serial, str(e)[:200])

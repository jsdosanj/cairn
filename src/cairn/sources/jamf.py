"""Jamf Pro device source.

Targets the *modern* Jamf Pro API (the JSON ``/api/v1/...`` endpoints, also
known as the "Jamf Pro API" or Uapi), not the legacy XML Classic API. Inventory
is read from ``/api/v1/computers-inventory`` with explicit ``section`` selectors
so we only pull the fields Cairn normalizes.

Two authentication modes are supported:

  * API client credentials (``client_id`` + ``client_secret``) -- preferred,
    uses ``POST /api/oauth/token``.
  * Username/password basic auth (``username`` + ``password``) -- uses
    ``POST /api/v1/auth/token``.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Iterable, Optional

from ..models import NormalizedDevice
from ..http import (
    build_session,
    request_json,
    require_https,
    resolve_verify,
    HttpError,
    DEFAULT_TIMEOUT,
)
from .base import DeviceSource, SourceConfigError

logger = logging.getLogger(__name__)

# Inventory sections we ask Jamf to return. Keeping this list tight makes the
# response smaller and faster than the (large) default full-record payload.
_SECTIONS = (
    "GENERAL",
    "HARDWARE",
    "OPERATING_SYSTEM",
    "USER_AND_LOCATION",
)

# Refresh a token this many seconds before it actually expires so a long fleet
# pull never fails mid-stream on an expired bearer token.
_TOKEN_SKEW = 60

# A serial gets interpolated into an RSQL filter; restrict it to characters that
# can't break out of the quoted value so a crafted serial can't tamper with the
# query.
_SERIAL_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class JamfSource(DeviceSource):
    key = "jamf"
    display_name = "Jamf Pro"

    # --- lifecycle -------------------------------------------------------
    def validate_config(self) -> None:
        url = self.config.get("url")
        if not url:
            raise SourceConfigError(f"{self.display_name} missing required config: url")

        has_client = bool(self.config.get("client_id")) and bool(
            self.config.get("client_secret")
        )
        has_basic = bool(self.config.get("username")) and bool(
            self.config.get("password")
        )
        if not (has_client or has_basic):
            raise SourceConfigError(
                f"{self.display_name} requires either client_id+client_secret "
                "or username+password"
            )

        require_https(url, f"{self.display_name} url")

    def setup(self) -> None:
        self.base_url = str(self.config["url"]).rstrip("/")
        self.page_size = int(self.config.get("page_size", 100) or 100)

        self.client_id = self.config.get("client_id")
        self.client_secret = self.config.get("client_secret")
        self.username = self.config.get("username")
        self.password = self.config.get("password")
        # Prefer the modern API client when both happen to be present.
        self._use_client_creds = bool(self.client_id and self.client_secret)

        self.session = build_session()
        self.session.verify = resolve_verify(self.config, self.base_url)

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
            # client-credentials tokens report lifetime in seconds.
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

    # --- helpers ---------------------------------------------------------
    def _inventory_url(self) -> str:
        return f"{self.base_url}/api/v1/computers-inventory"

    def _section_params(self) -> list[tuple[str, str]]:
        return [("section", s) for s in _SECTIONS]

    def _get(self, params: list[tuple[str, str]]) -> dict[str, Any]:
        payload = request_json(
            self.session,
            "GET",
            self._inventory_url(),
            params=params,
            headers=self._auth_headers(),
            timeout=DEFAULT_TIMEOUT,
        )
        return payload or {}

    def _to_device(self, result: dict[str, Any]) -> Optional[NormalizedDevice]:
        """Map one inventory record to a NormalizedDevice; None if unusable."""
        try:
            general = result.get("general") or {}
            hardware = result.get("hardware") or {}
            os_info = result.get("operatingSystem") or {}
            user_loc = result.get("userAndLocation") or {}

            serial = hardware.get("serialNumber")

            macs: list[str] = []
            for key in ("macAddress", "altMacAddress"):
                mac = hardware.get(key)
                if mac:
                    macs.append(mac)

            os_name = os_info.get("name")
            normalized_os = os_name
            if os_name and "mac" in str(os_name).lower():
                normalized_os = "macOS"

            return NormalizedDevice(
                serial=serial,
                source="jamf",
                source_id=str(result.get("id")) if result.get("id") is not None else None,
                hostname=general.get("name"),
                mac_addresses=macs,
                os_name=normalized_os,
                os_version=os_info.get("version"),
                os_build=os_info.get("build"),
                model=hardware.get("model"),
                manufacturer="Apple",
                primary_user=user_loc.get("username") or user_loc.get("realname"),
                primary_user_email=user_loc.get("email"),
                last_seen=general.get("lastContactTime"),
                raw=result,
            )
        except Exception as e:  # never let one bad record kill the pull
            logger.warning(
                "%s: skipping malformed inventory record id=%r: %s",
                self.display_name,
                result.get("id") if isinstance(result, dict) else "?",
                e,
            )
            return None

    # --- data access -----------------------------------------------------
    def fetch_all(self) -> Iterable[NormalizedDevice]:
        page = 0
        seen = 0
        total: Optional[int] = None

        while True:
            params = self._section_params() + [
                ("page", str(page)),
                ("page-size", str(self.page_size)),
            ]
            payload = self._get(params)

            if total is None:
                try:
                    total = int(payload.get("totalCount", 0) or 0)
                except (TypeError, ValueError):
                    total = None

            results = payload.get("results") or []
            if not results:
                break

            for result in results:
                if not isinstance(result, dict):
                    logger.warning(
                        "%s: skipping non-dict inventory result", self.display_name
                    )
                    continue
                seen += 1
                device = self._to_device(result)
                if device is not None:
                    yield device

            # Stop once we've collected everything the server promised.
            if total is not None and seen >= total:
                break
            # Defensive: a short page means we've reached the end.
            if len(results) < self.page_size:
                break

            page += 1

    def find_by_serial(self, serial: str) -> Optional[NormalizedDevice]:
        target = (serial or "").strip()
        if not target:
            return None
        if not _SERIAL_RE.match(target):
            logger.warning(
                "%s: refusing unsafe serial in filter: %r", self.display_name, target
            )
            return None

        params = self._section_params() + [
            ("page", "0"),
            ("page-size", "1"),
            ("filter", f'hardware.serialNumber=="{target}"'),
        ]
        payload = self._get(params)
        results = payload.get("results") or []
        for result in results:
            if isinstance(result, dict):
                device = self._to_device(result)
                if device is not None:
                    return device
        return None

"""GLPI as a CMDB reader: pull Computer assets into NormalizedDevice.

GLPI is the dominant open-source ITAM/ITSM system outside Snipe-IT, so reading
it lets Cairn's drift/reconciliation work against a GLPI system of record, not
just Snipe-IT. The engine already consumes generic NormalizedDevice lists, so
this is just a reader per backend.

GLPI's REST API uses session-token auth: an ``app_token`` (the API client) plus
a ``user_token`` are exchanged for a short-lived ``Session-Token`` via
``/initSession``; every subsequent call carries both the App-Token and the
Session-Token. Computers are paged with ``Content-Range``-style ``range``
params. We read the ``Computer`` itemtype and map GLPI's id-coded fields
(serial, name) into the normalized shape; the asset's GLPI id lands in
``asset_tag`` so drift can point an admin at the right record.
"""

from __future__ import annotations

import logging
from typing import Iterable, Optional

from ..http import build_session, request_json, require_https, resolve_verify
from ..models import NormalizedDevice
from .base import DeviceSource, SourceConfigError

logger = logging.getLogger(__name__)

_DEFAULT_PAGE_SIZE = 200


class GlpiSource(DeviceSource):
    key = "glpi"
    display_name = "GLPI (read)"

    def validate_config(self) -> None:
        self.require("url", "app_token", "user_token")
        require_https(self.config["url"], f"{self.display_name} url")

    def setup(self) -> None:
        # url is the API base, e.g. https://glpi.example.com/apirest.php
        self.base_url = str(self.config["url"]).rstrip("/")
        self.app_token = self.config["app_token"]
        self.user_token = self.config["user_token"]
        self.page_size = int(self.config.get("page_size", _DEFAULT_PAGE_SIZE) or _DEFAULT_PAGE_SIZE)
        self.session = build_session(headers={"App-Token": self.app_token})
        self.session.verify = resolve_verify(self.config, self.base_url)
        self._session_token: Optional[str] = None

    # --- auth ------------------------------------------------------------
    def _init_session(self) -> str:
        """Exchange the user token for a short-lived session token."""
        if self._session_token:
            return self._session_token
        payload = request_json(
            self.session,
            "GET",
            f"{self.base_url}/initSession",
            headers={"Authorization": f"user_token {self.user_token}"},
        ) or {}
        token = payload.get("session_token")
        if not token:
            raise SourceConfigError(
                f"{self.display_name}: initSession returned no session_token"
            )
        self._session_token = token
        self.session.headers["Session-Token"] = token
        return token

    # --- data access -----------------------------------------------------
    def fetch_all(self) -> Iterable[NormalizedDevice]:
        self._init_session()
        offset = 0
        while True:
            url = f"{self.base_url}/Computer"
            params = {
                "range": f"{offset}-{offset + self.page_size - 1}",
                "expand_dropdowns": "true",  # resolve id-coded fields to names
            }
            payload = request_json(self.session, "GET", url, params=params)
            rows = payload if isinstance(payload, list) else []
            for row in rows:
                device = self._to_device(row)
                if device is not None:
                    yield device
            if len(rows) < self.page_size:
                break
            offset += self.page_size

    def _to_device(self, row: dict) -> Optional[NormalizedDevice]:
        if not isinstance(row, dict):
            return None
        try:
            gid = row.get("id")
            # expand_dropdowns turns these foreign keys into display names.
            manufacturer = row.get("manufacturers_id") or None
            model = row.get("computermodels_id") or row.get("computertypes_id") or None
            return NormalizedDevice(
                serial=row.get("serial") or row.get("otherserial"),
                source="glpi",
                source_id=str(gid) if gid is not None else None,
                asset_tag=str(gid) if gid is not None else None,
                hostname=row.get("name"),
                model=model if isinstance(model, str) else None,
                manufacturer=manufacturer if isinstance(manufacturer, str) else None,
                os_name=_normalize_os(row.get("operatingsystems_id")),
                last_seen=row.get("last_inventory_update") or row.get("date_mod"),
                raw=row,
            )
        except Exception as e:  # noqa: BLE001 - one bad row shouldn't kill the pull
            logger.warning("%s: skipping malformed asset %r: %s",
                           self.display_name, row.get("id"), e)
            return None


def _normalize_os(value) -> Optional[str]:
    """Map a GLPI OS display string to Cairn's coarse os_name buckets."""
    if not isinstance(value, str) or not value.strip():
        return None
    low = value.lower()
    if "windows" in low:
        return "Windows"
    if "mac" in low or "os x" in low:
        return "macOS"
    if any(k in low for k in ("linux", "ubuntu", "debian", "centos", "rhel", "fedora")):
        return "Linux"
    return value

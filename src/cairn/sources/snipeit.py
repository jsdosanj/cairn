"""Snipe-IT as a *source*: read assets out of Snipe-IT into NormalizedDevice.

Used by the writeback flow (Snipe-IT is the system of record we read asset tags
from), and usable as a normal source if you want to pull one Snipe-IT instance
into another sink. Asset tag lands in `NormalizedDevice.asset_tag`.
"""

from __future__ import annotations

import logging
from typing import Iterable, Optional

from ..http import build_session, request_json, require_https
from ..models import NormalizedDevice
from .base import DeviceSource, SourceConfigError

logger = logging.getLogger(__name__)


class SnipeITSource(DeviceSource):
    key = "snipeit"
    display_name = "Snipe-IT (read)"

    def validate_config(self) -> None:
        self.require("url", "token")
        require_https(self.config["url"], f"{self.display_name} url")

    def setup(self) -> None:
        self.base_url = str(self.config["url"]).rstrip("/")
        self.page_size = int(self.config.get("page_size", 500) or 500)
        self.session = build_session(headers={
            "Authorization": f"Bearer {self.config['token']}",
            "Accept": "application/json",
        })

    def _to_device(self, row: dict) -> Optional[NormalizedDevice]:
        if not isinstance(row, dict):
            return None
        try:
            # Snipe-IT nests some values as {"datetime":..} / {"id":, "name":}.
            def _val(v):
                if isinstance(v, dict):
                    return v.get("name") or v.get("datetime") or v.get("value")
                return v

            return NormalizedDevice(
                serial=row.get("serial"),
                source="snipeit",
                source_id=str(row.get("id")) if row.get("id") is not None else None,
                asset_tag=row.get("asset_tag"),
                hostname=_val(row.get("name")),
                model=_val(row.get("model")),
                manufacturer=_val(row.get("manufacturer")),
                raw=row,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("%s: skipping malformed asset %r: %s",
                           self.display_name, row.get("id"), e)
            return None

    def fetch_all(self) -> Iterable[NormalizedDevice]:
        offset = 0
        while True:
            url = f"{self.base_url}/hardware?limit={self.page_size}&offset={offset}"
            payload = request_json(self.session, "GET", url)
            if not isinstance(payload, dict):
                break
            rows = payload.get("rows") or []
            for row in rows:
                device = self._to_device(row)
                if device is not None:
                    yield device
            total = payload.get("total")
            offset += len(rows)
            if not rows or (isinstance(total, int) and offset >= total):
                break
            if len(rows) < self.page_size:
                break

    def find_by_serial(self, serial: str) -> Optional[NormalizedDevice]:
        from urllib.parse import quote
        safe = quote(str(serial), safe="")
        payload = request_json(self.session, "GET", f"{self.base_url}/hardware?search={safe}")
        for row in (payload or {}).get("rows", []) or []:
            if str(row.get("serial", "")).strip().upper() == str(serial).strip().upper():
                return self._to_device(row)
        return None

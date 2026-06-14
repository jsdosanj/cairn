"""NetBox as a CMDB reader: pull DCIM devices into NormalizedDevice.

NetBox is the de-facto open-source source-of-truth for network/datacenter
inventory, so supporting it lets Cairn reconcile drift against a NetBox CMDB the
same way it does against Snipe-IT. NetBox's REST API is clean and well-paged:
``/api/dcim/devices/`` returns ``{count, next, results: [...]}`` with cursor-style
``next`` URLs, and auth is a simple ``Authorization: Token <key>`` header.

NetBox nests related objects (``device_type.manufacturer.name``,
``primary_ip``...), so the mapping flattens those into the normalized shape. The
NetBox device name lands in ``asset_tag`` (NetBox's human-facing identity) and
``hostname``; serial is the join key when present.
"""

from __future__ import annotations

import logging
from typing import Iterable, Optional

from ..http import build_session, request_json, require_https, resolve_verify
from ..models import NormalizedDevice
from .base import DeviceSource, SourceConfigError

logger = logging.getLogger(__name__)

_DEFAULT_PAGE_SIZE = 200


class NetBoxSource(DeviceSource):
    key = "netbox"
    display_name = "NetBox (read)"

    def validate_config(self) -> None:
        self.require("url", "token")
        require_https(self.config["url"], f"{self.display_name} url")

    def setup(self) -> None:
        self.base_url = str(self.config["url"]).rstrip("/")
        self.page_size = int(self.config.get("page_size", _DEFAULT_PAGE_SIZE) or _DEFAULT_PAGE_SIZE)
        self.session = build_session(headers={
            "Authorization": f"Token {self.config['token']}",
        })
        self.session.verify = resolve_verify(self.config, self.base_url)

    # --- data access -----------------------------------------------------
    def fetch_all(self) -> Iterable[NormalizedDevice]:
        url: Optional[str] = (
            f"{self.base_url}/api/dcim/devices/?limit={self.page_size}"
        )
        while url:
            payload = request_json(self.session, "GET", url)
            if not isinstance(payload, dict):
                break
            for row in payload.get("results") or []:
                device = self._to_device(row)
                if device is not None:
                    yield device
            # NetBox returns an absolute `next` URL (or null on the last page).
            url = payload.get("next")

    def _to_device(self, row: dict) -> Optional[NormalizedDevice]:
        if not isinstance(row, dict):
            return None
        try:
            device_type = row.get("device_type") or {}
            manufacturer = (device_type.get("manufacturer") or {}).get("name")
            nid = row.get("id")
            return NormalizedDevice(
                serial=row.get("serial"),
                source="netbox",
                source_id=str(nid) if nid is not None else None,
                asset_type="network",
                asset_tag=row.get("name") or row.get("asset_tag"),
                hostname=row.get("name"),
                model=device_type.get("model"),
                manufacturer=manufacturer,
                last_seen=row.get("last_updated"),
                extra={
                    "ip": _ip_only(row.get("primary_ip")),
                    "status": _label(row.get("status")),
                    "site": (row.get("site") or {}).get("name"),
                },
                raw=row,
            )
        except Exception as e:  # noqa: BLE001 - one bad row shouldn't kill the pull
            logger.warning("%s: skipping malformed device %r: %s",
                           self.display_name, row.get("id"), e)
            return None


def _label(value) -> Optional[str]:
    """NetBox choice fields serialize as {"value":, "label":}; take the label."""
    if isinstance(value, dict):
        return value.get("label") or value.get("value")
    return value if isinstance(value, str) else None


def _ip_only(primary_ip) -> Optional[str]:
    """primary_ip is {"address": "10.0.0.5/24", ...}; strip the prefix length."""
    if isinstance(primary_ip, dict):
        addr = primary_ip.get("address")
        if isinstance(addr, str):
            return addr.split("/")[0]
    return None

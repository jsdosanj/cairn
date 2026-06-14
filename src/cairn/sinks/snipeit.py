"""Snipe-IT asset sink.

Maps a NormalizedDevice onto a Snipe-IT hardware asset, creating or updating by
serial number. Custom-field mapping is config-driven so a NormalizedDevice
attribute (or an `extra.<source>.<key>` path) lands in whatever Snipe-IT custom
field the user named, without code changes.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional
from urllib.parse import quote

from ..http import build_session, request_json, require_https, HttpError
from ..models import NormalizedDevice, mask_serial
from .base import AssetSink, SinkConfigError, SyncResult

logger = logging.getLogger(__name__)

# Default custom-field-label -> NormalizedDevice path. Overridable via config.
DEFAULT_FIELD_MAP = {
    "Operating System": "os_name",
    "OS Version": "os_version",
    "OS Build": "os_build",
    "MAC Address": "mac_addresses",
    "Logged In Users": "logged_in_users",
    "Last Seen": "last_seen",
    "Source": "source",
}


def _sanitize(value: Any, max_len: int = 255) -> str:
    if not isinstance(value, str):
        value = "" if value is None else str(value)
    cleaned = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", value)
    return cleaned[:max_len]


def _extract_asset_tag_from_name(name: str) -> Optional[str]:
    if not isinstance(name, str) or not name:
        return None
    match = re.search(r"\d{4,}", name)
    return match.group(0) if match else None


def generate_asset_tag(serial: str, hostname: str) -> str:
    tag = _extract_asset_tag_from_name(hostname or "")
    if tag:
        return tag
    serial = str(serial or "")
    normalized = serial[-6:].zfill(6) if serial and serial != "UNKNOWN" else "000000"
    return f"CASID-{normalized}"


def _resolve_path(device: NormalizedDevice, path: str) -> Any:
    """Resolve a dotted path like 'os_name' or 'extra.crowdstrike.risk' on a device."""
    parts = path.split(".")
    cur: Any = getattr(device, parts[0], None)
    for p in parts[1:]:
        if isinstance(cur, dict):
            cur = cur.get(p)
        else:
            return None
    if isinstance(cur, list):
        return ", ".join(str(x) for x in cur)
    return cur


class SnipeITSink(AssetSink):
    key = "snipeit"
    display_name = "Snipe-IT"

    def validate_config(self) -> None:
        self.require("url", "token")
        require_https(self.config["url"], "Snipe-IT url")

    def setup(self) -> None:
        self.base_url = self.config["url"].rstrip("/")
        self.session = build_session(headers={
            "Authorization": f"Bearer {self.config['token']}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        })
        defaults = self.config.get("_defaults", {})
        self.status_id = int(self.config.get("status_id", defaults.get("status_id", 2)))
        self.company_id = self.config.get("company_id", defaults.get("company_id"))
        self.site_id = self.config.get("site_id", defaults.get("site_id"))
        self.field_map = self.config.get("field_map", DEFAULT_FIELD_MAP)
        self.default_model_id = self.config.get("default_model_id", 1)

    # --- API helpers -----------------------------------------------------
    def find_asset_by_serial(self, serial: str) -> Optional[dict]:
        safe = quote(str(serial), safe="")
        data = request_json(self.session, "GET", f"{self.base_url}/hardware?search={safe}")
        if not isinstance(data, dict):
            return None
        for row in data.get("rows", []) or []:
            # Snipe-IT search is fuzzy; confirm exact serial match.
            if str(row.get("serial", "")).strip().upper() == str(serial).strip().upper():
                return row
        rows = data.get("rows", []) or []
        return rows[0] if rows else None

    def find_or_create_model(self, name: str) -> int:
        safe = quote(str(name or "Unknown"), safe="")
        data = request_json(self.session, "GET", f"{self.base_url}/models?search={safe}")
        if isinstance(data, dict):
            for row in data.get("rows", []) or []:
                if row.get("id"):
                    return row["id"]
        return self.default_model_id

    def _custom_fields(self, device: NormalizedDevice) -> dict[str, str]:
        out: dict[str, str] = {}
        for label, path in self.field_map.items():
            out[label] = _sanitize(_resolve_path(device, path))
        return out

    def upsert(self, device: NormalizedDevice, dry_run: bool = False) -> SyncResult:
        serial = device.serial
        hostname = _sanitize(device.hostname or serial)
        try:
            existing = self.find_asset_by_serial(serial)
            custom_fields = self._custom_fields(device)
            if existing:
                if "id" not in existing or "asset_tag" not in existing:
                    raise SinkConfigError("Snipe-IT asset missing id/asset_tag")
                payload = {
                    "name": hostname,
                    "asset_tag": existing["asset_tag"],
                    "custom_fields": custom_fields,
                }
                if dry_run:
                    return SyncResult(SyncResult.UPDATED, serial, existing["asset_tag"], "dry-run")
                request_json(self.session, "PUT",
                             f"{self.base_url}/hardware/{int(existing['id'])}", json=payload)
                return SyncResult(SyncResult.UPDATED, serial, existing["asset_tag"])
            # Create
            asset_tag = generate_asset_tag(serial, hostname)
            model_id = self.find_or_create_model(device.model or device.os_name or "Unknown")
            payload = {
                "name": hostname,
                "serial": serial,
                "asset_tag": asset_tag,
                "model_id": model_id,
                "status_id": self.status_id,
                "custom_fields": custom_fields,
            }
            if self.company_id:
                payload["company_id"] = self.company_id
            if self.site_id:
                payload["site_id"] = self.site_id
            if dry_run:
                return SyncResult(SyncResult.CREATED, serial, asset_tag, "dry-run")
            resp = request_json(self.session, "POST", f"{self.base_url}/hardware", json=payload)
            # Snipe-IT returns {"status":"error",...} with HTTP 200 on validation errors.
            if isinstance(resp, dict) and resp.get("status") == "error":
                raise HttpError(f"Snipe-IT rejected create: {resp.get('messages')}")
            return SyncResult(SyncResult.CREATED, serial, asset_tag)
        except Exception as e:  # noqa: BLE001 - surface as a failed result, keep the run going
            logger.error("Snipe-IT upsert failed for %s: %s", mask_serial(serial), e)
            return SyncResult(SyncResult.FAILED, serial, "", str(e))

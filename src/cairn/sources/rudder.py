"""Rudder managed-nodes inventory source.

Rudder is an open-source configuration-management / continuous-audit tool. This
source reads its managed-nodes inventory via the Rudder REST API, authenticating
with an `X-API-Token` header. The `/nodes` endpoint returns the full inventory in
a single response, so no pagination is needed.

Note: Rudder nodes may not expose a hardware serial number (many are VMs or
distros that report none). Such records still map to a NormalizedDevice; the
model substitutes "UNKNOWN" for the serial, so these nodes end up keyed by MAC
address / hostname rather than serial for correlation.
"""

from __future__ import annotations

import logging
from typing import Iterable, Optional

from ..http import build_session, request_json, require_https
from ..models import NormalizedDevice
from .base import DeviceSource, SourceConfigError

logger = logging.getLogger(__name__)

_DEFAULT_API_VERSION = "latest"
_NODE_INCLUDE = "minimal,os,networkInterfaces,processors,storage"


class RudderSource(DeviceSource):
    key = "rudder"
    display_name = "Rudder"

    def validate_config(self) -> None:
        if not self.config.get("url"):
            raise SourceConfigError(f"{self.display_name} missing required config: url")
        if not self.config.get("api_token"):
            raise SourceConfigError(
                f"{self.display_name} missing required config: api_token"
            )
        require_https(self.config["url"], f"{self.display_name} url")

    def setup(self) -> None:
        self.base = self.config["url"].rstrip("/")
        self.api_version = self.config.get("api_version") or _DEFAULT_API_VERSION
        self.session = build_session(
            headers={
                "X-API-Token": self.config["api_token"],
                "Accept": "application/json",
            }
        )
        self.session.verify = bool(self.config.get("verify_ssl", True))

    # --- data access -----------------------------------------------------
    def fetch_all(self) -> Iterable[NormalizedDevice]:
        url = f"{self.base}/rudder/api/{self.api_version}/nodes"
        params = {"include": _NODE_INCLUDE}
        payload = request_json(self.session, "GET", url, params=params)
        nodes = ((payload or {}).get("data") or {}).get("nodes") or []
        for node in nodes:
            device = self._map_node(node)
            if device is not None:
                yield device

    # --- mapping ---------------------------------------------------------
    def _map_node(self, node: dict) -> Optional[NormalizedDevice]:
        if not isinstance(node, dict):
            logger.warning("%s skipping non-dict node record", self.display_name)
            return None
        try:
            os_info = node.get("os") if isinstance(node.get("os"), dict) else {}
            os_name = self._normalize_os(os_info.get("name"))
            os_version = os_info.get("version")

            machine = node.get("machine") if isinstance(node.get("machine"), dict) else {}
            serial = machine.get("serialNumber") or node.get("serialNumber")

            return NormalizedDevice(
                serial=serial,
                source="rudder",
                source_id=node.get("id"),
                asset_type="computer",
                hostname=node.get("hostname"),
                mac_addresses=self._extract_macs(node),
                os_name=os_name,
                os_version=os_version,
                primary_user=None,
                last_seen=node.get("lastInventoryDate") or node.get("lastRunDate"),
                extra={
                    "policyMode": node.get("policyMode"),
                    "state": node.get("state"),
                    "ipAddresses": node.get("ipAddresses"),
                },
                raw=node,
            )
        except Exception as e:  # defensive: never let one bad record kill the pull
            logger.warning(
                "%s skipping unmappable node %r: %s",
                self.display_name,
                node.get("id"),
                e,
            )
            return None

    @staticmethod
    def _normalize_os(os_name: Optional[str]) -> Optional[str]:
        if not os_name:
            return None
        lowered = str(os_name).strip().lower()
        if "windows" in lowered:
            return "Windows"
        if "mac" in lowered or "darwin" in lowered:
            return "macOS"
        # Most Rudder nodes are Linux (ubuntu, debian, centos, rhel, etc.).
        return "Linux"

    @staticmethod
    def _extract_macs(node: dict) -> list[str]:
        macs: list[str] = []
        for iface in node.get("networkInterfaces") or []:
            if not isinstance(iface, dict):
                continue
            addr = iface.get("macAddress")
            if addr:
                macs.append(addr)
        return macs

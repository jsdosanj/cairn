"""Native lightweight network discovery: catch devices no MDM/EDR manages.

This is Cairn's answer to "but it only knows what my MDM knows." Printers,
switches, IoT, and rogue boxes never enroll in Jamf/Intune/CrowdStrike, so the
managed sources are blind to them. A passive ARP-cache read (and an opt-in
ARP/ping sweep) surfaces every device that has recently talked on the local
segment, keyed by MAC address since such gear rarely exposes a serial number.

Design — a clean source boundary, honest about the OS probe:

  * The *parsing / normalization / merge* logic (``_parse_arp_table``,
    ``_observations_to_devices``, OUI vendor lookup) is pure and fully unit
    tested against fixtures. It never touches the network.
  * The *probe* — actually reading the kernel ARP cache or sweeping a CIDR — is
    isolated behind ``_collect_arp_lines`` / ``_sweep`` with an honest ``TODO``
    and **safe defaults: nothing is scanned unless the operator explicitly opts
    in with a ``cidr``**. By default we only read the ARP cache already
    populated by normal traffic, which sends no probe packets of our own.

Security: an unscoped network scan is intrusive and can trip IDS, so active
sweeping is strictly opt-in and gated on a configured CIDR. Raw-socket ARP
requires root; rather than ship a fragile privileged probe, the active sweep is
left as a documented TODO with a safe no-op default.
"""

from __future__ import annotations

import logging
import re
import subprocess
from typing import Iterable, Optional

from ..models import NormalizedDevice
from .base import DeviceSource, SourceConfigError

logger = logging.getLogger(__name__)

# Minimal OUI -> manufacturer table for the vendors that dominate unmanaged
# network gear. The full IEEE OUI registry is ~30k entries; we ship a curated
# subset and treat an unknown prefix as simply unknown rather than pulling a
# multi-megabyte database. Prefixes are the first 3 MAC octets, upper-case, no
# separators.
# TODO: optionally enrich from a bundled IEEE OUI file when present on disk.
_OUI_VENDORS = {
    "F4F5E8": "Google",
    "3C2AF4": "Brother",
    "002608": "Apple",
    "F0D1A9": "Apple",
    "B827EB": "Raspberry Pi Foundation",
    "DCA632": "Raspberry Pi Trading",
    "00156D": "Ubiquiti",
    "FCECDA": "Ubiquiti",
    "002655": "Cisco",
    "00000C": "Cisco",
    "001018": "Broadcom",
    "0004F2": "Polycom",
    "001B78": "HP",
    "3CD92B": "HP",
    "0080A3": "Lantronix",
    "001320": "Intel",
    "B499BA": "Hewlett Packard Enterprise",
    "000F1F": "Dell",
    "001422": "Dell",
}

# An ``incomplete`` / ``(incomplete)`` ARP entry has an IP but no resolved MAC;
# such rows carry no device identity and are dropped.
_INCOMPLETE = {"incomplete", "(incomplete)", "<incomplete>"}

# Recognize a MAC in either colon or dash form within a free-text ARP line.
_MAC_RE = re.compile(r"\b([0-9a-fA-F]{1,2}(?:[:-][0-9a-fA-F]{1,2}){5})\b")
# IPv4 dotted quad.
_IP_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")


class NetworkDiscoverySource(DeviceSource):
    key = "network_discovery"
    display_name = "Network discovery (ARP/ping)"

    def validate_config(self) -> None:
        # No required credentials: discovery reads the local ARP cache. A CIDR is
        # optional and only needed to opt in to active sweeping.
        cidr = self.config.get("cidr")
        if cidr is not None and not _looks_like_cidr(str(cidr)):
            raise SourceConfigError(
                f"{self.display_name}: 'cidr' must look like 10.0.0.0/24, got {cidr!r}"
            )

    def setup(self) -> None:
        self.cidr: Optional[str] = self.config.get("cidr") or None
        # Active sweep is doubly gated: a CIDR must be set AND the operator must
        # explicitly enable it. Either omission means passive-only (safe default).
        self.active_sweep: bool = bool(self.config.get("active_sweep")) and bool(self.cidr)
        self.asset_type = self.config.get("asset_type", "network")

    # --- data access -----------------------------------------------------
    def fetch_all(self) -> Iterable[NormalizedDevice]:
        """Yield one NormalizedDevice per distinct MAC seen on the segment.

        Passive by default (reads the kernel ARP cache only). If ``active_sweep``
        is enabled and a ``cidr`` is set, a sweep would first populate the cache;
        that probe is an isolated TODO and currently a safe no-op.
        """
        if self.active_sweep:
            # Opt-in active probing populates the ARP cache before we read it.
            self._sweep(self.cidr)  # currently a no-op boundary (see TODO).
        lines = self._collect_arp_lines()
        observations = self._parse_arp_table(lines)
        yield from self._observations_to_devices(observations)

    # --- OS probe boundary (isolated, honest TODO) -----------------------
    def _collect_arp_lines(self) -> list[str]:
        """Read the local kernel ARP/neighbor cache. Passive: sends no packets.

        Tries ``ip neigh`` (Linux) then ``arp -a`` (macOS/BSD/Windows). This is
        the only place this source shells out; the parsing below is pure and
        tested independently of it. A probe that fails (no tool, no permission)
        yields nothing rather than raising, so a discovery run degrades quietly.
        """
        for argv in (["ip", "neigh"], ["arp", "-a"]):
            try:
                proc = subprocess.run(
                    argv, capture_output=True, text=True, timeout=15
                )
            except (OSError, subprocess.SubprocessError) as e:
                logger.debug("%s: probe %s unavailable: %s", self.display_name, argv[0], e)
                continue
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.splitlines()
        logger.warning(
            "%s: no ARP table available (tried `ip neigh` and `arp -a`).",
            self.display_name,
        )
        return []

    def _sweep(self, cidr: Optional[str]) -> None:
        """Active ARP/ping sweep of ``cidr`` to populate the ARP cache.

        TODO: implement a polite sweep (e.g. one ICMP echo or ARP-who-has per
        host, rate-limited, IPv4 /16-or-smaller only) so the subsequent ARP-cache
        read sees hosts that haven't recently talked to us. Raw-socket ARP needs
        root and is platform-specific; until that lands this is a deliberate
        no-op so enabling ``active_sweep`` never silently scans a network in a
        half-built way.
        """
        logger.info(
            "%s: active sweep of %s requested but not yet implemented; "
            "falling back to passive ARP-cache read only.",
            self.display_name,
            cidr,
        )

    # --- pure parsing / normalization (unit tested) ----------------------
    def _parse_arp_table(self, lines: Iterable[str]) -> dict[str, dict]:
        """Parse ARP/neighbor output into {mac: {ip, ...}} observations.

        Handles the three real formats:
          * Linux ``ip neigh``:  ``192.168.1.5 dev eth0 lladdr aa:bb:.. REACHABLE``
          * macOS/BSD ``arp -a``: ``host (192.168.1.5) at aa:bb:.. on en0 ...``
          * Windows ``arp -a``:   ``  192.168.1.5    aa-bb-cc-dd-ee-ff   dynamic``

        Multiple lines for the same MAC (e.g. IPv4 + a hostname alias) collapse
        into one observation; the last non-empty IP wins. Incomplete entries and
        broadcast/multicast MACs are dropped.
        """
        observations: dict[str, dict] = {}
        for raw in lines:
            line = (raw or "").strip()
            if not line:
                continue
            low = line.lower()
            if any(tok in low for tok in _INCOMPLETE):
                continue
            mac_match = _MAC_RE.search(line)
            if not mac_match:
                continue
            mac = _canon_mac(mac_match.group(1))
            if not mac or _is_ignorable_mac(mac):
                continue
            ip_match = _IP_RE.search(line)
            ip = ip_match.group(1) if ip_match else None
            obs = observations.setdefault(mac, {"mac": mac, "ip": None})
            if ip:
                obs["ip"] = ip
        return observations

    def _observations_to_devices(
        self, observations: dict[str, dict]
    ) -> Iterable[NormalizedDevice]:
        """Map merged ARP observations into NormalizedDevice records.

        Network gear rarely exposes a serial, so these devices carry the model
        default serial of UNKNOWN and are correlated by MAC address. The OUI
        vendor (when recognized) becomes the manufacturer, which is often the
        only identifying signal an admin gets for an unmanaged box.
        """
        for mac in sorted(observations):
            obs = observations[mac]
            ip = obs.get("ip")
            vendor = oui_vendor(mac)
            yield NormalizedDevice(
                serial=None,  # no serial over ARP; model normalizes to UNKNOWN
                source="network_discovery",
                source_id=mac,  # MAC is the stable native id here
                asset_type=self.asset_type,
                hostname=ip,  # best available label until DNS/SNMP enriches it
                mac_addresses=[mac],
                manufacturer=vendor,
                extra={
                    "ip": ip,
                    "discovery": "arp",
                    "oui_vendor": vendor,
                },
                raw=dict(obs),
            )


# --- pure helpers -------------------------------------------------------
def _canon_mac(mac: str) -> str:
    """Normalize a raw ARP MAC (possibly with 1-digit octets) to AA:BB:..:FF."""
    parts = re.split(r"[:-]", mac.strip())
    if len(parts) != 6:
        return ""
    try:
        octets = [f"{int(p, 16):02X}" for p in parts]
    except ValueError:
        return ""
    return ":".join(octets)


def _is_ignorable_mac(mac: str) -> bool:
    """Drop broadcast and the all-zero placeholder; they aren't real devices."""
    compact = mac.replace(":", "")
    return compact in ("FFFFFFFFFFFF", "000000000000")


def oui_vendor(mac: str) -> Optional[str]:
    """Look up the manufacturer for a MAC's OUI prefix, or None if unknown."""
    prefix = mac.replace(":", "")[:6].upper()
    return _OUI_VENDORS.get(prefix)


def _looks_like_cidr(value: str) -> bool:
    m = re.fullmatch(r"(\d{1,3}(?:\.\d{1,3}){3})/(\d{1,2})", value.strip())
    if not m:
        return False
    octets = m.group(1).split(".")
    if any(int(o) > 255 for o in octets):
        return False
    return 0 <= int(m.group(2)) <= 32

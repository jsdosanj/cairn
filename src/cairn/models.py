"""Core data model shared across every source, sink, and notifier.

A `NormalizedDevice` is the lingua franca of Cairn: every MDM/EDR source maps
its native payload into this shape, the merge step reconciles records that
describe the same physical machine, and every sink consumes this shape. Adding a
new provider never requires touching the sink or the orchestrator.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional


def _norm_mac(mac: Optional[str]) -> str:
    """Canonicalize a MAC to AA:BB:CC:DD:EE:FF.

    Handles the formats vendors actually emit: colon (Jamf), dash (CrowdStrike),
    Cisco dotted (aabb.ccdd.eeff), and bare 12-hex with no separators (Intune).
    """
    if not mac:
        return ""
    s = str(mac).strip().upper().replace("-", ":").replace(".", ":")
    compact = s.replace(":", "")
    if len(compact) == 12 and all(c in "0123456789ABCDEF" for c in compact):
        return ":".join(compact[i:i + 2] for i in range(0, 12, 2))
    return s


def mask_serial(serial: Optional[str]) -> str:
    """Show only the last 4 chars of a serial for logs/reports/notifications.

    Serial numbers are mildly sensitive (they identify a physical machine and
    seed warranty lookups), so Cairn never prints a full serial by default.
    """
    s = str(serial or "").strip()
    if not s or s == "UNKNOWN":
        return s or "UNKNOWN"
    if len(s) <= 4:
        return "*" * len(s)
    return "****" + s[-4:]


def _norm_serial(serial: Optional[str]) -> str:
    """Serial numbers are the join key across providers, so normalize hard.

    Uppercase, strip whitespace, drop obvious junk. Vendors disagree on case
    and padding; a stable key is what lets us correlate a Jamf record with a
    CrowdStrike record for the same laptop.
    """
    if not serial:
        return "UNKNOWN"
    cleaned = str(serial).strip().upper()
    return cleaned or "UNKNOWN"


@dataclass
class NormalizedDevice:
    """One physical device, normalized away from any single provider's schema."""

    serial: str
    source: str  # provider key that produced this record (e.g. "jamf")
    source_id: Optional[str] = None  # provider-native device id, for round-trips
    # Broad asset class so non-endpoint sources (network gear, procurement) fit:
    # computer | mobile | network | accessory | consumable | purchase_order
    asset_type: str = "computer"
    # The asset tag in the system of record. Populated when reading from Snipe-IT;
    # used by writeback targets to push the tag back into the MDM.
    asset_tag: Optional[str] = None
    hostname: Optional[str] = None
    mac_addresses: list[str] = field(default_factory=list)
    os_name: Optional[str] = None  # "macOS" | "Windows" | "Linux" | ...
    os_version: Optional[str] = None
    os_build: Optional[str] = None
    model: Optional[str] = None
    manufacturer: Optional[str] = None
    primary_user: Optional[str] = None
    primary_user_email: Optional[str] = None
    logged_in_users: Optional[str] = None
    last_seen: Optional[str] = None  # ISO-8601 last check-in / last contact
    # Security/compliance signal surfaced by EDR + MDM tools.
    compliance: Optional[str] = None  # "compliant" | "noncompliant" | None
    encrypted: Optional[bool] = None
    # Provider-specific normalized extras that don't fit a first-class field.
    extra: dict[str, Any] = field(default_factory=dict)
    # The untouched provider payload, for debugging and field-mapping overrides.
    raw: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.serial = _norm_serial(self.serial)
        # De-dupe and upper-case MACs for stable comparison.
        seen: list[str] = []
        for mac in self.mac_addresses or []:
            m = _norm_mac(mac)
            if m and m not in seen:
                seen.append(m)
        self.mac_addresses = seen

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Field precedence when two sources report the same machine. EDR tools tend to
# have fresher last-seen and security posture; MDM tools tend to own ownership
# and hardware metadata. We don't hard-code a winner per field beyond "prefer
# non-empty, then prefer the higher-priority source".
def merge_devices(
    devices: list[NormalizedDevice],
    source_priority: Optional[list[str]] = None,
) -> NormalizedDevice:
    """Reconcile multiple records for the same serial into one device.

    Strategy: start from the highest-priority source, then fill any empty field
    from lower-priority sources. MAC addresses are unioned. `extra`/`raw` are
    namespaced by source so nothing is lost.
    """
    if not devices:
        raise ValueError("merge_devices called with no devices")

    priority = source_priority or []

    def rank(d: NormalizedDevice) -> int:
        try:
            return priority.index(d.source)
        except ValueError:
            return len(priority)  # unknown sources sort last

    ordered = sorted(devices, key=rank)
    base = ordered[0]

    merged = NormalizedDevice(serial=base.serial, source="merged")
    merged.source_id = base.source_id
    # Asset class is intrinsic to the device; take it from the highest-priority
    # source (prefer any non-default classification if the top source is generic).
    merged.asset_type = next(
        (d.asset_type for d in ordered if d.asset_type and d.asset_type != "computer"),
        base.asset_type,
    )
    merged_sources = []
    all_macs: list[str] = []

    simple_fields = [
        "hostname", "source_id", "os_name", "os_version", "os_build", "model",
        "manufacturer", "primary_user", "primary_user_email",
        "logged_in_users", "last_seen", "compliance", "asset_tag",
    ]

    for d in ordered:
        merged_sources.append(d.source)
        all_macs.extend(d.mac_addresses)
        for f in simple_fields:
            if not getattr(merged, f) and getattr(d, f):
                setattr(merged, f, getattr(d, f))
        if merged.encrypted is None and d.encrypted is not None:
            merged.encrypted = d.encrypted
        # Namespace provider extras + raw so multiple sources coexist.
        if d.extra:
            merged.extra[d.source] = d.extra
        if d.raw:
            merged.raw[d.source] = d.raw

    merged.mac_addresses = all_macs  # __post_init__ already ran; set directly
    # Re-dedupe MACs.
    seen: list[str] = []
    for mac in all_macs:
        m = _norm_mac(mac)
        if m and m not in seen:
            seen.append(m)
    merged.mac_addresses = seen
    merged.extra["_sources"] = merged_sources
    merged.source = "+".join(merged_sources)
    return merged

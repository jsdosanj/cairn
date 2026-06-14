"""Network discovery source: ARP-table parsing, normalization, and merge.

The parsing / normalization / merge logic is pure and verified here against
fixtures for the three real ARP output formats (Linux `ip neigh`, macOS/BSD
`arp -a`, Windows `arp -a`). The OS probe (`_collect_arp_lines`) and the active
sweep (`_sweep`) are the only network-touching parts and are stubbed, so these
tests never touch the network — mirroring how the source isolates the probe
behind a boundary.
"""

import pytest

from cairn.models import merge_devices
from cairn.sources.base import SourceConfigError
from cairn.sources.network_discovery import (
    NetworkDiscoverySource,
    _canon_mac,
    oui_vendor,
)

# --- fixtures: the three real ARP output dialects ----------------------
LINUX_IP_NEIGH = """\
192.168.1.5 dev eth0 lladdr f4:f5:e8:11:22:33 REACHABLE
192.168.1.6 dev eth0 lladdr B8-27-EB-aa-bb-cc STALE
192.168.1.7 dev eth0  INCOMPLETE
192.168.1.1 dev eth0 lladdr 00:15:6d:00:00:01 REACHABLE
"""

MACOS_ARP = """\
? (192.168.1.5) at f4:f5:e8:11:22:33 on en0 ifscope [ethernet]
gateway (192.168.1.1) at 0:15:6d:0:0:1 on en0 ifscope [ethernet]
? (192.168.1.250) at (incomplete) on en0 ifscope [ethernet]
broadcast (192.168.1.255) at ff:ff:ff:ff:ff:ff on en0 ifscope [ethernet]
"""

WINDOWS_ARP = """\
Interface: 192.168.1.10 --- 0xb
  Internet Address      Physical Address      Type
  192.168.1.5           f4-f5-e8-11-22-33     dynamic
  192.168.1.255         ff-ff-ff-ff-ff-ff     static
"""


def _src(**cfg):
    return NetworkDiscoverySource(cfg)


# --- pure MAC / OUI helpers --------------------------------------------
def test_canon_mac_pads_and_uppercases():
    assert _canon_mac("0:15:6d:0:0:1") == "00:15:6D:00:00:01"
    assert _canon_mac("f4-f5-e8-11-22-33") == "F4:F5:E8:11:22:33"
    assert _canon_mac("not a mac") == ""


def test_oui_vendor_lookup():
    assert oui_vendor("F4:F5:E8:11:22:33") == "Google"
    assert oui_vendor("00:15:6D:00:00:01") == "Ubiquiti"
    assert oui_vendor("DE:AD:BE:EF:00:00") is None


# --- parsing each dialect ----------------------------------------------
def test_parse_linux_ip_neigh_drops_incomplete():
    obs = _src()._parse_arp_table(LINUX_IP_NEIGH.splitlines())
    assert set(obs) == {
        "F4:F5:E8:11:22:33",
        "B8:27:EB:AA:BB:CC",
        "00:15:6D:00:00:01",
    }
    assert obs["F4:F5:E8:11:22:33"]["ip"] == "192.168.1.5"


def test_parse_macos_arp_drops_broadcast_and_incomplete():
    obs = _src()._parse_arp_table(MACOS_ARP.splitlines())
    # broadcast ff:ff... and the (incomplete) row are both dropped.
    assert set(obs) == {"F4:F5:E8:11:22:33", "00:15:6D:00:00:01"}
    assert obs["00:15:6D:00:00:01"]["ip"] == "192.168.1.1"


def test_parse_windows_arp():
    obs = _src()._parse_arp_table(WINDOWS_ARP.splitlines())
    assert set(obs) == {"F4:F5:E8:11:22:33"}  # broadcast dropped
    assert obs["F4:F5:E8:11:22:33"]["ip"] == "192.168.1.5"


# --- observations -> NormalizedDevice ----------------------------------
def test_fetch_all_maps_to_normalized_devices(monkeypatch):
    src = _src()
    monkeypatch.setattr(src, "_collect_arp_lines", lambda: LINUX_IP_NEIGH.splitlines())
    devices = list(src.fetch_all())
    assert len(devices) == 3
    by_mac = {d.mac_addresses[0]: d for d in devices}
    google = by_mac["F4:F5:E8:11:22:33"]
    assert google.serial == "UNKNOWN"  # no serial over ARP
    assert google.asset_type == "network"
    assert google.manufacturer == "Google"
    assert google.source == "network_discovery"
    assert google.source_id == "F4:F5:E8:11:22:33"
    assert google.extra["ip"] == "192.168.1.5"
    rpi = by_mac["B8:27:EB:AA:BB:CC"]
    assert rpi.manufacturer == "Raspberry Pi Foundation"


def test_discovered_device_merges_with_managed_record_by_mac():
    """A discovery hit and a managed record for the same box share a MAC; the
    merge keeps the managed serial and unions the discovery MAC."""
    src = _src()
    discovered = list(src._observations_to_devices(
        {"F4:F5:E8:11:22:33": {"mac": "F4:F5:E8:11:22:33", "ip": "192.168.1.5"}}
    ))[0]
    from cairn.models import NormalizedDevice
    managed = NormalizedDevice(
        serial="SER-123", source="jamf", hostname="laptop-1",
        mac_addresses=["F4:F5:E8:11:22:33"],
    )
    merged = merge_devices([managed, discovered], ["jamf", "network_discovery"])
    assert merged.serial == "SER-123"
    assert "F4:F5:E8:11:22:33" in merged.mac_addresses
    assert merged.manufacturer == "Google"  # backfilled from discovery


# --- safe defaults: no scanning without explicit opt-in ----------------
def test_passive_by_default_no_sweep(monkeypatch):
    src = _src()
    assert src.active_sweep is False
    swept = {"called": False}
    monkeypatch.setattr(src, "_sweep", lambda cidr: swept.__setitem__("called", True))
    monkeypatch.setattr(src, "_collect_arp_lines", lambda: [])
    list(src.fetch_all())
    assert swept["called"] is False  # never sweeps without opt-in


def test_active_sweep_requires_cidr():
    # active_sweep=true but no cidr -> stays passive (safe).
    src = _src(active_sweep=True)
    assert src.active_sweep is False


def test_active_sweep_opt_in(monkeypatch):
    src = _src(cidr="192.168.1.0/24", active_sweep=True)
    assert src.active_sweep is True
    swept = {"cidr": None}
    monkeypatch.setattr(src, "_sweep", lambda cidr: swept.__setitem__("cidr", cidr))
    monkeypatch.setattr(src, "_collect_arp_lines", lambda: [])
    list(src.fetch_all())
    assert swept["cidr"] == "192.168.1.0/24"


def test_bad_cidr_rejected():
    with pytest.raises(SourceConfigError):
        _src(cidr="not-a-cidr")
    with pytest.raises(SourceConfigError):
        _src(cidr="10.0.0.0/40")

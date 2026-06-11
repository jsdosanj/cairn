"""Tests for the P2 connectors: Apple BM, UniFi, CDW, Rudder."""

import responses

from cairn.sources.apple_business_manager import AppleBusinessManagerSource
from cairn.sources.cdw import CdwSource
from cairn.sources.rudder import RudderSource
from cairn.sources.unifi import UniFiSource


# --- CDW (CSV file import) ---------------------------------------------
def test_cdw_imports_csv_with_purchase_metadata(tmp_path):
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text(
        "Serial Number,Product Description,Asset Tag,Order Number,Unit Price,Order Date\n"
        "SER-CDW-1,Dell Latitude 7440,WS-1042,ORD-99,1299.00,2026-01-05\n"
        ",,,,,\n"  # empty row -> skipped (no serial, no order)
    )
    src = CdwSource({"csv_file": str(csv_path)})
    devices = list(src.fetch_all())
    assert len(devices) == 1
    d = devices[0]
    assert d.serial == "SER-CDW-1"
    assert d.model == "Dell Latitude 7440"
    assert d.asset_type == "computer"
    assert d.source_id == "ORD-99"
    assert d.extra["purchase_cost"] == "1299.00"
    assert d.extra["purchase_date"] == "2026-01-05"


def test_cdw_missing_file_raises():
    import pytest
    from cairn.sources.base import SourceConfigError
    src = CdwSource({"csv_file": "/no/such/file.csv"})
    with pytest.raises(SourceConfigError):
        list(src.fetch_all())


# --- UniFi --------------------------------------------------------------
@responses.activate
def test_unifi_fetch_all_iterates_sites_and_devices():
    host = "https://192.168.1.1"
    api = f"{host}/proxy/network/integration/v1"
    responses.add(responses.GET, f"{api}/sites", json={"data": [{"id": "s1"}]}, status=200)
    responses.add(
        responses.GET, f"{api}/sites/s1/devices",
        json={"data": [{
            "id": "u1", "name": "AP-Office", "model": "U6-Pro",
            "macAddress": "aa:bb:cc:11:22:33", "firmwareVersion": "6.6.55",
            "state": "ONLINE", "ipAddress": "192.168.1.10", "type": "uap",
        }], "totalCount": 1, "offset": 0, "limit": 200},
        status=200,
    )
    src = UniFiSource({"host": host, "api_key": "k", "verify_ssl": False})
    devices = list(src.fetch_all())
    assert len(devices) == 1
    d = devices[0]
    assert d.asset_type == "network"
    assert d.manufacturer == "Ubiquiti"
    assert d.hostname == "AP-Office"
    assert d.mac_addresses == ["AA:BB:CC:11:22:33"]
    assert src.session.verify is False  # self-signed support
    assert responses.calls[0].request.headers["X-API-KEY"] == "k"


# --- Apple Business Manager --------------------------------------------
@responses.activate
def test_apple_bm_fetch_all(monkeypatch):
    src = AppleBusinessManagerSource({
        "client_id": "cid", "key_id": "kid", "private_key": "-----FAKE-----",
    })
    monkeypatch.setattr(src, "_get_access_token", lambda: "tok")
    responses.add(
        responses.GET, "https://api-business.apple.com/v1/orgDevices",
        json={"data": [{
            "id": "abm-1", "type": "orgDevices",
            "attributes": {"serialNumber": "SER-ABM-1", "deviceModel": "MacBookPro18,3",
                           "productFamily": "Mac", "addedToOrgDateTime": "2026-01-01T00:00:00Z"},
        }]},  # no links.next -> single page
        status=200,
    )
    devices = list(src.fetch_all())
    assert len(devices) == 1
    d = devices[0]
    assert d.serial == "SER-ABM-1"
    assert d.os_name == "macOS"
    assert d.asset_type == "computer"
    assert d.manufacturer == "Apple"
    assert d.source_id == "abm-1"


# --- Rudder -------------------------------------------------------------
@responses.activate
def test_rudder_fetch_all():
    base = "https://rudder.example.com"
    responses.add(
        responses.GET, f"{base}/rudder/api/latest/nodes",
        json={"result": "success", "data": {"nodes": [{
            "id": "node-1", "hostname": "web-01",
            "os": {"name": "Ubuntu", "version": "22.04"},
            "machine": {"serialNumber": "SER-RUD-1"},
            "networkInterfaces": [{"macAddress": "AA:00:11:22:33:44"}],
            "lastInventoryDate": "2026-01-03T00:00:00Z",
            "policyMode": "enforce", "state": "enabled",
        }]}},
        status=200,
    )
    src = RudderSource({"url": base, "api_token": "t"})
    devices = list(src.fetch_all())
    assert len(devices) == 1
    d = devices[0]
    assert d.serial == "SER-RUD-1"
    assert d.os_name == "Linux"
    assert d.asset_type == "computer"
    assert d.mac_addresses == ["AA:00:11:22:33:44"]
    assert responses.calls[0].request.headers["X-API-Token"] == "t"

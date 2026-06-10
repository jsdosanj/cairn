"""Tests for the P1 connectors: Kandji and Google Workspace (ChromeOS)."""

import responses

from cairn.models import NormalizedDevice, merge_devices
from cairn.sources.kandji import KandjiSource
from cairn.sources.google_workspace import GoogleWorkspaceSource


# --- Kandji -------------------------------------------------------------
@responses.activate
def test_kandji_fetch_all_maps_platform_and_asset_type():
    base = "https://acme.api.kandji.io"
    responses.add(
        responses.GET, f"{base}/api/v1/devices",
        json=[
            {"device_id": "k1", "serial_number": "SER-MAC-1", "device_name": "mac-1",
             "platform": "Mac", "os_version": "14.4", "model": "MacBookPro18,3",
             "mac_address": "AA:BB:CC:DD:EE:01", "last_check_in": "2026-01-01T00:00:00Z",
             "user": {"name": "Jo Doe", "email": "jo@x.com"}},
            {"device_id": "k2", "serial_number": "SER-IPH-1", "device_name": "iphone-1",
             "platform": "iPhone", "os_version": "17.4", "model": "iPhone15,2",
             "user": "shared-device"},
        ],
        status=200,
    )
    src = KandjiSource({"api_url": base, "api_token": "tok"})
    devices = list(src.fetch_all())
    assert len(devices) == 2
    mac, iphone = devices
    assert mac.serial == "SER-MAC-1"
    assert mac.os_name == "macOS"
    assert mac.asset_type == "computer"
    assert mac.primary_user == "Jo Doe"
    assert mac.primary_user_email == "jo@x.com"
    assert mac.manufacturer == "Apple"
    assert iphone.os_name == "iOS"
    assert iphone.asset_type == "mobile"
    assert iphone.primary_user == "shared-device"  # bare string user
    # Bearer token sent
    assert responses.calls[0].request.headers["Authorization"] == "Bearer tok"


# --- Google Workspace / ChromeOS ---------------------------------------
@responses.activate
def test_google_chromeos_fetch_all(monkeypatch):
    src = GoogleWorkspaceSource({
        "subject": "admin@x.com",
        "service_account_info": {"client_email": "sa@x.iam", "private_key": "KEY"},
    })
    # Avoid real JWT signing / token exchange.
    monkeypatch.setattr(src, "_get_access_token", lambda: "tok")
    responses.add(
        responses.GET,
        "https://admin.googleapis.com/admin/directory/v1/customer/my_customer/devices/chromeos",
        json={"chromeosdevices": [{
            "deviceId": "g1", "serialNumber": "SER-CR-1", "annotatedAssetId": "asset-7",
            "model": "HP Chromebook", "osVersion": "120.0", "macAddress": "AABBCCDDEE02",
            "lastSync": "2026-01-02T00:00:00Z", "annotatedUser": "user@x.com",
            "status": "ACTIVE",
        }]},
        status=200,
    )
    devices = list(src.fetch_all())
    assert len(devices) == 1
    d = devices[0]
    assert d.serial == "SER-CR-1"
    assert d.os_name == "ChromeOS"
    assert d.asset_type == "computer"
    assert d.manufacturer == "Google"
    assert d.hostname == "asset-7"
    assert d.mac_addresses == ["AA:BB:CC:DD:EE:02"]  # bare hex normalized
    assert d.extra["status"] == "ACTIVE"
    assert d.compliance is None


def test_google_requires_subject_and_credentials():
    import pytest
    from cairn.sources.base import SourceConfigError
    with pytest.raises(SourceConfigError):
        GoogleWorkspaceSource({"service_account_info": {"client_email": "x", "private_key": "k"}})
    with pytest.raises(SourceConfigError):
        GoogleWorkspaceSource({"subject": "a@x.com"})


# --- asset_type reconciliation -----------------------------------------
def test_merge_preserves_non_default_asset_type():
    # A generic "computer" record + a "network" record for the same serial:
    # the non-default classification should win.
    a = NormalizedDevice(serial="S1", source="jamf", hostname="h")  # computer (default)
    b = NormalizedDevice(serial="S1", source="unifi", asset_type="network")
    merged = merge_devices([a, b], source_priority=["jamf", "unifi"])
    assert merged.asset_type == "network"

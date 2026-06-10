"""Provider tests: mock auth + list endpoints, assert normalization."""

import responses

from cairn.sources.crowdstrike import CrowdStrikeSource
from cairn.sources.intune import IntuneSource
from cairn.sources.jamf import JamfSource
from cairn.sources.jumpcloud import JumpCloudSource


# --- Intune -------------------------------------------------------------
@responses.activate
def test_intune_fetch_all():
    responses.add(
        responses.POST,
        "https://login.microsoftonline.com/T1/oauth2/v2.0/token",
        json={"access_token": "tok", "expires_in": 3600}, status=200,
    )
    responses.add(
        responses.GET,
        "https://graph.microsoft.com/v1.0/deviceManagement/managedDevices",
        json={"value": [{
            "id": "g1", "serialNumber": "SER-INT-1", "deviceName": "win-box",
            "operatingSystem": "Windows", "osVersion": "10.0.19045",
            "manufacturer": "Dell", "model": "Latitude",
            "userPrincipalName": "u@x.com", "emailAddress": "u@x.com",
            "complianceState": "compliant", "isEncrypted": True,
            "wiFiMacAddress": "AABBCCDDEEFF", "lastSyncDateTime": "2026-01-01T00:00:00Z",
        }]}, status=200,
    )
    src = IntuneSource({"tenant_id": "T1", "client_id": "c", "client_secret": "s"})
    devices = list(src.fetch_all())
    assert len(devices) == 1
    d = devices[0]
    assert d.serial == "SER-INT-1"
    assert d.os_name == "Windows"
    assert d.compliance == "compliant"
    assert d.encrypted is True
    assert d.mac_addresses == ["AA:BB:CC:DD:EE:FF"]


# --- Jamf ---------------------------------------------------------------
@responses.activate
def test_jamf_fetch_all_client_creds():
    base = "https://jamf.example.com"
    responses.add(responses.POST, f"{base}/api/oauth/token",
                  json={"access_token": "tok", "expires_in": 1200}, status=200)
    responses.add(
        responses.GET, f"{base}/api/v1/computers-inventory",
        json={"totalCount": 1, "results": [{
            "id": 12,
            "general": {"name": "macbook", "lastContactTime": "2026-01-02T00:00:00Z"},
            "hardware": {"serialNumber": "SER-JAMF-1", "model": "MacBookPro18,3",
                         "macAddress": "00:11:22:33:44:55"},
            "operatingSystem": {"name": "macOS", "version": "14.4", "build": "23E214"},
            "userAndLocation": {"username": "jdoe", "email": "jdoe@x.com"},
        }]}, status=200,
    )
    src = JamfSource({"url": base, "client_id": "c", "client_secret": "s"})
    devices = list(src.fetch_all())
    assert len(devices) == 1
    d = devices[0]
    assert d.serial == "SER-JAMF-1"
    assert d.os_name == "macOS"
    assert d.manufacturer == "Apple"
    assert d.primary_user == "jdoe"
    assert d.source_id == "12"


# --- JumpCloud ----------------------------------------------------------
@responses.activate
def test_jumpcloud_fetch_all_and_short_page_stops():
    base = "https://console.jumpcloud.com/api"
    responses.add(
        responses.GET, f"{base}/systems",
        json={"results": [{
            "_id": "jc1", "serialNumber": "SER-JC-1", "displayName": "ubuntu-1",
            "os": "Ubuntu", "version": "22.04", "lastContact": "2026-01-03T00:00:00Z",
            "networkInterfaces": [{"address": "AA:11:BB:22:CC:33"},
                                  {"address": "00:00:00:00:00:00"}],
            "fdeActive": True,
        }]}, status=200,
    )
    src = JumpCloudSource({"api_key": "k"})
    devices = list(src.fetch_all())
    assert len(devices) == 1
    d = devices[0]
    assert d.serial == "SER-JC-1"
    assert d.os_name == "Linux"
    assert d.encrypted is True
    # loopback filtered out
    assert d.mac_addresses == ["AA:11:BB:22:CC:33"]
    # x-api-key header was sent
    assert responses.calls[0].request.headers["x-api-key"] == "k"


# --- CrowdStrike --------------------------------------------------------
@responses.activate
def test_crowdstrike_two_step_query_and_hydrate():
    base = "https://api.crowdstrike.com"
    responses.add(responses.POST, f"{base}/oauth2/token",
                  json={"access_token": "tok", "expires_in": 1800}, status=200)
    responses.add(
        responses.GET, f"{base}/devices/queries/devices/v1",
        json={"resources": ["dev-1"], "meta": {"pagination": {"total": 1}}}, status=200,
    )
    responses.add(
        responses.POST, f"{base}/devices/entities/devices/v2",
        json={"resources": [{
            "device_id": "dev-1", "serial_number": "SER-CS-1", "hostname": "cs-host",
            "platform_name": "Mac", "os_version": "14.4", "os_build": "23E214",
            "mac_address": "aa-bb-cc-dd-ee-ff", "system_product_name": "MacBookPro18,3",
            "system_manufacturer": "Apple Inc.", "last_seen": "2026-01-04T00:00:00Z",
        }]}, status=200,
    )
    src = CrowdStrikeSource({"client_id": "c", "client_secret": "s"})
    devices = list(src.fetch_all())
    assert len(devices) == 1
    d = devices[0]
    assert d.serial == "SER-CS-1"
    assert d.os_name == "macOS"
    assert d.mac_addresses == ["AA:BB:CC:DD:EE:FF"]
    assert d.source_id == "dev-1"

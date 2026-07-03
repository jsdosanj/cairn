import responses

from cairn.models import NormalizedDevice
from cairn.sinks.base import SyncResult
from cairn.sinks.snipeit import SnipeITSink, generate_asset_tag

BASE = "https://snipe.example.com/api/v1"


def _sink():
    return SnipeITSink({"url": BASE, "token": "tok", "_defaults": {"company_id": 1, "site_id": 1}})


def _device():
    return NormalizedDevice(
        serial="ABC123", source="jamf", hostname="ws-1042",
        os_name="macOS", os_version="14.4", mac_addresses=["AA:BB:CC:DD:EE:FF"],
    )


def test_generate_asset_tag_from_hostname():
    assert generate_asset_tag("ABC123", "ws-1042") == "1042"


def test_generate_asset_tag_fallback():
    assert generate_asset_tag("ZZ99XYZ", "laptop").startswith("CASID-")


@responses.activate
def test_create_new_asset():
    responses.add(responses.GET, f"{BASE}/hardware", json={"rows": []}, status=200)
    responses.add(responses.GET, f"{BASE}/models", json={"rows": [{"id": 7}]}, status=200)
    responses.add(responses.POST, f"{BASE}/hardware",
                  json={"status": "success", "payload": {"id": 99}}, status=200)
    result = _sink().upsert(_device())
    assert result.action == SyncResult.CREATED
    assert result.serial == "ABC123"
    # body sent to create includes the serial and a model_id
    create_call = [c for c in responses.calls if c.request.method == "POST"][0]
    assert "ABC123" in create_call.request.body.decode()


@responses.activate
def test_update_existing_asset():
    responses.add(responses.GET, f"{BASE}/hardware",
                  json={"rows": [{"id": 5, "asset_tag": "1042", "serial": "ABC123"}]}, status=200)
    responses.add(responses.PUT, f"{BASE}/hardware/5",
                  json={"status": "success"}, status=200)
    result = _sink().upsert(_device())
    assert result.action == SyncResult.UPDATED
    assert result.identifier == "1042"


@responses.activate
def test_dry_run_writes_nothing():
    responses.add(responses.GET, f"{BASE}/hardware", json={"rows": []}, status=200)
    responses.add(responses.GET, f"{BASE}/models", json={"rows": [{"id": 1}]}, status=200)
    result = _sink().upsert(_device(), dry_run=True)
    assert result.action == SyncResult.CREATED
    assert result.detail == "dry-run"
    assert not [c for c in responses.calls if c.request.method == "POST"]


@responses.activate
def test_create_failure_returns_failed_result():
    responses.add(responses.GET, f"{BASE}/hardware", json={"rows": []}, status=200)
    responses.add(responses.GET, f"{BASE}/models", json={"rows": [{"id": 1}]}, status=200)
    responses.add(responses.POST, f"{BASE}/hardware",
                  json={"status": "error", "messages": {"asset_tag": "taken"}}, status=200)
    result = _sink().upsert(_device())
    assert result.action == SyncResult.FAILED


@responses.activate
def test_no_exact_serial_match_creates_instead_of_updating_wrong_asset():
    # Snipe-IT fuzzy search returns an UNRELATED asset (different serial). We must NOT
    # bind to it — that would UPDATE the wrong record and corrupt the CMDB. Treat as
    # not-found and CREATE the genuinely-new device.
    responses.add(responses.GET, f"{BASE}/hardware",
                  json={"rows": [{"id": 5, "asset_tag": "9999", "serial": "OTHER-SERIAL"}]}, status=200)
    responses.add(responses.GET, f"{BASE}/models", json={"rows": [{"id": 7}]}, status=200)
    responses.add(responses.POST, f"{BASE}/hardware",
                  json={"status": "success", "payload": {"id": 100}}, status=200)
    result = _sink().upsert(_device())
    assert result.action == SyncResult.CREATED
    assert not [c for c in responses.calls if c.request.method == "PUT"]  # never touched the wrong asset


@responses.activate
def test_update_failure_returns_failed_result():
    # Snipe-IT returns {"status":"error"} with HTTP 200 on a rejected PUT — must surface FAILED.
    responses.add(responses.GET, f"{BASE}/hardware",
                  json={"rows": [{"id": 5, "asset_tag": "1042", "serial": "ABC123"}]}, status=200)
    responses.add(responses.PUT, f"{BASE}/hardware/5",
                  json={"status": "error", "messages": {"name": "invalid"}}, status=200)
    result = _sink().upsert(_device())
    assert result.action == SyncResult.FAILED

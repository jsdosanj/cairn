"""Tests for P3: Snipe-IT read source + Jamf/Intune writeback + orchestrator flow."""

import responses

from cairn.models import NormalizedDevice
from cairn.sources.snipeit import SnipeITSource
from cairn.writebacks.base import WritebackResult
from cairn.writebacks.jamf import JamfWriteback
from cairn.writebacks.intune import IntuneWriteback


# --- Snipe-IT read source ----------------------------------------------
@responses.activate
def test_snipeit_source_reads_asset_tag():
    base = "https://snipe.example.com/api/v1"
    responses.add(responses.GET, f"{base}/hardware",
                  json={"total": 1, "rows": [{
                      "id": 5, "serial": "SER-1", "asset_tag": "WS-1042",
                      "name": "ws-1042", "model": {"name": "Latitude"},
                  }]}, status=200)
    src = SnipeITSource({"url": base, "token": "t"})
    devices = list(src.fetch_all())
    assert len(devices) == 1
    d = devices[0]
    assert d.serial == "SER-1"
    assert d.asset_tag == "WS-1042"
    assert d.model == "Latitude"


# --- Jamf writeback -----------------------------------------------------
JAMF = "https://jamf.example.com"


def _add_jamf_token():
    responses.add(responses.POST, f"{JAMF}/api/oauth/token",
                  json={"access_token": "tok", "expires_in": 1200}, status=200)


def _add_jamf_lookup(asset_tag):
    responses.add(responses.GET, f"{JAMF}/api/v1/computers-inventory",
                  json={"results": [{"id": 42, "general": {"assetTag": asset_tag}}]}, status=200)


def _jamf_device(tag="WS-1042"):
    return NormalizedDevice(serial="SER-1", source="snipeit", asset_tag=tag)


@responses.activate
def test_jamf_writeback_dry_run_reports_change():
    _add_jamf_token(); _add_jamf_lookup(asset_tag="OLD-TAG")
    wb = JamfWriteback({"url": JAMF, "client_id": "c", "client_secret": "s"})
    res = wb.push(_jamf_device("WS-1042"), dry_run=True)
    assert res.action == WritebackResult.UPDATED
    assert "would set" in res.detail
    # no PATCH issued in dry-run
    assert not [c for c in responses.calls if c.request.method == "PATCH"]


@responses.activate
def test_jamf_writeback_applies_patch():
    _add_jamf_token(); _add_jamf_lookup(asset_tag="OLD-TAG")
    responses.add(responses.PATCH, f"{JAMF}/api/v1/computers-inventory-detail/42",
                  json={"id": 42}, status=200)
    wb = JamfWriteback({"url": JAMF, "client_id": "c", "client_secret": "s"})
    res = wb.push(_jamf_device("WS-1042"), dry_run=False)
    assert res.action == WritebackResult.UPDATED
    patch = [c for c in responses.calls if c.request.method == "PATCH"][0]
    assert "WS-1042" in patch.request.body.decode()


@responses.activate
def test_jamf_writeback_skips_when_already_correct():
    _add_jamf_token(); _add_jamf_lookup(asset_tag="WS-1042")  # already matches
    wb = JamfWriteback({"url": JAMF, "client_id": "c", "client_secret": "s"})
    res = wb.push(_jamf_device("WS-1042"), dry_run=False)
    assert res.action == WritebackResult.SKIPPED


@responses.activate
def test_jamf_writeback_only_if_empty_declines_nonempty():
    _add_jamf_token(); _add_jamf_lookup(asset_tag="EXISTING")
    wb = JamfWriteback({"url": JAMF, "client_id": "c", "client_secret": "s",
                        "conflict": "only_if_empty"})
    res = wb.push(_jamf_device("WS-1042"), dry_run=False)
    assert res.action == WritebackResult.SKIPPED


@responses.activate
def test_jamf_writeback_skips_when_not_in_jamf():
    _add_jamf_token()
    responses.add(responses.GET, f"{JAMF}/api/v1/computers-inventory",
                  json={"results": []}, status=200)
    wb = JamfWriteback({"url": JAMF, "client_id": "c", "client_secret": "s"})
    res = wb.push(_jamf_device(), dry_run=False)
    assert res.action == WritebackResult.SKIPPED
    assert "not in Jamf" in res.detail


def test_jamf_writeback_skips_without_asset_tag():
    # no asset tag -> skipped before any network call (setup still needs token)
    responses.start()
    try:
        _add_jamf_token()
        wb = JamfWriteback({"url": JAMF, "client_id": "c", "client_secret": "s"})
        res = wb.push(NormalizedDevice(serial="SER-1", source="snipeit"), dry_run=False)
        assert res.action == WritebackResult.SKIPPED
    finally:
        responses.stop(); responses.reset()


# --- Intune writeback ---------------------------------------------------
@responses.activate
def test_intune_writeback_applies_patch():
    responses.add(responses.POST,
                  "https://login.microsoftonline.com/T1/oauth2/v2.0/token",
                  json={"access_token": "tok", "expires_in": 3600}, status=200)
    responses.add(responses.GET,
                  "https://graph.microsoft.com/v1.0/deviceManagement/managedDevices",
                  json={"value": [{"id": "g1", "notes": None}]}, status=200)
    responses.add(responses.PATCH,
                  "https://graph.microsoft.com/v1.0/deviceManagement/managedDevices/g1",
                  json={}, status=200)
    wb = IntuneWriteback({"tenant_id": "T1", "client_id": "c", "client_secret": "s"})
    res = wb.push(NormalizedDevice(serial="SER-1", source="snipeit", asset_tag="WS-9"),
                  dry_run=False)
    assert res.action == WritebackResult.UPDATED
    patch = [c for c in responses.calls if c.request.method == "PATCH"][0]
    assert "WS-9" in patch.request.body.decode()


# --- orchestrator writeback flow ---------------------------------------
def test_orchestrator_run_writeback(monkeypatch):
    import cairn.orchestrator as orch_mod
    from cairn.sinks.snipeit import SnipeITSink

    pushed = []

    class FakeReader:
        def __init__(self, cfg): pass
        def fetch_all(self):
            return [
                NormalizedDevice(serial="S1", source="snipeit", asset_tag="T1"),
                NormalizedDevice(serial="S2", source="snipeit", asset_tag=None),  # skip
            ]

    class FakeWriteback:
        key = "jamf"
        def __init__(self, cfg): pass
        def push(self, device, dry_run=True):
            pushed.append((device.serial, dry_run))
            return WritebackResult(WritebackResult.UPDATED, device.serial, "ok")

    monkeypatch.setattr(orch_mod, "get_source_class", lambda key: FakeReader)
    monkeypatch.setattr(orch_mod, "get_writeback_class", lambda key: FakeWriteback)
    monkeypatch.setattr(orch_mod, "get_sink_class", lambda key: SnipeITSink)

    config = {
        "mode": "fleet",
        "sinks": {"snipeit": {"url": "https://snipe.example.com/api/v1", "token": "t"}},
        "writebacks": {"jamf": {"enabled": True}},
        "notifiers": {}, "sources": {}, "defaults": {},
    }
    summary = orch_mod.Orchestrator(config).run_writeback(dry_run=True)
    assert summary.assets_read == 2
    assert summary.updated == 1          # only S1 (has asset_tag)
    assert pushed == [("S1", True)]      # S2 skipped (no tag), dry_run propagated

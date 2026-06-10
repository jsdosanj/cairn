from cairn.models import NormalizedDevice
from cairn.orchestrator import Orchestrator
from cairn.sinks.base import AssetSink, SyncResult
from cairn.sources.base import DeviceSource


class FakeSource(DeviceSource):
    key = "fake"
    display_name = "Fake"
    _devices: list = []

    def fetch_all(self):
        return list(type(self)._devices)

    def find_by_serial(self, serial):
        for d in type(self)._devices:
            if d.serial == serial.strip().upper():
                return d
        return None


class FakeSink(AssetSink):
    key = "fakesink"
    display_name = "FakeSink"
    upserts: list = []

    def upsert(self, device, dry_run=False):
        type(self).upserts.append((device.serial, dry_run))
        return SyncResult(SyncResult.CREATED, device.serial, "tag")


def _patch_registry(monkeypatch, source_cls, sink_cls):
    import cairn.orchestrator as orch
    monkeypatch.setattr(orch, "get_source_class", lambda key: source_cls)
    monkeypatch.setattr(orch, "get_sink_class", lambda key: sink_cls)
    monkeypatch.setattr(orch, "get_notifier_class", lambda key: None)


def _config():
    return {
        "mode": "fleet",
        "source_priority": ["fake"],
        "sources": {"fake": {"enabled": True}},
        "sinks": {"fakesink": {"enabled": True}},
        "notifiers": {},
        "defaults": {},
    }


def test_fleet_run_merges_by_serial(monkeypatch):
    FakeSink.upserts = []
    FakeSource._devices = [
        NormalizedDevice(serial="S1", source="fake", hostname="a"),
        NormalizedDevice(serial="S1", source="fake", os_version="14"),  # same serial
        NormalizedDevice(serial="S2", source="fake", hostname="b"),
    ]
    _patch_registry(monkeypatch, FakeSource, FakeSink)
    summary = Orchestrator(_config()).run()
    # S1 reconciled into one device, S2 separate -> 2 upserts
    assert summary.devices_seen == 2
    assert summary.created == 2
    assert {s for s, _ in FakeSink.upserts} == {"S1", "S2"}


def test_unkeyed_devices_still_synced(monkeypatch):
    FakeSink.upserts = []
    FakeSource._devices = [NormalizedDevice(serial="UNKNOWN", source="fake", hostname="x")]
    _patch_registry(monkeypatch, FakeSource, FakeSink)
    summary = Orchestrator(_config()).run()
    assert summary.devices_seen == 1


def test_dry_run_propagates(monkeypatch):
    FakeSink.upserts = []
    FakeSource._devices = [NormalizedDevice(serial="S1", source="fake")]
    _patch_registry(monkeypatch, FakeSource, FakeSink)
    Orchestrator(_config()).run(dry_run=True)
    assert FakeSink.upserts == [("S1", True)]


def test_source_error_recorded_not_fatal(monkeypatch):
    class BoomSource(FakeSource):
        def fetch_all(self):
            raise RuntimeError("api down")

    FakeSink.upserts = []
    _patch_registry(monkeypatch, BoomSource, FakeSink)
    summary = Orchestrator(_config()).run()
    assert "fake" in summary.source_errors
    assert summary.devices_seen == 0

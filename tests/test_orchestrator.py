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


def _config(**overrides):
    cfg = {
        "mode": "fleet",
        "source_priority": ["fake"],
        "sources": {"fake": {"enabled": True}},
        "sinks": {"fakesink": {"enabled": True}},
        "notifiers": {},
        "defaults": {},
        "incremental": False,  # tests don't touch the real ~/.cairn state by default
    }
    cfg.update(overrides)
    return cfg


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


def test_incremental_skips_unchanged_on_second_run(monkeypatch, tmp_path):
    FakeSource._devices = [NormalizedDevice(serial="S1", source="fake", hostname="a")]
    _patch_registry(monkeypatch, FakeSource, FakeSink)
    cfg = _config(incremental=True, state_path=str(tmp_path / "state.json"))

    FakeSink.upserts = []
    first = Orchestrator(cfg).run()
    assert first.created == 1  # written the first time

    FakeSink.upserts = []
    second = Orchestrator(cfg).run()  # nothing changed
    assert second.skipped == 1
    assert second.created == 0
    assert FakeSink.upserts == []  # the sink was never called the second time


def test_full_flag_overrides_incremental(monkeypatch, tmp_path):
    FakeSource._devices = [NormalizedDevice(serial="S1", source="fake", hostname="a")]
    _patch_registry(monkeypatch, FakeSource, FakeSink)
    cfg = _config(incremental=True, state_path=str(tmp_path / "state.json"))
    Orchestrator(cfg).run()
    FakeSink.upserts = []
    summary = Orchestrator(cfg).run(full=True)  # force re-sync
    assert summary.created == 1
    assert FakeSink.upserts == [("S1", False)]


def test_run_drift_diffs_sources_against_snipeit(monkeypatch):
    # Observed by the source: S1 (matches CMDB) and S2 (missing from CMDB).
    FakeSource._devices = [
        NormalizedDevice(serial="S1", source="fake", hostname="a"),
        NormalizedDevice(serial="S2", source="fake", hostname="b"),
    ]

    class FakeSnipeReader(DeviceSource):
        key = "snipeit"

        def fetch_all(self):
            # CMDB holds S1 (consistent) only — S2 is missing.
            return [NormalizedDevice(serial="S1", source="snipeit", hostname="a", asset_tag="A1")]

    import cairn.orchestrator as orch
    # Sources build via get_source_class("fake"); the reader is also fetched via
    # get_source_class("snipeit"). Route each to the right fake.
    classes = {"fake": FakeSource, "snipeit": FakeSnipeReader}
    monkeypatch.setattr(orch, "get_source_class", lambda key: classes[key])
    monkeypatch.setattr(orch, "get_sink_class", lambda key: FakeSink)
    monkeypatch.setattr(orch, "get_notifier_class", lambda key: None)

    cfg = _config(sinks={"snipeit": {"enabled": True}})
    report = Orchestrator(cfg).run_drift(stale_days=30)
    cats = {f.serial: f.category for f in report.findings}
    assert cats["S1"] == "ok"
    assert cats["S2"] == "missing"


def test_source_error_recorded_not_fatal(monkeypatch):
    class BoomSource(FakeSource):
        def fetch_all(self):
            raise RuntimeError("api down")

    FakeSink.upserts = []
    _patch_registry(monkeypatch, BoomSource, FakeSink)
    summary = Orchestrator(_config()).run()
    assert "fake" in summary.source_errors
    assert summary.devices_seen == 0

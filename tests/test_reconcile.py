"""Reconciliation / drift engine tests.

The engine takes two plain lists of NormalizedDevice (observed vs. system of
record) and does no I/O, so these are fast pure-function tests.
"""

from datetime import datetime, timedelta, timezone

import pytest

from cairn.models import NormalizedDevice, mask_serial, merge_devices
from cairn.reconcile import (
    CONFLICTING,
    DUPLICATE,
    MISSING,
    OK,
    STALE,
    DriftReport,
    reconcile,
    render_text,
)

NOW = datetime(2026, 6, 14, tzinfo=timezone.utc)


def _obs(serial, source="jamf", **kw):
    return NormalizedDevice(serial=serial, source=source, **kw)


def _rec(serial, **kw):
    return NormalizedDevice(serial=serial, source="snipeit", **kw)


def test_missing_when_observed_but_not_in_record():
    report = reconcile([_obs("S1")], [], now=NOW)
    f = report.by_category(MISSING)
    assert len(f) == 1
    assert f[0].serial == "S1"
    assert f[0].observed_by == ["jamf"]


def test_ok_when_present_and_consistent():
    obs = [_obs("S1", hostname="mac-1", model="MacBook")]
    rec = [_rec("S1", hostname="mac-1", model="MacBook", asset_tag="A100")]
    report = reconcile(obs, rec, now=NOW)
    assert report.counts()[OK] == 1
    assert report.counts()[CONFLICTING] == 0
    assert report.by_category(OK)[0].asset_tag == "A100"


def test_conflict_only_when_both_sides_have_values():
    # CMDB blank model is a backfill opportunity, not a conflict.
    obs = [_obs("S1", hostname="newname", model="MacBook")]
    rec = [_rec("S1", hostname="oldname", model=None)]
    report = reconcile(obs, rec, now=NOW)
    confs = report.by_category(CONFLICTING)
    assert len(confs) == 1
    assert "hostname" in confs[0].conflicts
    assert "model" not in confs[0].conflicts
    assert confs[0].conflicts["hostname"] == {"observed": "newname", "record": "oldname"}


def test_stale_when_record_only_and_aged_out():
    old = (NOW - timedelta(days=90)).isoformat()
    report = reconcile([], [_rec("S1", last_seen=old, asset_tag="A1")], stale_days=30, now=NOW)
    stale = report.by_category(STALE)
    assert len(stale) == 1
    assert stale[0].asset_tag == "A1"
    assert "90 days ago" in stale[0].detail


def test_record_only_but_recent_is_not_flagged():
    recent = (NOW - timedelta(days=5)).isoformat()
    report = reconcile([], [_rec("S1", last_seen=recent)], stale_days=30, now=NOW)
    assert report.counts()[STALE] == 0
    assert not report.drift


def test_duplicate_when_two_record_rows_share_a_serial():
    rec = [_rec("S1", asset_tag="A1"), _rec("S1", asset_tag="A2")]
    report = reconcile([_obs("S1")], rec, now=NOW)
    dups = report.by_category(DUPLICATE)
    assert len(dups) == 1
    assert "A1" in dups[0].asset_tag and "A2" in dups[0].asset_tag


def test_missing_confidence_rises_with_corroborating_sources():
    # A merged device records its contributing sources in extra["_sources"].
    merged = merge_devices(
        [_obs("S1", source="jamf"), _obs("S1", source="crowdstrike"), _obs("S1", source="intune")],
        ["jamf", "crowdstrike", "intune"],
    )
    one = reconcile([_obs("S1", source="jamf")], [], now=NOW).by_category(MISSING)[0]
    three = reconcile([merged], [], now=NOW).by_category(MISSING)[0]
    assert three.confidence > one.confidence
    assert three.observed_by == ["jamf", "crowdstrike", "intune"]


def test_stale_confidence_increases_with_age():
    near = reconcile([], [_rec("S1", last_seen=(NOW - timedelta(days=31)).isoformat())],
                     stale_days=30, now=NOW).by_category(STALE)[0]
    far = reconcile([], [_rec("S2", last_seen=(NOW - timedelta(days=400)).isoformat())],
                    stale_days=30, now=NOW).by_category(STALE)[0]
    assert far.confidence > near.confidence


def test_unknown_serials_are_ignored():
    report = reconcile([_obs("UNKNOWN")], [_rec("UNKNOWN")], now=NOW)
    assert report.findings == []


def test_negative_stale_days_rejected():
    with pytest.raises(ValueError):
        reconcile([], [], stale_days=-1, now=NOW)


def test_drift_orders_worst_first():
    obs = [_obs("MISS"), _obs("CONF", hostname="a")]
    rec = [
        _rec("CONF", hostname="b"),
        _rec("STALE1", last_seen=(NOW - timedelta(days=90)).isoformat()),
    ]
    report = reconcile(obs, rec, stale_days=30, now=NOW)
    categories = [f.category for f in report.drift]
    # missing outranks conflicting outranks stale
    assert categories.index(MISSING) < categories.index(CONFLICTING) < categories.index(STALE)


def test_to_dict_masks_serials_by_default():
    report = reconcile([_obs("ABCDEF123456")], [], now=NOW)
    d = report.to_dict()
    assert d["findings"][0]["serial"] == "****3456"
    raw = report.to_dict(mask=False)
    assert raw["findings"][0]["serial"] == "ABCDEF123456"


def test_render_text_masks_and_summarizes():
    obs = [_obs("ABCDEF123456")]
    report = reconcile(obs, [], now=NOW)
    out = render_text(report, color=False)
    assert "****3456" in out
    assert "ABCDEF123456" not in out
    assert "1 missing" in out


def test_render_text_clean_report():
    report = reconcile([_obs("S1", hostname="x")], [_rec("S1", hostname="x")], now=NOW)
    out = render_text(report, color=False)
    assert "No drift" in out


def test_mask_serial_helper():
    assert mask_serial("ABCDEF123456") == "****3456"
    assert mask_serial("AB") == "**"
    assert mask_serial("") == "UNKNOWN"
    assert mask_serial(None) == "UNKNOWN"

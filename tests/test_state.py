import os

from cairn.models import NormalizedDevice
from cairn.state import SyncState


def _dev(**kw):
    base = dict(serial="S1", source="jamf", hostname="h", os_name="macOS")
    base.update(kw)
    return NormalizedDevice(**base)


def test_hash_stable_and_sensitive(tmp_path):
    st = SyncState(path=str(tmp_path / "s.json"))
    h1 = st.device_hash(_dev())
    assert h1 == st.device_hash(_dev())  # stable
    assert h1 != st.device_hash(_dev(hostname="other"))  # sensitive to change


def test_last_seen_ignored_by_default(tmp_path):
    st = SyncState(path=str(tmp_path / "s.json"))
    # last_seen changing must NOT count as a change (avoids needless writes).
    assert st.device_hash(_dev(last_seen="t1")) == st.device_hash(_dev(last_seen="t2"))


def test_roundtrip_skip(tmp_path):
    p = str(tmp_path / "s.json")
    st = SyncState(path=p)
    d = _dev()
    assert st.is_unchanged(d) is False  # nothing recorded yet
    st.mark_synced(d)
    st.save()
    assert os.path.exists(p)
    # New instance loads prior state and now sees it as unchanged.
    st2 = SyncState(path=p)
    assert st2.is_unchanged(d) is True
    assert st2.is_unchanged(_dev(os_version="14.5")) is False


def test_disabled_state_never_skips(tmp_path):
    st = SyncState(path=str(tmp_path / "s.json"), enabled=False)
    d = _dev()
    st.mark_synced(d)
    assert st.is_unchanged(d) is False


def test_corrupt_state_starts_fresh(tmp_path):
    p = tmp_path / "s.json"
    p.write_text("{ not json")
    st = SyncState(path=str(p))
    assert st.is_unchanged(_dev()) is False  # didn't crash

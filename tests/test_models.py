from cairn.models import NormalizedDevice, merge_devices


def test_serial_normalized_upper_strip():
    d = NormalizedDevice(serial="  abc123 ", source="jamf")
    assert d.serial == "ABC123"


def test_unknown_serial():
    assert NormalizedDevice(serial="", source="x").serial == "UNKNOWN"
    assert NormalizedDevice(serial=None, source="x").serial == "UNKNOWN"


def test_mac_dedup_and_format():
    d = NormalizedDevice(
        serial="S1", source="x",
        mac_addresses=["aa-bb-cc-dd-ee-ff", "AA:BB:CC:DD:EE:FF", ""],
    )
    assert d.mac_addresses == ["AA:BB:CC:DD:EE:FF"]


def test_merge_priority_and_fill():
    jamf = NormalizedDevice(serial="S1", source="jamf", hostname="laptop",
                            os_name="macOS", model="MacBookPro18,3")
    crowd = NormalizedDevice(serial="S1", source="crowdstrike",
                             os_version="14.4.1", last_seen="2026-01-01",
                             mac_addresses=["11:22:33:44:55:66"])
    merged = merge_devices([crowd, jamf], source_priority=["jamf", "crowdstrike"])
    # jamf has priority -> its hostname/model win, empty fields filled from crowd
    assert merged.hostname == "laptop"
    assert merged.model == "MacBookPro18,3"
    assert merged.os_version == "14.4.1"
    assert merged.last_seen == "2026-01-01"
    assert merged.mac_addresses == ["11:22:33:44:55:66"]
    assert set(merged.extra["_sources"]) == {"jamf", "crowdstrike"}
    assert "jamf" in merged.source and "crowdstrike" in merged.source


def test_merge_unknown_source_sorts_last():
    a = NormalizedDevice(serial="S1", source="mystery", hostname="A")
    b = NormalizedDevice(serial="S1", source="jamf", hostname="B")
    merged = merge_devices([a, b], source_priority=["jamf"])
    assert merged.hostname == "B"  # jamf ranked above unknown

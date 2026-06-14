"""CMDB readers (GLPI, NetBox) so drift/reconciliation isn't Snipe-IT-only.

Each reads a CMDB into NormalizedDevice; the reconcile engine consumes the same
list regardless of backend. Upstream APIs are mocked with `responses`.
"""

import responses

from cairn.sources.glpi import GlpiSource
from cairn.sources.netbox import NetBoxSource


# --- GLPI ---------------------------------------------------------------
@responses.activate
def test_glpi_init_session_and_fetch():
    base = "https://glpi.example.com/apirest.php"
    responses.add(responses.GET, f"{base}/initSession",
                  json={"session_token": "sess-123"}, status=200)
    responses.add(
        responses.GET, f"{base}/Computer",
        json=[
            {
                "id": 7, "name": "PC-7", "serial": "SER-GLPI-7",
                "manufacturers_id": "Dell", "computermodels_id": "OptiPlex 7090",
                "operatingsystems_id": "Microsoft Windows 11 Pro",
                "date_mod": "2026-05-01 12:00:00",
            },
        ],
        status=200,
    )
    src = GlpiSource({"url": base, "app_token": "app", "user_token": "user"})
    devices = list(src.fetch_all())
    assert len(devices) == 1
    d = devices[0]
    assert d.serial == "SER-GLPI-7"
    assert d.source == "glpi"
    assert d.asset_tag == "7"  # GLPI id, so drift can point at the record
    assert d.manufacturer == "Dell"
    assert d.model == "OptiPlex 7090"
    assert d.os_name == "Windows"
    # initSession used the user_token header; Computer carried the session token.
    init_call = responses.calls[0].request
    assert init_call.headers["Authorization"] == "user_token user"
    assert init_call.headers["App-Token"] == "app"
    assert responses.calls[1].request.headers["Session-Token"] == "sess-123"


@responses.activate
def test_glpi_pagination_stops_on_short_page():
    base = "https://glpi.example.com/apirest.php"
    responses.add(responses.GET, f"{base}/initSession",
                  json={"session_token": "s"}, status=200)
    # One short page (< page_size) ends the loop after a single call.
    responses.add(responses.GET, f"{base}/Computer",
                  json=[{"id": 1, "name": "a", "serial": "X1"}], status=200)
    src = GlpiSource({"url": base, "app_token": "app", "user_token": "user",
                      "page_size": 200})
    devices = list(src.fetch_all())
    assert [d.serial for d in devices] == ["X1"]
    # initSession + exactly one Computer page.
    computer_calls = [c for c in responses.calls if c.request.url.startswith(f"{base}/Computer")]
    assert len(computer_calls) == 1


# --- NetBox -------------------------------------------------------------
@responses.activate
def test_netbox_fetch_flattens_nested_fields():
    base = "https://netbox.example.com"
    responses.add(
        responses.GET, f"{base}/api/dcim/devices/",
        json={
            "count": 1, "next": None, "previous": None,
            "results": [{
                "id": 42, "name": "sw-core-1", "serial": "SER-NB-42",
                "device_type": {"model": "EX4300", "manufacturer": {"name": "Juniper"}},
                "status": {"value": "active", "label": "Active"},
                "site": {"name": "HQ"},
                "primary_ip": {"address": "10.0.0.5/24"},
                "last_updated": "2026-05-02T08:00:00Z",
            }],
        },
        status=200,
    )
    src = NetBoxSource({"url": base, "token": "tok"})
    devices = list(src.fetch_all())
    assert len(devices) == 1
    d = devices[0]
    assert d.serial == "SER-NB-42"
    assert d.source == "netbox"
    assert d.manufacturer == "Juniper"
    assert d.model == "EX4300"
    assert d.asset_tag == "sw-core-1"
    assert d.extra["ip"] == "10.0.0.5"
    assert d.extra["status"] == "Active"
    assert d.extra["site"] == "HQ"
    assert responses.calls[0].request.headers["Authorization"] == "Token tok"


@responses.activate
def test_netbox_follows_next_url():
    base = "https://netbox.example.com"
    page2 = f"{base}/api/dcim/devices/?limit=200&offset=200"
    responses.add(
        responses.GET, f"{base}/api/dcim/devices/",
        json={"count": 2, "next": page2, "results": [
            {"id": 1, "name": "a", "serial": "A", "device_type": {}}]},
        status=200,
    )
    responses.add(
        responses.GET, page2,
        json={"count": 2, "next": None, "results": [
            {"id": 2, "name": "b", "serial": "B", "device_type": {}}]},
        status=200,
    )
    src = NetBoxSource({"url": base, "token": "tok"})
    serials = [d.serial for d in src.fetch_all()]
    assert serials == ["A", "B"]

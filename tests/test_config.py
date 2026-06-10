import os
import textwrap

import pytest

from cairn.config import ConfigError, enabled_items, load_config, normalize


def _write(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(textwrap.dedent(content))
    os.chmod(p, 0o600)
    return p


def test_load_yaml(tmp_path):
    _write(tmp_path, "config.yaml", """
        mode: fleet
        sources:
          jamf:
            enabled: true
            url: https://jamf.example.com
            client_id: a
            client_secret: b
        sinks:
          snipeit:
            url: https://snipe.example.com/api/v1
            token: t
    """)
    cfg = load_config(search_dir=str(tmp_path))
    assert cfg["mode"] == "fleet"
    assert "jamf" in enabled_items(cfg, "sources")
    assert "snipeit" in enabled_items(cfg, "sinks")


def test_disabled_source_excluded(tmp_path):
    _write(tmp_path, "config.yaml", """
        sources:
          jamf:
            enabled: false
            url: https://jamf.example.com
    """)
    cfg = load_config(search_dir=str(tmp_path))
    assert "jamf" not in enabled_items(cfg, "sources")


def test_env_override_generic(tmp_path, monkeypatch):
    _write(tmp_path, "config.yaml", """
        sinks:
          snipeit:
            url: https://snipe.example.com/api/v1
            token: PLACEHOLDER
    """)
    monkeypatch.setenv("CAIRN_sinks__snipeit__token", "real-secret")
    cfg = load_config(search_dir=str(tmp_path))
    assert cfg["sinks"]["snipeit"]["token"] == "real-secret"


def test_legacy_env_maps_in(tmp_path, monkeypatch):
    monkeypatch.setenv("GHOST_SNIPE_URL", "https://snipe.example.com/api/v1")
    monkeypatch.setenv("GHOST_SNIPE_TOKEN", "tok")
    cfg = load_config(search_dir=str(tmp_path))  # no file present
    assert cfg["sinks"]["snipeit"]["url"] == "https://snipe.example.com/api/v1"
    assert cfg["sinks"]["snipeit"]["token"] == "tok"


def test_legacy_ini_backcompat(tmp_path):
    _write(tmp_path, "settings.conf", """
        [DEFAULT]
        snipe_url = https://snipe.example.com/api/v1
        snipe_token = tok
        jamf_url = https://jamf.example.com
        jamf_user = u
        jamf_password = p
        site_id = 3
        company_id = 4
        teams_webhook_url = https://outlook.office.com/webhook/x
    """)
    cfg = load_config(search_dir=str(tmp_path))
    assert cfg["mode"] == "agent"
    assert cfg["sources"]["jamf"]["url"] == "https://jamf.example.com"
    assert cfg["sinks"]["snipeit"]["token"] == "tok"
    assert cfg["defaults"]["site_id"] == 3
    assert "teams" in cfg["notifiers"]


def test_world_readable_rejected(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("mode: fleet\n")
    os.chmod(p, 0o644)
    if os.name != "nt":
        with pytest.raises(ConfigError):
            load_config(search_dir=str(tmp_path))


def test_bad_mode_rejected():
    with pytest.raises(ConfigError):
        normalize({"mode": "bogus"})

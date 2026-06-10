"""Tests for the UX layer: provider metadata, secrets, health, web helpers."""

import os
import textwrap

import pytest

from cairn import secrets, web, wizard
from cairn.provider_meta import all_meta, get_meta


# --- provider_meta ------------------------------------------------------
def test_meta_covers_every_registered_provider():
    from cairn.registry import available_sources, available_sinks, available_notifiers
    meta = all_meta()
    for key in available_sources():
        assert key in meta["sources"], f"missing meta for source {key}"
    for key in available_sinks():
        assert key in meta["sinks"]
    for key in available_notifiers():
        assert key in meta["notifiers"]


def test_snipeit_meta_marks_token_secret():
    m = get_meta("sinks", "snipeit")
    token = next(f for f in m.fields if f.key == "token")
    assert token.secret is True and token.required is True


# --- secrets ------------------------------------------------------------
def test_resolve_secrets_replaces_keyring_refs(monkeypatch):
    monkeypatch.setattr(secrets, "get_secret", lambda name: f"SECRET[{name}]")
    tree = {"sinks": {"snipeit": {"token": "keyring:snipe-tok", "url": "https://x"}}}
    out = secrets.resolve_secrets(tree)
    assert out["sinks"]["snipeit"]["token"] == "SECRET[snipe-tok]"
    assert out["sinks"]["snipeit"]["url"] == "https://x"  # untouched


def test_resolve_secrets_noop_without_refs():
    tree = {"a": ["b", {"c": "plain"}]}
    assert secrets.resolve_secrets(tree) == tree


# --- wizard helpers -----------------------------------------------------
def test_wizard_coerce_ints():
    assert wizard._coerce_ints({"company_id": "3", "url": "x"})["company_id"] == 3


def test_wizard_store_secrets_uses_keyring(monkeypatch):
    stored = {}
    monkeypatch.setattr(secrets, "set_secret", lambda n, v: stored.__setitem__(n, v))
    meta = get_meta("sinks", "snipeit")
    out = wizard._store_secrets("sinks", "snipeit", {"token": "abc", "url": "https://x"}, meta, True)
    assert out["token"] == "keyring:sinks-snipeit-token"
    assert stored["sinks-snipeit-token"] == "abc"
    assert out["url"] == "https://x"  # non-secret stays inline


def test_wizard_store_secrets_inline_when_no_keyring():
    meta = get_meta("sinks", "snipeit")
    out = wizard._store_secrets("sinks", "snipeit", {"token": "abc"}, meta, False)
    assert out["token"] == "abc"


# --- web helpers --------------------------------------------------------
def test_web_masks_secret_values():
    masked = web._mask_config({"sinks": {"snipeit": {"token": "supersecret", "url": "https://x"}}},
                              web._secret_keys())
    assert masked["sinks"]["snipeit"]["token"] == "********"
    assert masked["sinks"]["snipeit"]["url"] == "https://x"


def test_web_state_reads_config(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent("""
        mode: fleet
        sinks:
          snipeit:
            url: https://snipe.example.com/api/v1
            token: TOPSECRET
    """))
    os.chmod(p, 0o600)
    state = web._api_state(str(p))
    assert state["exists"] is True
    # token must be masked in the state payload
    assert state["config"]["sinks"]["snipeit"]["token"] == "********"
    assert "snipeit" in state["enabled"]["sinks"]


def test_web_test_endpoint_handles_unknown_provider():
    # Should never raise; returns ok=False for a bogus provider.
    result = web._api_test({"section": "sources", "key": "does-not-exist", "config": {}})
    assert result["ok"] is False

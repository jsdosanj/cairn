"""Configuration loading: YAML + environment overrides + legacy .ini back-compat.

Precedence (highest wins):
  1. Environment variables (CAIRN_* nested, plus legacy GHOST_*/TEAMS_* vars)
  2. config.yaml / config.yml
  3. legacy settings.conf (only if no YAML is found)

Secrets should live in env vars in production; the YAML is for structure and
non-secret defaults. Every secret-bearing key can be supplied via env.
"""

from __future__ import annotations

import configparser
import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None

CONFIG_CANDIDATES = ("config.yaml", "config.yml")
LEGACY_INI = "settings.conf"

# Legacy env vars from the original GhostAssetSync, mapped into the new tree.
_LEGACY_ENV_MAP = {
    "GHOST_JAMF_URL": ("sources", "jamf", "url"),
    "GHOST_JAMF_USER": ("sources", "jamf", "username"),
    "GHOST_JAMF_PASSWORD": ("sources", "jamf", "password"),
    "GHOST_SNIPE_URL": ("sinks", "snipeit", "url"),
    "GHOST_SNIPE_TOKEN": ("sinks", "snipeit", "token"),
    "TEAMS_WEBHOOK_URL": ("notifiers", "teams", "webhook_url"),
}


class ConfigError(Exception):
    pass


def _deep_set(tree: dict, path: tuple[str, ...], value: Any) -> None:
    node = tree
    for key in path[:-1]:
        node = node.setdefault(key, {})
        if not isinstance(node, dict):
            raise ConfigError(f"Config path conflict at {'.'.join(path)}")
    node[path[-1]] = value


def find_config(explicit: Optional[str] = None, search_dir: Optional[str] = None) -> Optional[str]:
    if explicit:
        if not os.path.isfile(explicit):
            raise ConfigError(f"Config file not found: {explicit}")
        return explicit
    base = search_dir or os.getcwd()
    for name in (*CONFIG_CANDIDATES, LEGACY_INI):
        candidate = os.path.join(base, name)
        if os.path.isfile(candidate):
            return candidate
    return None


def _check_perms(path: str) -> None:
    """Refuse a world-readable config; credentials may live in it."""
    if os.name == "nt":
        return
    import stat

    mode = os.stat(path).st_mode
    if mode & stat.S_IROTH:
        raise ConfigError(
            f"{path} is world-readable. Run: chmod 600 {os.path.basename(path)}"
        )
    if mode & stat.S_IRGRP:
        logger.warning("%s is group-readable. Consider chmod 600.", path)


def _load_yaml(path: str) -> dict:
    if yaml is None:
        raise ConfigError("PyYAML is required to read YAML config. pip install pyyaml")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ConfigError("Top-level config must be a mapping")
    return data


def _load_legacy_ini(path: str) -> dict:
    """Translate the original flat settings.conf into the new structure."""
    parser = configparser.ConfigParser()
    parser.read(path)
    c = parser["DEFAULT"]
    tree: dict[str, Any] = {
        "mode": "agent",  # the original tool was an on-device agent
        "sources": {},
        "sinks": {},
        "notifiers": {},
        "defaults": {},
    }
    if c.get("jamf_url"):
        tree["sources"]["jamf"] = {
            "enabled": True,
            "url": c.get("jamf_url"),
            "username": c.get("jamf_user"),
            "password": c.get("jamf_password"),
        }
    if c.get("snipe_url"):
        tree["sinks"]["snipeit"] = {
            "enabled": True,
            "url": c.get("snipe_url"),
            "token": c.get("snipe_token"),
        }
    if c.get("teams_webhook_url"):
        tree["notifiers"]["teams"] = {
            "enabled": True,
            "webhook_url": c.get("teams_webhook_url"),
        }
    tree["defaults"] = {
        "site_id": int(c.get("site_id", 1)),
        "company_id": int(c.get("company_id", 1)),
    }
    logger.info("Loaded legacy settings.conf and translated to Cairn config schema.")
    return tree


def _apply_env_overrides(tree: dict) -> None:
    # Legacy explicit vars first.
    for env_key, path in _LEGACY_ENV_MAP.items():
        val = os.environ.get(env_key)
        if val:
            _deep_set(tree, path, val)
            # Anything overridden by env should be considered enabled.
            _deep_set(tree, (path[0], path[1], "enabled"), True)
    # Generic nested form: CAIRN_sources__jamf__client_secret=...
    for env_key, val in os.environ.items():
        if not env_key.startswith("CAIRN_"):
            continue
        remainder = env_key[len("CAIRN_"):]
        parts = tuple(p for p in remainder.split("__") if p)
        if not parts:
            continue
        # Lowercase section/provider names, keep leaf key as-is (lowercased).
        path = tuple(p.lower() for p in parts)
        _deep_set(tree, path, val)


def normalize(tree: dict) -> dict:
    tree.setdefault("mode", "fleet")
    tree.setdefault("sources", {})
    tree.setdefault("sinks", {})
    tree.setdefault("notifiers", {})
    tree.setdefault("defaults", {})
    tree.setdefault(
        "source_priority",
        ["intune", "jamf", "kandji", "jumpcloud", "google_workspace",
         "crowdstrike", "sophos", "defender"],
    )
    if tree["mode"] not in ("agent", "fleet"):
        raise ConfigError("mode must be 'agent' or 'fleet'")
    return tree


def load_config(explicit: Optional[str] = None, search_dir: Optional[str] = None) -> dict:
    path = find_config(explicit, search_dir)
    if path:
        _check_perms(path)
        if path.endswith((".yaml", ".yml")):
            tree = _load_yaml(path)
        else:
            tree = _load_legacy_ini(path)
        logger.info("Loaded config from %s", path)
    else:
        logger.info("No config file found; relying entirely on environment variables.")
        tree = {}
    _apply_env_overrides(tree)
    tree = normalize(tree)
    # Resolve any `keyring:NAME` references against the OS keychain (no-op unless
    # such references exist).
    from .secrets import resolve_secrets

    return resolve_secrets(tree)


def enabled_items(tree: dict, section: str) -> dict[str, dict]:
    """Return {key: merged_config} for enabled entries in a section.

    An entry is enabled when its config has enabled != false. The merged config
    includes the top-level `defaults` block for convenience.
    """
    out: dict[str, dict] = {}
    for key, cfg in (tree.get(section) or {}).items():
        cfg = cfg or {}
        if cfg.get("enabled", True) is False:
            continue
        merged = {"_defaults": tree.get("defaults", {})}
        merged.update(cfg)
        out[key] = merged
    return out

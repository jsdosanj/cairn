"""`cairn setup` — an interactive wizard for non-technical users.

Walks through Snipe-IT + each integration with plain-language prompts, tests the
connection live, optionally stores secrets in the OS keychain, and writes a
ready-to-run config.yaml. No YAML editing required.

Pure stdlib (input/getpass) so it works everywhere, including the frozen binary.
"""

from __future__ import annotations

import getpass
import os
from typing import Optional

import yaml

from . import health, secrets
from .provider_meta import NOTIFIERS, SINKS, SOURCES, ProviderMeta
from .registry import get_sink_class, get_source_class


def _ask(prompt: str, default: Optional[str] = None) -> str:
    suffix = f" [{default}]" if default else ""
    val = input(f"  {prompt}{suffix}: ").strip()
    return val or (default or "")


def _ask_yes(prompt: str, default: bool = True) -> bool:
    d = "Y/n" if default else "y/N"
    val = input(f"  {prompt} [{d}]: ").strip().lower()
    if not val:
        return default
    return val.startswith("y")


def _collect(meta: ProviderMeta) -> dict:
    """Prompt for a provider's fields; return {key: value} for those filled in."""
    print(f"\n  -- {meta.display}: {meta.blurb}")
    if meta.note:
        print(f"     note: {meta.note}")
    cfg: dict = {}
    for f in meta.fields:
        label = f.label + (" (required)" if f.required else "")
        if f.help:
            label += f" — {f.help}"
        if f.secret:
            val = getpass.getpass(f"  {label}: ").strip()
        else:
            val = _ask(label, f.default)
        if val:
            cfg[f.key] = val
    return cfg


def _coerce_ints(cfg: dict, int_keys=("company_id", "site_id", "status_id")) -> dict:
    for k in int_keys:
        if k in cfg:
            try:
                cfg[k] = int(cfg[k])
            except (TypeError, ValueError):
                pass
    return cfg


def _test(section: str, key: str, cfg: dict) -> bool:
    print("     testing connection...", end=" ", flush=True)
    try:
        if section == "sources":
            obj = get_source_class(key)(cfg)
            ok, msg = health.probe_source(obj)
        else:
            obj = get_sink_class(key)(cfg)
            ok, msg = health.probe_sink(obj)
    except Exception as e:  # noqa: BLE001
        ok, msg = False, str(e)[:200]
    print("OK" if ok else f"FAILED ({msg})")
    return ok


def _store_secrets(section: str, key: str, cfg: dict, meta: ProviderMeta, use_keyring: bool) -> dict:
    """Replace secret values with keyring: references when keychain is in use."""
    if not use_keyring:
        return cfg
    secret_keys = {f.key for f in meta.fields if f.secret}
    out = dict(cfg)
    for k in list(out):
        if k in secret_keys and isinstance(out[k], str) and not out[k].startswith("keyring:"):
            name = f"{section}-{key}-{k}"
            secrets.set_secret(name, out[k])
            out[k] = f"keyring:{name}"
    return out


def run_setup(config_path: str = "config.yaml") -> int:
    print("\n=== Cairn setup ===")
    print("Let's connect your tools to Snipe-IT. Press Enter to skip optional fields.\n")

    if os.path.exists(config_path):
        if not _ask_yes(f"{config_path} already exists. Overwrite it?", default=False):
            print("Cancelled. Nothing was changed.")
            return 1

    use_keyring = False
    if secrets.keyring_available():
        use_keyring = _ask_yes("Store secrets in your OS keychain (recommended)?", True)
    else:
        print("  (OS keychain not available; secrets will be written into the config "
              "file — chmod 600 it, or use environment variables.)")

    tree: dict = {
        "mode": "fleet",
        "defaults": {"status_id": 2, "company_id": 1, "site_id": 1},
        "incremental": True,
        "sources": {},
        "sinks": {},
        "notifiers": {},
    }

    # --- Snipe-IT (required sink) ---------------------------------------
    print("\nStep 1 — your Snipe-IT (the system of record):")
    sink_meta = SINKS["snipeit"]
    while True:
        cfg = _coerce_ints(_collect(sink_meta))
        if _test("sinks", "snipeit", cfg) or _ask_yes("Connection failed. Keep it anyway?", False):
            break
        print("  Let's try again.")
    cfg["enabled"] = True
    tree["sinks"]["snipeit"] = _store_secrets("sinks", "snipeit", cfg, sink_meta, use_keyring)

    # --- Sources --------------------------------------------------------
    print("\nStep 2 — the tools to pull devices from:")
    remaining = dict(SOURCES)
    while remaining:
        keys = list(remaining)
        print("\n  Available:", ", ".join(keys))
        choice = _ask("Add which source? (name, or blank to finish)").lower()
        if not choice:
            break
        if choice not in remaining:
            print(f"  '{choice}' isn't a source. Pick from: {', '.join(keys)}")
            continue
        meta = remaining.pop(choice)
        cfg = _collect(meta)
        if not _test("sources", choice, cfg) and not _ask_yes("Connection failed. Keep it anyway?", False):
            print(f"  Skipped {meta.display}.")
            continue
        cfg["enabled"] = True
        tree["sources"][choice] = _store_secrets("sources", choice, cfg, meta, use_keyring)
        print(f"  Added {meta.display}.")

    # --- Notifier (optional) -------------------------------------------
    if _ask_yes("\nStep 3 — send run summaries to chat? (optional)", False):
        print("  Available:", ", ".join(NOTIFIERS))
        choice = _ask("Which notifier? (name, or blank to skip)").lower()
        if choice in NOTIFIERS:
            meta = NOTIFIERS[choice]
            cfg = _collect(meta)
            cfg["enabled"] = True
            tree["notifiers"][choice] = _store_secrets("notifiers", choice, cfg, meta, use_keyring)

    # --- Schedule (optional) -------------------------------------------
    if _ask_yes("\nStep 4 — run automatically on a schedule? (optional)", False):
        hours = _ask("Every how many hours?", "1")
        try:
            tree["schedule"] = {"interval": max(60, int(float(hours) * 3600))}
        except ValueError:
            tree["schedule"] = {"interval": 3600}

    # --- Write ----------------------------------------------------------
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(tree, f, sort_keys=False, default_flow_style=False)
    if os.name != "nt":
        os.chmod(config_path, 0o600)

    print(f"\nDone. Wrote {config_path}.")
    print("Next steps:")
    print(f"  cairn -c {config_path} sync --dry-run     # preview")
    print(f"  cairn -c {config_path} sync               # run it")
    if tree.get("schedule"):
        print(f"  cairn -c {config_path} schedule install   # turn on auto-sync")
    return 0

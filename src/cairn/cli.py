"""Cairn command-line interface.

  cairn sync            run a sync (agent or fleet per config)
  cairn sync --dry-run  show what would change, write nothing
  cairn validate        load config + initialize providers, report readiness
  cairn list-providers  show available sources/sinks/notifiers
"""

from __future__ import annotations

import argparse
import logging
import sys

from .config import ConfigError, enabled_items, load_config
from .registry import available_notifiers, available_sinks, available_sources

logger = logging.getLogger("cairn")


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


def _cmd_list_providers(_args) -> int:
    print("Sources:   ", ", ".join(available_sources()))
    print("Sinks:     ", ", ".join(available_sinks()))
    print("Notifiers: ", ", ".join(available_notifiers()))
    return 0


def _cmd_validate(args) -> int:
    config = load_config(args.config)
    print(f"mode: {config.get('mode')}")
    for section in ("sources", "sinks", "notifiers"):
        items = enabled_items(config, section)
        print(f"{section}: {', '.join(items) or '(none enabled)'}")
    # Try to construct everything; this surfaces missing-credential errors early.
    from .orchestrator import Orchestrator

    try:
        orch = Orchestrator(config)
    except Exception as e:  # noqa: BLE001
        print(f"\nVALIDATION FAILED: {e}", file=sys.stderr)
        return 1
    print(f"\nReady: {len(orch.sources)} source(s), {len(orch.sinks)} sink(s), "
          f"{len(orch.notifiers)} notifier(s).")
    return 0


def _cmd_sync(args) -> int:
    config = load_config(args.config)
    if args.mode:
        config["mode"] = args.mode
    from .orchestrator import Orchestrator

    orch = Orchestrator(config)
    summary = orch.run(dry_run=args.dry_run)
    print(summary.as_text())
    return 1 if summary.failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cairn", description="Cairn device asset sync")
    parser.add_argument("-c", "--config", help="path to config.yaml (default: auto-discover)")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = parser.add_subparsers(dest="command")

    p_sync = sub.add_parser("sync", help="run a sync")
    p_sync.add_argument("--dry-run", action="store_true", help="report changes, write nothing")
    p_sync.add_argument("--mode", choices=["agent", "fleet"], help="override config mode")
    p_sync.set_defaults(func=_cmd_sync)

    sub.add_parser("validate", help="check config + providers").set_defaults(func=_cmd_validate)
    sub.add_parser("list-providers", help="list available plugins").set_defaults(func=_cmd_list_providers)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(getattr(args, "verbose", False))
    if not getattr(args, "command", None):
        # Back-compat: bare invocation behaves like `sync`.
        args.func = _cmd_sync
        args.dry_run = False
        args.mode = None
    try:
        return args.func(args)
    except ConfigError as e:
        logger.error("Config error: %s", e)
        return 2
    except KeyboardInterrupt:
        return 130
    except Exception as e:  # noqa: BLE001
        logger.exception("Unexpected failure: %s", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())

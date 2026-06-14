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

from . import __version__
from .config import ConfigError, enabled_items, load_config
from .registry import (
    available_notifiers,
    available_sinks,
    available_sources,
    available_writebacks,
)

logger = logging.getLogger("cairn")

STARTER_CONFIG = """\
# Cairn configuration. chmod 600 this file; prefer env vars for secrets.
# Full reference: https://github.com/jsdosanj/cairn/blob/main/config.example.yaml
mode: fleet
source_priority: [intune, jamf, jumpcloud, crowdstrike, sophos, defender]

defaults:
  status_id: 2
  company_id: 1
  site_id: 1

incremental: true
schedule:
  interval: 3600

sources:
  jamf:
    enabled: false
    url: https://your.jamf.instance.com
    client_id: ...
    client_secret: ...

sinks:
  snipeit:
    enabled: true
    url: https://your-snipe-it/api/v1
    token: ...

notifiers:
  slack:
    enabled: false
    webhook_url: https://hooks.slack.com/services/XXX/YYY/ZZZ
"""


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


def _cmd_init(_args) -> int:
    # Print a starter config to stdout so `cairn init > cairn.yaml` works.
    print(STARTER_CONFIG, end="")
    return 0


def _cmd_setup(args) -> int:
    from .wizard import run_setup

    return run_setup(args.config or "config.yaml")


def _cmd_doctor(args) -> int:
    from . import health

    config = load_config(args.config)
    results = health.check_config(config)
    if not results:
        print("No sources or sinks enabled. Run `cairn setup` first.")
        return 1
    for r in results:
        mark = "OK  " if r.ok else "FAIL"
        print(f"[{mark}] {r.section[:-1]}:{r.key} — {r.message}")
    failed = [r for r in results if not r.ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} healthy.")
    return 1 if failed else 0


def _cmd_web(args) -> int:
    from .web import serve

    return serve(host=args.host, port=args.port, config_path=args.config or "config.yaml")


def _cmd_list_providers(_args) -> int:
    print("Sources:   ", ", ".join(available_sources()))
    print("Sinks:     ", ", ".join(available_sinks()))
    print("Notifiers: ", ", ".join(available_notifiers()))
    print("Writebacks:", ", ".join(available_writebacks()))
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
    summary = orch.run(dry_run=args.dry_run, full=getattr(args, "full", False))
    print(summary.as_text())
    return 1 if summary.failed else 0


def _cmd_writeback(args) -> int:
    config = load_config(args.config)
    from .orchestrator import Orchestrator

    orch = Orchestrator(config)
    dry = not args.apply
    summary = orch.run_writeback(dry_run=dry)
    print(summary.as_text())
    if dry:
        print("\n(dry-run — nothing was written. Re-run with --apply to write to your MDM.)")
    return 1 if summary.failed else 0


def _cmd_drift(args) -> int:
    if args.stale_days < 0:
        print("error: --stale-days must be >= 0", file=sys.stderr)
        return 2
    config = load_config(args.config)
    from .orchestrator import Orchestrator
    from .reconcile import render_text

    orch = Orchestrator(config)
    report = orch.run_drift(stale_days=args.stale_days)

    if args.json:
        import json

        text = json.dumps(report.to_dict(mask=not args.show_serials), indent=2)
    else:
        text = render_text(
            report,
            color=sys.stdout.isatty() and not args.no_color,
            mask=not args.show_serials,
        )

    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"drift report written to {args.output}")
    else:
        print(text)

    # Exit non-zero when there is drift, so CI/cron can alert on it.
    drift_total = sum(v for k, v in report.counts().items() if k != "ok")
    return 1 if drift_total else 0


def _cmd_schedule(args) -> int:
    from . import scheduler

    if args.action == "install":
        interval = args.interval
        if interval is None:
            cfg = load_config(args.config)
            interval = int((cfg.get("schedule") or {}).get("interval", 3600))
        command = "drift" if getattr(args, "drift", False) else "sync"
        print(scheduler.install(interval, args.config, args.mode, command))
    elif args.action == "uninstall":
        print(scheduler.uninstall())
    else:  # status
        print(scheduler.status())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cairn", description="Cairn device asset sync")
    parser.add_argument("--version", action="version", version=f"cairn {__version__}")
    parser.add_argument("-c", "--config", help="path to config.yaml (default: auto-discover)")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = parser.add_subparsers(dest="command")

    p_sync = sub.add_parser("sync", help="run a sync")
    p_sync.add_argument("--dry-run", action="store_true", help="report changes, write nothing")
    p_sync.add_argument("--full", action="store_true",
                        help="ignore incremental state; re-sync every device")
    p_sync.add_argument("--mode", choices=["agent", "fleet"], help="override config mode")
    p_sync.set_defaults(func=_cmd_sync)

    p_wb = sub.add_parser("writeback", help="push Snipe-IT asset tags back to your MDM (Jamf/Intune)")
    p_wb.add_argument("--apply", action="store_true",
                      help="actually write to the MDM (default is a dry-run preview)")
    p_wb.set_defaults(func=_cmd_writeback)

    p_drift = sub.add_parser(
        "drift",
        help="reconcile sources vs Snipe-IT: what's missing, stale, duplicate, or conflicting",
    )
    p_drift.add_argument("--stale-days", type=int, default=30,
                         help="flag CMDB assets no source has seen in N days (default 30)")
    p_drift.add_argument("--json", action="store_true", help="emit the report as JSON")
    p_drift.add_argument("--output", "-o", help="write the report to a file instead of stdout")
    p_drift.add_argument("--show-serials", action="store_true",
                         help="print full serials (default masks to last 4)")
    p_drift.add_argument("--no-color", action="store_true", help="disable ANSI color")
    p_drift.set_defaults(func=_cmd_drift)

    p_sched = sub.add_parser("schedule", help="install/remove a native scheduled sync")
    p_sched.add_argument("action", choices=["install", "uninstall", "status"])
    p_sched.add_argument("--interval", type=int,
                         help="seconds between runs (default: config schedule.interval or 3600)")
    p_sched.add_argument("--mode", choices=["agent", "fleet"], help="mode for the scheduled run")
    p_sched.add_argument("--drift", action="store_true",
                         help="schedule a read-only drift-digest run instead of a sync "
                              "(notifiers deliver the missing/stale/conflicting digest)")
    p_sched.set_defaults(func=_cmd_schedule)

    sub.add_parser("setup", help="interactive setup wizard (recommended for first run)").set_defaults(func=_cmd_setup)
    sub.add_parser("doctor", help="test every configured connection").set_defaults(func=_cmd_doctor)

    p_web = sub.add_parser("web", help="launch the local dashboard in your browser")
    p_web.add_argument("--host", default="127.0.0.1", help="bind host (default 127.0.0.1)")
    p_web.add_argument("--port", type=int, default=8765, help="bind port (default 8765)")
    p_web.set_defaults(func=_cmd_web)

    sub.add_parser("init", help="print a starter config (e.g. cairn init > cairn.yaml)").set_defaults(func=_cmd_init)
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

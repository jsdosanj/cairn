"""The engine: pull from sources, reconcile by serial, push to sinks, notify.

Two modes:
  * agent  — runs on one endpoint; syncs only the machine it runs on. Collects
             local facts, asks each source about that one serial, merges, writes.
  * fleet  — runs centrally; pulls every device from every enabled source,
             reconciles records that share a serial, writes the whole fleet.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from . import system_info
from .config import enabled_items
from .models import NormalizedDevice, mask_serial, merge_devices
from .registry import (
    get_notifier_class,
    get_sink_class,
    get_source_class,
    get_writeback_class,
)
from .sinks.base import SyncResult
from .state import SyncState

logger = logging.getLogger(__name__)


@dataclass
class RunSummary:
    mode: str
    dry_run: bool
    devices_seen: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    source_errors: dict[str, str] = field(default_factory=dict)
    results: list[SyncResult] = field(default_factory=list)

    def record(self, result: SyncResult) -> None:
        self.results.append(result)
        if result.action == SyncResult.CREATED:
            self.created += 1
        elif result.action == SyncResult.UPDATED:
            self.updated += 1
        elif result.action == SyncResult.SKIPPED:
            self.skipped += 1
        elif result.action == SyncResult.FAILED:
            self.failed += 1

    def as_text(self) -> str:
        lines = [
            f"Cairn {self.mode} run{' (dry-run)' if self.dry_run else ''}",
            f"  devices reconciled: {self.devices_seen}",
            f"  created: {self.created}  updated: {self.updated}  "
            f"skipped: {self.skipped}  failed: {self.failed}",
        ]
        if self.source_errors:
            lines.append("  source errors:")
            for src, err in self.source_errors.items():
                lines.append(f"    - {src}: {err}")
        return "\n".join(lines)


@dataclass
class WritebackSummary:
    dry_run: bool
    assets_read: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    per_target: dict[str, dict[str, int]] = field(default_factory=dict)
    results: list = field(default_factory=list)

    def record(self, target: str, result) -> None:
        self.results.append((target, result))
        bucket = self.per_target.setdefault(target, {"updated": 0, "skipped": 0, "failed": 0})
        bucket[result.action] = bucket.get(result.action, 0) + 1
        setattr(self, result.action, getattr(self, result.action) + 1)

    def as_text(self) -> str:
        lines = [
            f"Cairn writeback{' (dry-run)' if self.dry_run else ''}",
            f"  Snipe-IT assets read: {self.assets_read}",
            f"  updated: {self.updated}  skipped: {self.skipped}  failed: {self.failed}",
        ]
        for target, b in self.per_target.items():
            lines.append(f"    {target}: updated {b.get('updated',0)}, "
                         f"skipped {b.get('skipped',0)}, failed {b.get('failed',0)}")
        return "\n".join(lines)


class Orchestrator:
    def __init__(self, config: dict):
        self.config = config
        self.mode = config.get("mode", "fleet")
        self.source_priority = config.get("source_priority", [])
        self.sources = self._build(get_source_class, "sources")
        self.sinks = self._build(get_sink_class, "sinks")
        self.notifiers = self._build(get_notifier_class, "notifiers")
        if not self.sources:
            logger.warning("No sources enabled.")
        if not self.sinks:
            raise ValueError("No sinks enabled — nothing to sync into.")
        self.state = SyncState(
            path=config.get("state_path"),
            enabled=config.get("incremental", True) is not False,
            ignore_fields=config.get("incremental_ignore_fields"),
        )

    def _build(self, getter, section: str) -> dict:
        built = {}
        for key, cfg in enabled_items(self.config, section).items():
            try:
                built[key] = getter(key)(cfg)
                logger.info("Enabled %s: %s", section[:-1], key)
            except Exception as e:  # noqa: BLE001 - a broken provider shouldn't kill the run
                logger.error("Failed to initialize %s '%s': %s", section[:-1], key, e)
        return built

    # --- public entrypoint ----------------------------------------------
    def run(self, dry_run: bool = False, full: bool = False) -> RunSummary:
        """Run a sync. `full=True` ignores incremental state (re-sync everything)."""
        summary = RunSummary(mode=self.mode, dry_run=dry_run)
        devices = (
            self._collect_fleet(summary)
            if self.mode == "fleet"
            else self._collect_agent(summary)
        )
        summary.devices_seen = len(devices)
        for device in devices:
            # Incremental skip: unchanged device since last successful sync.
            if not full and self.state.is_unchanged(device):
                summary.record(SyncResult(SyncResult.SKIPPED, device.serial, "", "unchanged"))
                continue
            ok = True
            for sink in self.sinks.values():
                result = sink.upsert(device, dry_run=dry_run)
                summary.record(result)
                if result.action == SyncResult.FAILED:
                    ok = False
                    logger.error("sink %s failed for %s: %s", sink.key, result.serial, result.detail)
            # Only remember a device as synced when every sink accepted it and we
            # actually wrote (never in dry-run), so failures retry next run.
            if ok and not dry_run:
                self.state.mark_synced(device)
        if not dry_run:
            self.state.save()
        self._notify(summary)
        return summary

    # --- collection ------------------------------------------------------
    def _collect_fleet(self, summary: RunSummary) -> list[NormalizedDevice]:
        by_serial: dict[str, list[NormalizedDevice]] = defaultdict(list)
        unkeyed: list[NormalizedDevice] = []
        for key, source in self.sources.items():
            try:
                count = 0
                for device in source.fetch_all():
                    count += 1
                    if device.serial and device.serial != "UNKNOWN":
                        by_serial[device.serial].append(device)
                    else:
                        # No serial (e.g. some Defender/Sophos records): keep, but
                        # can't reconcile by serial. Write as-is.
                        unkeyed.append(device)
                logger.info("source %s returned %d devices", key, count)
            except Exception as e:  # noqa: BLE001
                logger.error("source %s failed: %s", key, e)
                summary.source_errors[key] = str(e)
        merged = [merge_devices(group, self.source_priority) for group in by_serial.values()]
        return merged + unkeyed

    def _collect_agent(self, summary: RunSummary) -> list[NormalizedDevice]:
        local = system_info.collect_local_device()
        serial = local.serial
        logger.info("Agent mode: local serial %s", mask_serial(serial))
        records = [local]
        for key, source in self.sources.items():
            try:
                found = source.find_by_serial(serial)
                if found:
                    records.append(found)
                    logger.info("source %s matched local device", key)
            except Exception as e:  # noqa: BLE001
                logger.error("source %s lookup failed: %s", key, e)
                summary.source_errors[key] = str(e)
        if serial == "UNKNOWN" and len(records) == 1:
            logger.warning("Local serial unknown and no source match; syncing local facts only.")
        return [merge_devices(records, ["local"] + self.source_priority)]

    # --- notify ----------------------------------------------------------
    def _notify(self, summary: RunSummary) -> None:
        if not self.notifiers:
            return
        level = "error" if summary.failed else ("warning" if summary.source_errors else "success")
        title = f"Cairn sync: {summary.created} created, {summary.updated} updated"
        if summary.failed:
            title += f", {summary.failed} failed"
        for notifier in self.notifiers.values():
            try:
                notifier.notify(title, summary.as_text(), level=level)
            except Exception as e:  # noqa: BLE001 - notifications are best-effort
                logger.error("notifier %s failed: %s", notifier.key, e)

    # --- writeback (Snipe-IT -> MDM) ------------------------------------
    def run_writeback(self, dry_run: bool = True, full: bool = False) -> WritebackSummary:
        """Read assets from Snipe-IT and push asset tags back into the MDMs.

        dry_run defaults to True: writeback mutates systems you may not own, so a
        preview is the safe default. The caller opts in to writing.
        """
        sink_cfgs = enabled_items(self.config, "sinks")
        if "snipeit" not in sink_cfgs:
            raise ValueError("Writeback needs a Snipe-IT sink configured to read from.")
        reader = get_source_class("snipeit")(sink_cfgs["snipeit"])

        targets = {}
        for key, cfg in enabled_items(self.config, "writebacks").items():
            try:
                targets[key] = get_writeback_class(key)(cfg)
                logger.info("Enabled writeback: %s", key)
            except Exception as e:  # noqa: BLE001
                logger.error("Failed to initialize writeback '%s': %s", key, e)
        if not targets:
            raise ValueError("No writebacks enabled.")

        summary = WritebackSummary(dry_run=dry_run)
        for device in reader.fetch_all():
            summary.assets_read += 1
            if not device.asset_tag or device.serial in (None, "", "UNKNOWN"):
                continue
            for key, wb in targets.items():
                try:
                    result = wb.push(device, dry_run=dry_run)
                except Exception as e:  # noqa: BLE001 - one device shouldn't kill the run
                    from .writebacks.base import WritebackResult
                    result = WritebackResult(WritebackResult.FAILED, device.serial, str(e)[:200])
                summary.record(key, result)
        self._notify_writeback(summary)
        return summary

    # --- drift / reconciliation (observed vs system of record) ----------
    def _cmdb_reader(self):
        """Build the reader for the system of record drift compares against.

        Defaults to Snipe-IT (reading the configured Snipe-IT sink, so existing
        setups need no extra config). Set a top-level ``cmdb`` block to point
        drift at GLPI / NetBox / any other reader instead — the engine consumes
        the same NormalizedDevice list regardless of backend:

            cmdb:
              backend: netbox
              url: https://netbox.example.com
              token: ...
        """
        cmdb = self.config.get("cmdb") or {}
        backend = cmdb.get("backend", "snipeit")
        if backend == "snipeit" and not cmdb:
            # Back-compat: reuse the Snipe-IT sink credentials as the reader.
            sink_cfgs = enabled_items(self.config, "sinks")
            if "snipeit" not in sink_cfgs:
                raise ValueError(
                    "Drift needs a Snipe-IT sink (or a `cmdb:` block) configured "
                    "to read the system of record."
                )
            return get_source_class("snipeit")(sink_cfgs["snipeit"])
        try:
            return get_source_class(backend)(cmdb)
        except KeyError as e:
            raise ValueError(f"Unknown cmdb backend '{backend}'.") from e

    def run_drift(self, stale_days: int = 30):
        """Compare what the sources observe against the system-of-record CMDB.

        Read-only: pulls every enabled source, reconciles by serial (the same
        merge the sync uses), pulls the full CMDB (Snipe-IT by default, or the
        backend named in the ``cmdb`` config), and diffs them. Writes nothing.
        Returns a `reconcile.DriftReport`.
        """
        from .reconcile import reconcile

        record_reader = self._cmdb_reader()

        # Collect + reconcile observed devices exactly like a fleet sync would.
        summary = RunSummary(mode="fleet", dry_run=True)
        observed = self._collect_fleet(summary)
        record = list(record_reader.fetch_all())
        report = reconcile(observed, record, stale_days=stale_days)
        # Surface source-pull failures: a missing source biases the report toward
        # false "stale" findings, so the caller should know.
        report.source_errors = dict(summary.source_errors)
        self._notify_drift(report)
        return report

    def _notify_drift(self, report) -> None:
        if not self.notifiers:
            return
        from .reconcile import render_text

        counts = report.counts()
        drift_total = sum(v for k, v in counts.items() if k != "ok")
        level = "warning" if drift_total else "success"
        title = (f"Cairn drift: {counts['missing']} missing, "
                 f"{counts['stale']} stale, {counts['conflicting']} conflicting, "
                 f"{counts['duplicate']} duplicate")
        for notifier in self.notifiers.values():
            try:
                notifier.notify(title, render_text(report, color=False), level=level)
            except Exception as e:  # noqa: BLE001 - notifications are best-effort
                logger.error("notifier %s failed: %s", notifier.key, e)

    def _notify_writeback(self, summary: WritebackSummary) -> None:
        if not self.notifiers:
            return
        level = "error" if summary.failed else "success"
        title = f"Cairn writeback: {summary.updated} updated, {summary.failed} failed"
        for notifier in self.notifiers.values():
            try:
                notifier.notify(title, summary.as_text(), level=level)
            except Exception as e:  # noqa: BLE001
                logger.error("notifier %s failed: %s", notifier.key, e)

"""Drift / reconciliation engine — Cairn's core job, made visible.

Compares the devices *observed* by the MDM/EDR sources (already reconciled into
one record per serial) against the *system of record* (Snipe-IT) and classifies
every discrepancy:

  * missing      — observed by a source, absent from the CMDB. Someone bought a
                   laptop and never logged it. The CMDB is lying by omission.
  * stale        — present in the CMDB, but no source has seen it in N days. A
                   retirement / lost-device candidate.
  * duplicate    — the CMDB holds more than one asset row for the same serial.
  * conflicting  — present in both, but a field disagrees (hostname, model, …).
  * ok           — present in both and consistent.

Each finding carries a 0–100 **confidence score**: how sure Cairn is that the
finding is real and actionable, given how many independent sources corroborate
it and how strong the signal is. The engine performs *no* I/O itself — the
caller hands it two lists of NormalizedDevice — so it is fully unit-testable and
honest about external boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from .models import NormalizedDevice, mask_serial

# Drift categories, ordered by how loudly they should shout at an admin.
MISSING = "missing"
STALE = "stale"
DUPLICATE = "duplicate"
CONFLICTING = "conflicting"
OK = "ok"

_SEVERITY = {MISSING: 4, DUPLICATE: 3, CONFLICTING: 2, STALE: 1, OK: 0}

# Fields worth comparing across observed vs. system-of-record. We deliberately
# skip volatile fields (last_seen, compliance) — they drift constantly and a
# mismatch there isn't a data-integrity problem.
_COMPARE_FIELDS = ("hostname", "model", "manufacturer", "os_name")


@dataclass
class Finding:
    """One reconciliation result for one serial."""

    serial: str
    category: str
    confidence: int  # 0..100
    observed_by: list[str] = field(default_factory=list)  # source keys
    asset_tag: Optional[str] = None  # tag in the system of record, if known
    detail: str = ""
    conflicts: dict[str, dict[str, Any]] = field(default_factory=dict)
    # field -> {"observed": ..., "record": ...}

    def to_dict(self, mask: bool = True) -> dict[str, Any]:
        return {
            "serial": mask_serial(self.serial) if mask else self.serial,
            "category": self.category,
            "confidence": self.confidence,
            "observed_by": self.observed_by,
            "asset_tag": self.asset_tag,
            "detail": self.detail,
            "conflicts": self.conflicts,
        }


@dataclass
class DriftReport:
    stale_days: int
    generated_at: str
    findings: list[Finding] = field(default_factory=list)
    observed_total: int = 0
    record_total: int = 0
    # Source-pull failures, if any — a missing source skews findings toward
    # false "stale" hits, so we surface it rather than silently undercount.
    source_errors: dict[str, str] = field(default_factory=dict)

    def by_category(self, category: str) -> list[Finding]:
        return [f for f in self.findings if f.category == category]

    @property
    def drift(self) -> list[Finding]:
        """Every finding that isn't clean, worst first."""
        bad = [f for f in self.findings if f.category != OK]
        return sorted(bad, key=lambda f: (-_SEVERITY[f.category], -f.confidence))

    def counts(self) -> dict[str, int]:
        out = {c: 0 for c in (MISSING, STALE, DUPLICATE, CONFLICTING, OK)}
        for f in self.findings:
            out[f.category] += 1
        return out

    def to_dict(self, mask: bool = True) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "stale_days": self.stale_days,
            "observed_total": self.observed_total,
            "record_total": self.record_total,
            "counts": self.counts(),
            "source_errors": self.source_errors,
            "findings": [f.to_dict(mask=mask) for f in self.drift],
        }


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    """Best-effort ISO-8601 parse; vendors emit a Z, an offset, or nothing."""
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # Snipe-IT often returns "YYYY-MM-DD HH:MM:SS"
        try:
            dt = datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _days_since(value: Optional[str], now: datetime) -> Optional[float]:
    dt = _parse_dt(value)
    if dt is None:
        return None
    return (now - dt).total_seconds() / 86400.0


def reconcile(
    observed: list[NormalizedDevice],
    record: list[NormalizedDevice],
    stale_days: int = 30,
    now: Optional[datetime] = None,
) -> DriftReport:
    """Diff observed devices against the system of record.

    `observed` is the post-merge fleet from the MDM/EDR sources (one record per
    serial; pass the orchestrator's reconciled list). `record` is what the CMDB
    currently holds (e.g. every Snipe-IT asset). Neither is mutated.
    """
    if stale_days < 0:
        raise ValueError("stale_days must be >= 0")
    now = now or datetime.now(timezone.utc)

    # Index the system of record by serial; track duplicates explicitly.
    record_by_serial: dict[str, list[NormalizedDevice]] = {}
    for dev in record:
        if not dev.serial or dev.serial == "UNKNOWN":
            continue
        record_by_serial.setdefault(dev.serial, []).append(dev)

    observed_by_serial: dict[str, NormalizedDevice] = {}
    for dev in observed:
        if not dev.serial or dev.serial == "UNKNOWN":
            continue
        observed_by_serial[dev.serial] = dev

    report = DriftReport(
        stale_days=stale_days,
        generated_at=now.isoformat(),
        observed_total=len(observed_by_serial),
        record_total=len(record),
    )

    # --- serials present in observed data --------------------------------
    for serial, obs in observed_by_serial.items():
        sources = _sources_of(obs)
        rows = record_by_serial.get(serial)
        if not rows:
            report.findings.append(Finding(
                serial=serial,
                category=MISSING,
                confidence=_missing_confidence(sources),
                observed_by=sources,
                detail="not in the system of record",
            ))
            continue
        if len(rows) > 1:
            report.findings.append(Finding(
                serial=serial,
                category=DUPLICATE,
                confidence=95,
                observed_by=sources,
                asset_tag=", ".join(r.asset_tag for r in rows if r.asset_tag) or None,
                detail=f"{len(rows)} asset records share this serial in the CMDB",
            ))
            continue
        rec = rows[0]
        conflicts = _field_conflicts(obs, rec)
        if conflicts:
            report.findings.append(Finding(
                serial=serial,
                category=CONFLICTING,
                confidence=_conflict_confidence(sources, conflicts),
                observed_by=sources,
                asset_tag=rec.asset_tag,
                detail=f"{len(conflicts)} field(s) disagree: "
                       f"{', '.join(sorted(conflicts))}",
                conflicts=conflicts,
            ))
        else:
            report.findings.append(Finding(
                serial=serial,
                category=OK,
                confidence=100,
                observed_by=sources,
                asset_tag=rec.asset_tag,
            ))

    # --- serials only in the system of record (stale candidates) ---------
    for serial, rows in record_by_serial.items():
        if serial in observed_by_serial:
            continue
        if len(rows) > 1:
            report.findings.append(Finding(
                serial=serial,
                category=DUPLICATE,
                confidence=95,
                observed_by=[],
                asset_tag=", ".join(r.asset_tag for r in rows if r.asset_tag) or None,
                detail=f"{len(rows)} asset records share this serial in the CMDB",
            ))
            continue
        rec = rows[0]
        age = _days_since(rec.last_seen, now)
        if age is None:
            # No last_seen at all and no source sees it: treat as stale, but with
            # lower confidence since we can't measure the age.
            report.findings.append(Finding(
                serial=serial,
                category=STALE,
                confidence=55,
                observed_by=[],
                asset_tag=rec.asset_tag,
                detail="no source reports this device and the CMDB has no "
                       "last-seen date",
            ))
        elif age >= stale_days:
            report.findings.append(Finding(
                serial=serial,
                category=STALE,
                confidence=_stale_confidence(age, stale_days),
                observed_by=[],
                asset_tag=rec.asset_tag,
                detail=f"last seen {int(age)} days ago; no source reports it",
            ))
        # Recently-seen-in-CMDB-but-not-observed-now: not flagged. A source may
        # simply not cover this device (e.g. a printer no MDM manages).

    return report


# --- confidence scoring -------------------------------------------------
# Confidence answers "how sure are we this finding is real and worth acting on",
# not "how severe". More corroborating sources => higher confidence.

def _sources_of(device: NormalizedDevice) -> list[str]:
    srcs = device.extra.get("_sources") if isinstance(device.extra, dict) else None
    if srcs:
        return [s for s in srcs if s and s != "merged"]
    # Single, un-merged record: its own source key.
    return [device.source] if device.source and device.source != "merged" else []


def _missing_confidence(sources: list[str]) -> int:
    # One source could be a typo'd serial; several independent tools agreeing a
    # device exists makes "it's missing from the CMDB" near-certain.
    n = len(sources)
    if n >= 3:
        return 95
    if n == 2:
        return 85
    return 70


def _conflict_confidence(sources: list[str], conflicts: dict) -> int:
    base = 60 + 10 * min(len(conflicts), 3)
    if len(sources) >= 2:
        base += 10
    return min(base, 95)


def _stale_confidence(age_days: float, threshold: int) -> int:
    # The older past the threshold, the more confident it's genuinely retired.
    over = age_days - threshold
    return int(min(95, 60 + over / max(threshold, 1) * 35))


def _field_conflicts(obs: NormalizedDevice, rec: NormalizedDevice) -> dict:
    """Return {field: {observed, record}} for fields that disagree.

    Only counts a conflict when *both* sides have a value — a blank field in the
    CMDB is a backfill opportunity, not a conflict.
    """
    out: dict[str, dict[str, Any]] = {}
    for f in _COMPARE_FIELDS:
        o = getattr(obs, f, None)
        r = getattr(rec, f, None)
        if not o or not r:
            continue
        if str(o).strip().lower() != str(r).strip().lower():
            out[f] = {"observed": o, "record": r}
    return out


# --- rendering ----------------------------------------------------------
_LABELS = {
    MISSING: "MISSING from CMDB",
    STALE: "STALE / retire?",
    DUPLICATE: "DUPLICATE in CMDB",
    CONFLICTING: "CONFLICTING fields",
}

# ANSI colors, one per category. Disabled automatically when stdout isn't a TTY.
_COLORS = {
    MISSING: "\033[31m",      # red
    DUPLICATE: "\033[35m",    # magenta
    CONFLICTING: "\033[33m",  # yellow
    STALE: "\033[36m",        # cyan
}
_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"


def _conf_bar(confidence: int) -> str:
    filled = round(confidence / 10)
    return "█" * filled + "░" * (10 - filled)


def render_text(report: DriftReport, color: bool = True, mask: bool = True) -> str:
    """Human-readable drift report grouped by category, worst first."""
    def c(code: str, text: str) -> str:
        return f"{code}{text}{_RESET}" if color else text

    counts = report.counts()
    drift_total = sum(v for k, v in counts.items() if k != OK)
    lines: list[str] = []
    lines.append(c(_BOLD, "Cairn drift report"))
    lines.append(c(_DIM, f"  generated {report.generated_at}  "
                         f"(stale threshold: {report.stale_days}d)"))
    lines.append(
        f"  observed {report.observed_total} device(s) across sources vs "
        f"{report.record_total} asset record(s) in the CMDB"
    )
    lines.append("")
    # Summary line.
    summary_bits = [
        c(_COLORS[MISSING], f"{counts[MISSING]} missing"),
        c(_COLORS[STALE], f"{counts[STALE]} stale"),
        c(_COLORS[CONFLICTING], f"{counts[CONFLICTING]} conflicting"),
        c(_COLORS[DUPLICATE], f"{counts[DUPLICATE]} duplicate"),
        c(_DIM, f"{counts[OK]} ok"),
    ]
    lines.append("  " + "   ".join(summary_bits))
    lines.append("")

    if not drift_total:
        lines.append(c(_BOLD, "  No drift — the CMDB matches what your tools see."))
        if report.source_errors:
            lines.append("")
            lines.append(c(_COLORS[CONFLICTING], "  Warning: some sources failed to pull "
                                                 "(results may be incomplete):"))
            for src, err in report.source_errors.items():
                lines.append(f"    - {src}: {err}")
        return "\n".join(lines)

    # Group findings by category in severity order.
    for category in (MISSING, DUPLICATE, CONFLICTING, STALE):
        items = [f for f in report.drift if f.category == category]
        if not items:
            continue
        lines.append(c(_COLORS[category] + _BOLD, f"  {_LABELS[category]} ({len(items)})"))
        for f in items:
            serial = mask_serial(f.serial) if mask else f.serial
            tag = f" [{f.asset_tag}]" if f.asset_tag else ""
            seen = f"  seen by: {', '.join(f.observed_by)}" if f.observed_by else ""
            lines.append(
                f"    {serial:<14}{tag}  {c(_DIM, _conf_bar(f.confidence))} "
                f"{f.confidence:>3}%  {f.detail}{seen}"
            )
            for fld, vals in f.conflicts.items():
                lines.append(c(_DIM, f"        {fld}: source={vals['observed']!r} "
                                     f"cmdb={vals['record']!r}"))
        lines.append("")

    if report.source_errors:
        lines.append(c(_COLORS[CONFLICTING], "  Warning: some sources failed to pull "
                                             "(results may be incomplete):"))
        for src, err in report.source_errors.items():
            lines.append(f"    - {src}: {err}")
        lines.append("")

    lines.append(c(_DIM, "  Confidence = how sure Cairn is the finding is real "
                         "(more corroborating sources => higher)."))
    return "\n".join(lines)

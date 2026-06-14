# Drift & reconciliation report

[← Back to docs index](README.md)

`cairn drift` answers one question: **is your CMDB lying?** It is **read-only** —
it writes nothing. It pulls every enabled source, reconciles by serial (the exact
same merge `cairn sync` uses), pulls your whole system of record, and diffs them.
In one command you see exactly where the official record disagrees with the tools
that actually manage your fleet.

---

## Running it

```bash
cairn drift                          # grouped, colored report, worst first
cairn drift --stale-days 60          # only flag assets unseen for 60+ days
cairn drift --json                   # machine-readable JSON to stdout
cairn drift --json -o drift.json     # …or to a file
cairn drift --show-serials           # full serials (default masks to last 4)
cairn drift --no-color               # disable ANSI color
```

See [CLI reference → drift](cli-reference.md#cairn-drift) for the flag table.

**Exit code:** `0` if no drift; **`1` if any drift is found** (so cron/CI alerts
naturally); `2` if `--stale-days` is negative.

By default drift reads Snipe-IT (your sink). Point it at GLPI/NetBox with a
`cmdb:` block — see [Sinks & CMDB readers](sinks-and-cmdb.md#choosing-the-cmdb-for-drift).

---

## The four drift categories

Every device with a serial is sorted into exactly one bucket:

| Category | Meaning | What to do |
|---|---|---|
| **missing** | A device your MDM/EDR sees that **isn't in the CMDB at all**. Someone bought a laptop and never logged it. | Add it to the CMDB (or run `cairn sync` to create it). |
| **stale** | A CMDB asset **no source has seen in `--stale-days`** (default 30). A retirement / lost-device candidate. | Investigate; retire or mark lost. |
| **duplicate** | **More than one** CMDB asset row shares the same serial. | Merge/delete the duplicate rows. |
| **conflicting** | Present in both, but a field disagrees (hostname, model, manufacturer, OS name). | Decide which is right; fix the CMDB. |
| *ok* | Present in both and consistent. | Nothing — counted in the summary only. |

Notes on the logic:

- Only serials are reconciled. Records without a serial (e.g. network-discovery
  devices, some Defender/Sophos endpoints) don't produce serial-keyed findings.
- **Conflicts only count when both sides have a value.** A blank field in the
  CMDB is a *backfill opportunity*, not a conflict — it won't be flagged.
- Compared fields are deliberately limited to stable ones: `hostname`, `model`,
  `manufacturer`, `os_name`. Volatile fields (last_seen, compliance) are *not*
  compared — a mismatch there isn't a data-integrity problem.
- A CMDB asset that's recently-seen but simply isn't covered by any source (e.g. a
  printer no MDM manages) is **not** flagged stale — only assets past the
  threshold *and* unseen are.
- If a CMDB asset has **no last-seen date at all** and no source reports it, it's
  flagged **stale** at lower confidence (55), since the age can't be measured.

---

## Reading the report

```
Cairn drift report
  generated 2026-06-14T17:02:11+00:00  (stale threshold: 30d)
  observed 412 device(s) across sources vs 388 asset record(s) in the CMDB

  7 missing   3 stale   2 conflicting   1 duplicate   399 ok

  MISSING from CMDB (7)
    ****9F2A          ████████░░  85%  not in the system of record  seen by: jamf, crowdstrike
    ****1C04          ███████░░░  70%  not in the system of record  seen by: intune
  ...
  DUPLICATE in CMDB (1)
    ****77B1  [A1023, A2044]  ██████████  95%  2 asset records share this serial in the CMDB
  ...
  CONFLICTING fields (2)
    ****8D10  [A0991]  ████████░░  80%  1 field(s) disagree: hostname  seen by: jamf
        hostname: source='MARKETING-07' cmdb='mktg-laptop-7'

  Confidence = how sure Cairn is the finding is real (more corroborating sources => higher).
```

- Findings are **grouped by category, severity-ordered** (missing → duplicate →
  conflicting → stale), and within each group **worst first** (highest confidence).
- The bracketed value (`[A0991]`) is the **asset tag(s)** in the CMDB.
- `seen by:` lists the sources that corroborate an observed device.
- For conflicts, each disagreeing field is shown with both the source value and
  the CMDB value.
- Color is on when stdout is a TTY (disable with `--no-color`).

If some sources failed to pull, the report ends with a **warning** listing them —
a missing source biases results toward false "stale" hits, so you should know.

---

## Confidence scores

Every finding carries a **0–100 confidence**: *how sure Cairn is the finding is
real and worth acting on* (not how severe). More independent sources corroborating
a finding ⇒ higher confidence.

| Category | How confidence is computed |
|---|---|
| **missing** | 3+ sources agree ⇒ 95; 2 sources ⇒ 85; 1 source ⇒ 70. (One source could be a typo'd serial; several tools agreeing makes it near-certain.) |
| **duplicate** | Always 95 (a duplicate row is an objective fact). |
| **conflicting** | `60 + 10 × min(conflicting fields, 3)`, `+10` if 2+ sources, capped at 95. |
| **stale** | Scales with how far past the threshold: `60 + (age − threshold)/threshold × 35`, capped at 95. No last-seen date ⇒ 55. |

The text report renders confidence as a 10-segment bar plus the percentage. In
JSON it's the integer `confidence` field. Use it to triage: act on the
high-confidence findings first.

---

## Serial masking & `--show-serials`

Serial numbers identify physical machines (and seed warranty lookups), so Cairn
**masks them by default** — only the last 4 characters show (`****9F2A`), in both
the text and JSON output, and in notifier digests. Pass `--show-serials` to print
full serials (e.g. when you need to act on them in your CMDB). See
[Security → serial masking](security.md#serial-masking).

---

## JSON output

`--json` emits a machine-readable report for BI dashboards, alerting, or CI:

```bash
cairn drift --json -o drift.json
```

Shape:

```json
{
  "generated_at": "2026-06-14T17:02:11+00:00",
  "stale_days": 30,
  "observed_total": 412,
  "record_total": 388,
  "counts": { "missing": 7, "stale": 3, "duplicate": 1, "conflicting": 2, "ok": 399 },
  "source_errors": { },
  "findings": [
    {
      "serial": "****9F2A",
      "category": "missing",
      "confidence": 85,
      "observed_by": ["jamf", "crowdstrike"],
      "asset_tag": null,
      "detail": "not in the system of record",
      "conflicts": {}
    }
  ]
}
```

`findings` contains only the **drift** (non-ok) entries, sorted worst-first.
Serials are masked unless you also pass `--show-serials`.

---

## Scheduling a drift digest

Install a **read-only, recurring drift digest** so configured notifiers deliver a
"what's missing/stale/conflicting" summary to Teams/Slack/webhook on a cadence —
without ever writing to your CMDB:

```bash
cairn schedule install --drift --interval 86400    # daily
```

This schedules `cairn drift` (not `sync`). Each run reconciles, diffs, and — if
notifiers are enabled — sends a digest titled like
`Cairn drift: 7 missing, 3 stale, 2 conflicting, 1 duplicate`. See
[Scheduling](scheduling.md) and [Notifiers](notifiers.md).

You can also wire drift into CI directly, since it exits non-zero on drift:

```bash
cairn drift --json -o drift.json   # fails the step when drift exists
```

---

## See also

- [Concepts → reconciliation](concepts.md#reconciliation-merging-by-serial)
- [Sinks & CMDB readers](sinks-and-cmdb.md) — choosing/configuring the CMDB.
- [Troubleshooting → drift](troubleshooting.md#drift).

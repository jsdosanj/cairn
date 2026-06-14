# Concepts: the source → reconcile → sink model

[← Back to docs index](README.md)

This page explains what Cairn is, the model it is built on, and the vocabulary
the rest of the docs use. Read it once; everything else will make sense.

---

## What problem Cairn solves

Most teams already have several tools that each know about *some* of their
devices:

- An **MDM** (Mobile Device Management) like Jamf or Intune manages laptops and
  enrolls them.
- An **EDR** (Endpoint Detection & Response) like CrowdStrike or Defender watches
  the same laptops for threats.
- A **CMDB / asset system** (Configuration Management Database) like Snipe-IT is
  supposed to be the official record of every asset you own.

The trouble: the same laptop shows up in Jamf *and* CrowdStrike, a PC in Intune
*and* Defender, printers and switches show up in *nothing*, and the asset
database silently drifts out of date the moment someone forgets to update it.

Cairn treats **every tool as a pluggable source**, **every asset system as a
pluggable sink/reader**, and **reconciliation as a first-class step**. It:

1. **Pulls** device records from every tool you enable.
2. **Reconciles** them — records that share a serial number become one device,
   merged field by field in the order you trust your sources.
3. **Writes** the reconciled fleet to your system of record (or just *reports*
   the differences with `cairn drift`, writing nothing).

---

## The three building blocks

### Sources

A **source** is any system Cairn reads device data *out of*. Each source is a
plugin: one Python module that knows how to authenticate to one upstream API and
yield normalized device records. The MDM/EDR sources are the main ones (Jamf,
Intune, JumpCloud, CrowdStrike, Sophos, Defender, Kandji, Google Workspace /
ChromeOS, Apple Business Manager, UniFi, CDW, Rudder), plus a local
[network-discovery](network-discovery.md) source that finds devices no tool
manages.

Snipe-IT, GLPI, and NetBox can *also* act as sources — that is how Cairn reads a
system of record for the [drift](drift.md) report and for [writeback](writeback.md).

See [Source connectors](sources.md).

### Sinks

A **sink** is a system Cairn *writes* reconciled devices *into*. Today there is
one sink: **Snipe-IT**. When you run `cairn sync`, every reconciled device is
created or updated in every enabled sink.

See [Sinks & CMDB readers](sinks-and-cmdb.md).

### Notifiers

A **notifier** delivers a short run summary to a chat or HTTP endpoint after a
sync, writeback, or scheduled drift run: **Microsoft Teams**, **Slack**, or a
**generic webhook**. Optional. See [Notifiers](notifiers.md).

---

## The data model: `NormalizedDevice`

Every source maps its native, vendor-specific payload into one shared shape, a
`NormalizedDevice`. This is the lingua franca that lets a Jamf record and a
CrowdStrike record for the *same* laptop be compared and merged. Key fields:

| Field | Meaning |
|---|---|
| `serial` | Serial number — **the join key**. Uppercased, whitespace-stripped. Missing/unknown becomes `UNKNOWN`. |
| `source` | Which provider produced the record (e.g. `jamf`). After merge: `jamf+crowdstrike`. |
| `source_id` | The provider's own native device id (for round-trips / writeback). |
| `asset_type` | `computer` (default), `mobile`, `network`, `accessory`, `consumable`, or `purchase_order`. |
| `asset_tag` | The tag in the system of record. Populated when reading a CMDB; used by writeback. |
| `hostname` | Device/computer name. |
| `mac_addresses` | List of MACs, normalized to `AA:BB:CC:DD:EE:FF` and de-duplicated. |
| `os_name` / `os_version` / `os_build` | Coarse OS bucket (`macOS`/`Windows`/`Linux`/…) and version detail. |
| `model` / `manufacturer` | Hardware identity. |
| `primary_user` / `primary_user_email` / `logged_in_users` | Who uses it. |
| `last_seen` | ISO-8601 last check-in / last contact (drives "stale" detection). |
| `compliance` / `encrypted` | Security posture signals from EDR/MDM. |
| `extra` | Provider-specific normalized extras, namespaced per source. |
| `raw` | The untouched provider payload, namespaced per source, for debugging and field mapping. |

Serial normalization is aggressive on purpose: vendors disagree on case and
padding, and a stable key is exactly what lets Cairn correlate the same physical
machine across tools.

---

## Reconciliation (merging by serial)

When two or more sources report the same serial, Cairn merges them into one
device using your **`source_priority`** list:

- Sources are sorted by their position in `source_priority` (earlier = higher
  trust). Sources not listed sort last.
- For each field, the **highest-priority source that has a non-empty value
  wins**; empty fields are then **backfilled** from lower-priority sources.
- **MAC addresses are unioned** across all sources and re-normalized.
- Each source's `extra` and `raw` payloads are preserved, namespaced by source,
  so nothing is lost (`raw[jamf]`, `raw[crowdstrike]`, …).
- The merged record records every contributing source in `extra._sources`, which
  the drift report uses to compute [confidence](drift.md#confidence-scores).

EDR-only records that lack a serial (some Defender/Sophos endpoints) can't be
reconciled by serial — they are still synced, just written as-is rather than
merged.

Example trust order: `source_priority: [intune, jamf, jumpcloud, crowdstrike,
sophos, defender]` means "trust MDM ownership/hardware metadata from Intune and
Jamf first, fall back to EDR data for anything they don't have."

---

## Run modes: `fleet` vs `agent`

Cairn runs in one of two modes, set by `mode:` in config (override per run with
`--mode`):

### `fleet` — run centrally

Each enabled source is **fully enumerated**, records sharing a serial are merged,
and the reconciled devices are written to every sink. This is how you keep an
entire estate current. Run it on a schedule on one machine (a server, a
management box). This is the default.

### `agent` — run on the endpoint

Cairn collects the **local machine's** facts (via `system_info`), asks each
source for *that one serial*, merges, and writes a **single asset**. This mirrors
the original GhostAssetSync behavior, where the tool ran on each endpoint (e.g.
deployed by Jamf/Intune/GPO). If the local serial can't be determined and no
source matches, Cairn syncs the local facts only.

---

## The lifecycle of a sync

```
sources.fetch_all()  ──►  reconcile by serial  ──►  sink.upsert()  ──►  notify
   (pull devices)         (merge_devices)          (create/update)     (Teams/Slack)
```

With **incremental sync** on (the default), a per-device content hash means a
scheduled run only writes devices that actually changed since the last
successful sync — see [Efficiency](configuration.md#efficiency--incremental-sync).

---

## Read-only vs. write operations

| Command | Touches your CMDB? | Touches your MDM? |
|---|---|---|
| `cairn doctor` / `validate` | No | No |
| `cairn drift` | No (read-only) | No |
| `cairn sync --dry-run` | No | No |
| `cairn sync` | **Yes** (creates/updates assets) | No |
| `cairn writeback` (no `--apply`) | No (read-only preview) | No |
| `cairn writeback --apply` | No | **Yes** (writes asset tags) |

When in doubt, every write operation has a dry-run that shows you exactly what
would happen first.

---

Next: [Getting started](getting-started.md).

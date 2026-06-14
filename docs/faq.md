# FAQ

[← Back to docs index](README.md)

Short answers to common questions. For symptom-driven fixes see
[Troubleshooting](troubleshooting.md); for command details see the
[CLI reference](cli-reference.md).

---

### What is Cairn, in one sentence?

An open-source CLI that pulls device inventory from your MDM/EDR tools, merges
records for the same machine by serial, and keeps your asset system of record
(Snipe-IT, GLPI, or NetBox) honest — with a read-only drift report and optional
writeback.

### Is Cairn the same as GhostAssetSync?

Yes — Cairn is the evolution of GhostAssetSync. The `ghostsync` command and the
legacy `settings.conf` still work, so old deployments keep running unchanged.

### Do I need Python installed?

No, if you use a release binary (single cross-platform binary for macOS/Windows/
Linux). Yes, if you install from source.

### Does Cairn need a database or a server?

No. It's a CLI. Incremental state is a small JSON file (`~/.cairn/state.json`).
Scheduling uses the OS's own scheduler — no daemon.

---

### `agent` vs `fleet` — which mode do I want?

- **`fleet`** (default): run centrally, pull and reconcile the whole estate. This
  is what most people want.
- **`agent`**: run on each endpoint (e.g. deployed by Jamf/Intune/GPO) to sync
  just that machine. Mirrors original GhostAssetSync behavior.

See [Concepts → modes](concepts.md#run-modes-fleet-vs-agent).

### How does Cairn know two records are the same device?

By **serial number** (normalized: uppercased, trimmed). Records sharing a serial
are merged field-by-field using your `source_priority`. MACs are unioned.

### What if a device has no serial?

It can't be merged by serial, so it's synced as-is (not reconciled). Network gear
from [network discovery](network-discovery.md) is keyed by MAC and carries
`serial: UNKNOWN`.

### How do I control which source "wins" a field?

`source_priority` — earlier sources win; empty fields are backfilled from later
ones. See [Concepts → reconciliation](concepts.md#reconciliation-merging-by-serial).

---

### Which systems can Cairn write to?

Only **Snipe-IT** (the sink). GLPI and NetBox are **read-only** CMDB readers used
by `cairn drift`. Writeback writes the asset tag into **Jamf** or **Intune**.

### Can Cairn read from ServiceNow / write to GLPI or NetBox?

No. There's **no ServiceNow** connector, and GLPI/NetBox are read-only (no sink).
Don't configure these — they aren't implemented.

### What sources are supported?

Jamf, Intune, JumpCloud, CrowdStrike, Sophos, Defender, Kandji, Google Workspace
(ChromeOS), Apple Business Manager, UniFi, CDW (CSV), Rudder, plus local network
discovery. Run `cairn list-providers` to see the live list.

---

### Will `cairn sync` overwrite or delete things in Snipe-IT?

It creates assets that don't exist and updates the name + mapped custom fields of
ones that do (keeping the existing asset tag). It never deletes. Preview with
`cairn sync --dry-run` first.

### Why are most devices "skipped" on a sync?

Incremental sync skipped them because nothing changed since the last good run.
That's the point — it keeps scheduled runs cheap. Force everything with
`cairn sync --full`.

### Why does `cairn drift` exit with code 1?

Because it found drift. That's intentional so cron/CI can alert. A clean CMDB
exits `0`.

### Is `cairn drift` safe to run anytime?

Yes — it's strictly read-only. So is `cairn sync --dry-run` and
`cairn writeback` without `--apply`.

---

### Where do I put secrets so they're not in a file?

Use environment variables (`CAIRN_sources__<name>__<key>=…` or the legacy
`GHOST_*` vars), or the OS keychain (`keyring:NAME`). See
[Security](security.md#supplying-secrets-via-environment-variables).

### Why won't Cairn start — it complains about permissions?

Your config is world-readable. `chmod 600 config.yaml`. Cairn refuses to load
credentials from a world-readable file.

### Why are serials shown as `****1234`?

Serials are masked to the last 4 chars in logs/reports/notifications by default.
Use `cairn drift --show-serials` for full serials.

### My internal Snipe-IT uses a self-signed cert. How do I connect?

Set `ca_bundle: /path/to/ca.pem` on the provider (preferred). Only as a last
resort, `verify_ssl: false` + `CAIRN_ALLOW_INSECURE_TLS=1`. See
[Security → TLS](security.md#tls).

### Does Cairn scan my network?

No, not by default. Network discovery only **reads the local ARP cache** (no
packets sent). Active sweeping is a no-op TODO and is doubly gated. See
[no-scan-by-default](security.md#no-scan-by-default).

---

### How often should I schedule it?

Hourly (`--interval 3600`) is a good default for sync; daily
(`--interval 86400`) is typical for a `--drift` digest. Incremental sync keeps
runs cheap, and idle-priority keeps them out of the way.

### Can I run a scheduled sync *and* a scheduled drift digest?

`cairn schedule` manages one job per platform. Install one with Cairn and add the
second manually with your OS scheduler. See
[Scheduling](scheduling.md#scheduled-drift-digest).

### What does the web dashboard do, and is it secure to expose?

It lets non-technical users test connections, dry-run, and toggle the schedule.
Keep it on `127.0.0.1` — its token is localhost protection, not real auth. See
[CLI → web](cli-reference.md#cairn-web).

### How do I add a new source connector?

It's one module implementing `DeviceSource.fetch_all()` (optionally
`find_by_serial`) plus one line in `registry.py`. (Developer task; see the repo
README's Architecture section.)

---

Didn't find it? Try [Troubleshooting](troubleshooting.md), the
[Error reference](errors.md), or the [recipe index](recipes.md).

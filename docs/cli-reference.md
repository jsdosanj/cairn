# CLI reference

[← Back to docs index](README.md)

Every command, every flag, with examples and exit codes. The program is invoked
as `cairn` (the legacy alias `ghostsync` is identical).

---

## Global options

These come **before** the subcommand:

| Option | Description |
|---|---|
| `-c PATH`, `--config PATH` | Use a specific config file instead of auto-discovering `config.yaml`/`config.yml` in the working directory. |
| `-v`, `--verbose` | Debug-level logging to stderr. Use this when filing a bug or diagnosing an auth issue. |
| `--version` | Print the Cairn version and exit. |
| `-h`, `--help` | Show help. Works on the top level and on every subcommand (`cairn drift --help`). |

```bash
cairn -c /etc/cairn/prod.yaml -v sync --dry-run
```

> **Bare invocation:** running `cairn` with no subcommand behaves like
> `cairn sync` (a real sync, not a dry-run). This is back-compat with
> GhostAssetSync. Prefer being explicit.

---

## Exit codes

Cairn uses meaningful exit codes so it works cleanly in CI, cron, and scripts:

| Code | Meaning | Which commands |
|---|---|---|
| `0` | Success / no problems found | all |
| `1` | Operation completed but something failed, OR a finding was reported | `sync`/`writeback` (a sink/target failed); `drift` (**drift was found**); `doctor` (a connection failed); `setup`/`web` (per their own return) |
| `2` | Configuration error, or invalid arguments | any command on `ConfigError`; `drift` on a negative `--stale-days` |
| `130` | Interrupted (Ctrl-C) | any |

The most important nuance: **`cairn drift` exits `1` whenever it finds any drift**
(missing/stale/duplicate/conflicting). That is intentional, so a scheduled drift
run or a CI step naturally fails/alerts when your CMDB is wrong. A perfectly
clean CMDB exits `0`.

---

## Command summary

```
cairn setup                 interactive first-run wizard (recommended)
cairn web                   launch the local point-and-click dashboard
cairn init                  print a starter config to stdout
cairn doctor                test every configured connection
cairn validate              load config + build providers, report readiness
cairn drift                 reconcile sources vs the CMDB (read-only report)
cairn sync                  run a sync (agent or fleet per config)
cairn writeback             push Snipe-IT asset tags back to your MDM
cairn schedule {install|status|uninstall}   manage the native scheduled job
cairn list-providers        list available sources / sinks / notifiers / writebacks
```

---

## `cairn setup`

Interactive first-run wizard. Picks your tools, prompts for credentials, tests
each connection live, optionally stores secrets in your OS keychain, and writes
the config file.

```bash
cairn setup
cairn -c team-prod.yaml setup    # write to a specific path
```

Writes to `config.yaml` (or the `-c` path). See [Getting started](getting-started.md).

---

## `cairn web`

Launches a zero-dependency local web dashboard in your browser: test connections,
preview a dry-run sync with a results table, and toggle the schedule — no YAML
editing.

```bash
cairn web                          # http://127.0.0.1:8765
cairn web --host 0.0.0.0 --port 9000
```

| Flag | Default | Description |
|---|---|---|
| `--host` | `127.0.0.1` | Bind address. **Leave it on localhost** unless you understand the exposure — the dashboard can reveal config structure. |
| `--port` | `8765` | Bind port. |

Security notes: the page embeds a random per-session token that every API call
must echo (deters other local processes / CSRF), and secret fields are masked
(`********`) when echoed back to the browser. It is **not** real authentication —
do not expose it to an untrusted network. See [Security](security.md).

---

## `cairn init`

Prints a minimal starter config to **stdout**, so you can redirect it to a file:

```bash
cairn init > config.yaml
chmod 600 config.yaml
```

Writes nothing itself; just emits text.

---

## `cairn doctor`

Tests **every configured connection** by making one cheap real call per provider
(pull one device from each source; do one harmless lookup against each sink).

```bash
cairn doctor
cairn -c prod.yaml doctor
```

Output:

```
[OK  ] source:jamf — reachable
[FAIL] source:crowdstrike — POST .../oauth2/token -> 401: access denied
[OK  ] sink:snipeit — reachable

2/3 healthy.
```

**Exit codes:** `0` if all healthy; `1` if any check failed **or** if no sources
or sinks are enabled. Use this first whenever something isn't working.

---

## `cairn validate`

Loads the config and **constructs** every provider (which surfaces missing
credentials and bad config early) **without making network calls**. Lighter than
`doctor` — it checks wiring, not reachability.

```bash
cairn validate
```

Output:

```
mode: fleet
sources: jamf, crowdstrike
sinks: snipeit
notifiers: slack

Ready: 2 source(s), 1 sink(s), 1 notifier(s).
```

**Exit codes:** `0` if everything constructs; `1` on a validation failure (prints
`VALIDATION FAILED: …`); `2` on a config-file error.

---

## `cairn sync`

Runs a sync: pull from sources, reconcile by serial, upsert into every sink,
notify. See [Concepts → lifecycle](concepts.md#the-lifecycle-of-a-sync).

```bash
cairn sync                  # real sync, mode per config
cairn sync --dry-run        # report changes, write nothing
cairn sync --full           # re-sync every device (ignore incremental state)
cairn sync --mode agent     # override the configured mode for this run
cairn sync --mode fleet --full --dry-run    # flags combine
```

| Flag | Description |
|---|---|
| `--dry-run` | Compute and report every create/update, but **write nothing**. Safe to run anytime. Devices are never recorded as "synced" in dry-run, so the next real run still processes them. |
| `--full` | Ignore [incremental state](configuration.md#efficiency--incremental-sync) and re-process every device, even unchanged ones. Use after changing your `field_map` or to repair a sink. |
| `--mode {agent,fleet}` | Override `mode:` from config for this run only. |

Output (a `RunSummary`):

```
Cairn fleet run (dry-run)
  devices reconciled: 412
  created: 7  updated: 38  skipped: 367  failed: 0
  source errors:
    - sophos: POST .../token -> 401: invalid client
```

- `created` / `updated` — assets written (or that *would* be, in dry-run).
- `skipped` — unchanged devices that incremental sync skipped before any write.
- `failed` — a sink rejected the device.
- `source errors` — a source that failed to pull entirely (the run continues with
  the remaining sources).

**Exit codes:** `0` if nothing failed; `1` if any device failed at a sink; `2` on
a config error.

---

## `cairn writeback`

Reads assets from Snipe-IT and pushes the **asset tag** back into the matching
MDM device (the `snipe2jamf` / Snipe-IT → Intune direction). **Dry-run by
default** — it mutates a system you may not own, so you must opt in to writing.

```bash
cairn writeback            # preview: what would change in the MDM
cairn writeback --apply    # actually write the asset tags
```

| Flag | Description |
|---|---|
| `--apply` | Actually write to the MDM. Without it you get a preview and a reminder. |

Requires a Snipe-IT sink (to read from) and at least one enabled `writebacks:`
target. Honors a per-target conflict policy and never creates devices. Full
details: [Writeback](writeback.md).

**Exit codes:** `0` if nothing failed; `1` if any target write failed; `2` on a
config error.

---

## `cairn drift`

Read-only reconciliation report: pulls every source, reconciles by serial, pulls
the whole CMDB, and classifies every discrepancy as **missing / stale / duplicate
/ conflicting** with a confidence score. Writes nothing. Full guide:
[Drift](drift.md).

```bash
cairn drift                          # grouped, colored report, worst first
cairn drift --stale-days 60          # only flag assets unseen for 60+ days
cairn drift --json                   # machine-readable JSON to stdout
cairn drift --json -o drift.json     # …or to a file
cairn drift --show-serials           # print full serials (default masks to last 4)
cairn drift --no-color               # disable ANSI color
```

| Flag | Default | Description |
|---|---|---|
| `--stale-days N` | `30` | Flag CMDB assets no source has seen in N days. Must be `≥ 0`. |
| `--json` | off | Emit the report as JSON instead of the human-readable view. |
| `--output PATH`, `-o PATH` | stdout | Write the report to a file. |
| `--show-serials` | off | Print full serial numbers. Default masks to the last 4 chars. |
| `--no-color` | off | Disable ANSI color (also auto-disabled when stdout isn't a TTY). |

**Exit codes:** `0` if no drift; **`1` if any drift is found** (this is the point
— it lets cron/CI alert); `2` if `--stale-days` is negative.

If notifiers are configured, `drift` also delivers a digest to Teams/Slack/webhook.

---

## `cairn schedule`

Install, inspect, or remove a native OS-level scheduled job. Full guide:
[Scheduling](scheduling.md).

```bash
cairn schedule install                      # use schedule.interval from config (or 3600s)
cairn schedule install --interval 3600      # every hour
cairn schedule install --interval 1800 --mode fleet
cairn schedule install --drift --interval 86400   # daily read-only DRIFT digest
cairn schedule status
cairn schedule uninstall
```

| Action | Description |
|---|---|
| `install` | Create the OS-native scheduled job (launchd / systemd-or-cron / Task Scheduler). |
| `status` | Show whether the job exists and is loaded/active. |
| `uninstall` | Remove the scheduled job. |

| Flag (with `install`) | Description |
|---|---|
| `--interval SECONDS` | Seconds between runs. Defaults to `schedule.interval` in config, else `3600`. |
| `--mode {agent,fleet}` | Mode for the scheduled *sync*. Ignored for `--drift` (drift is always a read-only fleet pull). |
| `--drift` | Schedule a **read-only drift digest** instead of a sync. Notifiers deliver the missing/stale/conflicting digest. |

**Exit code:** `0` on success (errors from the OS scheduler raise and exit `1`).

---

## `cairn list-providers`

Lists every available plugin, regardless of what's enabled in your config.

```bash
cairn list-providers
```

```
Sources:    apple_bm, cdw, crowdstrike, defender, glpi, google_workspace, intune,
            jamf, jumpcloud, kandji, netbox, network_discovery, rudder, snipeit,
            sophos, unifi
Sinks:      snipeit
Notifiers:  slack, teams, webhook
Writebacks: intune, jamf
```

**Exit code:** `0`.

---

## Quick examples

```bash
# First-time, manual setup
cairn init > config.yaml && chmod 600 config.yaml
cairn validate && cairn doctor

# Safe preview before any write
cairn drift
cairn sync --dry-run

# Production run with an explicit config and debug logs
cairn -c /etc/cairn/prod.yaml -v sync

# Daily drift gate in CI (non-zero exit on drift)
cairn drift --json -o drift.json || echo "CMDB drift detected"

# Force a full re-sync after changing field_map
cairn sync --full
```

Next: [Configuration reference](configuration.md).

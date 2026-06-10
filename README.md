# Cairn

**Every device. One source of truth.**

Cairn reconciles device inventory from the MDM and EDR tools that already manage
your fleet into your asset system of record (Snipe-IT), automatically. Point it
at Jamf, Intune, JumpCloud, CrowdStrike, Sophos, and Microsoft Defender; it pulls
each one, merges records that describe the same physical machine by serial number,
and keeps your CMDB honest.

> Cairn is the evolution of **GhostAssetSync**. The `ghostsync` command and the
> legacy `settings.conf` still work, so existing deployments keep running.

---

## Why Cairn

The original tool synced one source (Jamf) to one sink (Snipe-IT) for the machine
it ran on. Real fleets are messier: a laptop shows up in Jamf *and* CrowdStrike, a
PC in Intune *and* Defender, and your asset database drifts out of date the moment
someone forgets to update it. Cairn treats every tool as a pluggable source, every
asset system as a pluggable sink, and reconciliation as a first-class step.

- **Pluggable providers** — add an MDM/EDR by dropping in one module. The core
  never changes.
- **Serial-number reconciliation** — one device seen by three tools becomes one
  asset, merged field-by-field in your trust order.
- **Two run modes** — `agent` (run on each endpoint, sync that machine) or
  `fleet` (run centrally, pull and reconcile the whole fleet).
- **Security-first** — HTTPS enforced, secrets via env vars, config permission
  checks, retry/backoff on every API call, serial masking in logs.
- **Dry-run** — see exactly what would change before anything is written.
- **Cross-platform single binary** — macOS, Windows, Linux. No Python required on
  the endpoint.

---

## Supported integrations

| Sources (MDM / EDR)              | System of record | Notifications      |
|----------------------------------|------------------|--------------------|
| Jamf Pro                         | Snipe-IT         | Microsoft Teams    |
| Microsoft Intune (Graph)         |                  | Slack              |
| JumpCloud                        |                  | Generic webhook    |
| CrowdStrike Falcon               |                  |                    |
| Sophos Central                   |                  |                    |
| Microsoft Defender for Endpoint  |                  |                    |

---

## Install

**Download a release binary** (recommended) from
[Releases](https://github.com/jsdosanj/GhostAssetSync/releases):

- macOS — `.pkg` installer or `cairn-macos.tar.gz`
- Windows — `.zip` or the Inno Setup `.exe` installer
- Linux — `.deb` or `cairn-linux.tar.gz`

**Or install from source:**

```bash
git clone https://github.com/jsdosanj/GhostAssetSync.git
cd GhostAssetSync
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
cairn --help
```

---

## Quick start

1. Copy the example config and lock it down:

   ```bash
   cp config.example.yaml config.yaml
   chmod 600 config.yaml      # Cairn refuses a world-readable config
   ```

2. Enable the sources you use and fill in credentials (or supply secrets via env
   vars — see below). Minimal example:

   ```yaml
   mode: fleet
   source_priority: [intune, jamf, crowdstrike]

   sources:
     jamf:
       enabled: true
       url: https://your.jamf.instance.com
       client_id: ...
       client_secret: ...
     crowdstrike:
       enabled: true
       client_id: ...
       client_secret: ...
       base_url: https://api.us-2.crowdstrike.com

   sinks:
     snipeit:
       enabled: true
       url: https://your-snipe-it/api/v1
       token: ...
   ```

3. Validate, then dry-run, then sync:

   ```bash
   cairn validate              # check config + credentials wiring
   cairn sync --dry-run        # show what would change, write nothing
   cairn sync                  # do it
   ```

---

## Commands

```
cairn validate              load config, initialize every provider, report readiness
cairn sync                  run a sync (agent or fleet per config)
cairn sync --dry-run        report changes, write nothing
cairn sync --full           re-sync every device (ignore incremental state)
cairn sync --mode agent     override the configured mode for one run
cairn schedule install      install a native scheduled auto-sync (--interval SECONDS)
cairn schedule status       show the scheduled job
cairn schedule uninstall    remove the scheduled job
cairn list-providers        list available sources / sinks / notifiers
cairn -c path/to.yaml ...   use a specific config file
cairn -v ...                debug logging
```

---

## Run modes

**`fleet`** (run centrally, e.g. on a schedule): each enabled source is fully
enumerated, records sharing a serial are merged using `source_priority`, and the
reconciled devices are written to every enabled sink. This is how you keep an
entire estate current.

**`agent`** (run on the endpoint, e.g. via Jamf/Intune/GPO): Cairn collects the
local machine's facts, asks each source for that one serial, merges, and writes a
single asset. This mirrors the original GhostAssetSync behavior.

### Reconciliation

When two tools report the same serial, fields are filled in `source_priority`
order: the highest-priority source wins each field it has a value for, and empty
fields are backfilled from lower-priority sources. MAC addresses are unioned and
normalized; every source's raw payload is preserved under `raw[<source>]`. EDR-only
records that lack a serial (some Defender/Sophos endpoints) are still synced, just
not merged.

---

## Scheduling (auto-sync)

Install Cairn as a native scheduled job so it keeps Snipe-IT current on its own:

```bash
cairn schedule install --interval 3600   # sync every hour
cairn schedule status
cairn schedule uninstall
```

Per platform, this uses the OS-native scheduler (no daemon to babysit):

- **macOS** — a launchd LaunchAgent (`~/Library/LaunchAgents/com.cairn.sync.plist`),
  run at low I/O priority, logging to `~/Library/Logs/cairn.log`.
- **Linux** — a `systemd --user` service + timer, falling back to cron if systemd
  isn't available. (Run `loginctl enable-linger $USER` to keep it running while
  logged out.)
- **Windows** — a Task Scheduler task (`schtasks`).

The interval defaults to `schedule.interval` in your config (or 3600s).

## Efficiency

Cairn is built to run cheaply on a tight schedule:

- **Incremental sync** — a per-device content hash means a scheduled run only
  writes the devices that actually changed. Unchanged devices are skipped before
  any write. `last_seen` is excluded from the hash by default so a routine
  check-in doesn't cause churn. Force a full re-sync with `cairn sync --full`.
- **Streaming** — sources yield devices as they page, so memory stays flat
  regardless of fleet size.
- **Connection reuse** — pooled keep-alive sessions with retry/backoff per source.
- **Lazy loading** — only the providers you enable are imported.
- **Low priority** — scheduled jobs run niced / idle-I/O so they stay out of the
  way of interactive work.

State lives in `~/.cairn/state.json` (override with `state_path` or `CAIRN_STATE`).

---

## Configuration & secrets

Configuration is YAML (`config.yaml` / `config.yml`, auto-discovered in the working
directory) or the legacy `settings.conf`. **Any value can be overridden by an
environment variable** — keep secrets out of files in production:

```bash
# Legacy vars (still honored):
export GHOST_JAMF_URL=... GHOST_SNIPE_TOKEN=... TEAMS_WEBHOOK_URL=...

# Generic nested form — CAIRN_<section>__<provider>__<key>:
export CAIRN_sources__crowdstrike__client_secret=...
export CAIRN_sinks__snipeit__token=...
```

Precedence: environment variables > `config.yaml` > legacy `settings.conf`.

### Snipe-IT field mapping

Snipe-IT custom fields are mapped by label to any device attribute (or a nested
`extra.<source>.<key>` path) in config, so you decide what lands where without
touching code:

```yaml
sinks:
  snipeit:
    field_map:
      "Operating System": os_name
      "OS Version": os_version
      "MAC Address": mac_addresses
      "Falcon Risk": extra.crowdstrike.reduced_functionality_mode
```

See [`config.example.yaml`](config.example.yaml) for every option.

---

## Security

- **HTTPS enforced** on every API and webhook URL (localhost exempt for dev).
- **Config permissions** — Cairn refuses to start on a world-readable config and
  warns on group-readable; `chmod 600` it.
- **Secrets via env** — every credential can be supplied by environment variable.
- **TLS verification on**, retry/backoff with `Retry-After` respected.
- **Serial masking** — only the last 4 chars of a serial appear in logs and
  notifications.
- Report vulnerabilities via a GitHub issue tagged `[SECURITY]`.

---

## Architecture

```
src/cairn/
├── cli.py            argparse entrypoint (sync / validate / list-providers)
├── orchestrator.py   pull -> reconcile-by-serial -> upsert -> notify
├── config.py         YAML + env + legacy .ini loader
├── models.py         NormalizedDevice + merge_devices (the lingua franca)
├── http.py           retrying session, HTTPS enforcement, OAuth2 client creds
├── registry.py       maps config keys -> provider classes (lazy import)
├── state.py          incremental-sync hash store (skip unchanged devices)
├── scheduler.py      install native scheduled jobs (launchd / systemd / schtasks)
├── system_info.py    local machine facts (macOS / Windows / Linux) for agent mode
├── sources/          DeviceSource plugins: jamf, intune, jumpcloud,
│                     crowdstrike, sophos, defender
├── sinks/            AssetSink plugins: snipeit
└── notifiers/        teams, slack, webhook
```

**Adding a source** is one file implementing `DeviceSource.fetch_all()` (plus an
optional server-side `find_by_serial`) and one line in `registry.py`.

---

## Development

```bash
pip install -e ".[dev]"
pytest                      # 26 tests: models, config, sink, orchestrator, providers
```

Provider tests mock the upstream APIs with `responses`, so the suite is fast and
offline.

---

## Packaging & releases

Tag a release and CI builds all three platforms and attaches them to a GitHub
Release:

```bash
git tag v1.0.0 && git push origin v1.0.0
```

Build locally with the scripts in [`installers/`](installers/) (PyInstaller
one-file binary, then `.pkg` / `.deb` / `.zip`). See
[`installers/README.md`](installers/README.md).

---

## License

MIT. Formerly GhostAssetSync.

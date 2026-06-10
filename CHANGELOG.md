# Changelog

All notable changes to this project are documented here.

## [1.1.0] — 2026-06-10

**More integrations, and you no longer need a terminal to use Cairn.**

This release starts consolidating the Snipe-IT integration ecosystem and adds a
guided experience for non-technical admins.

### Added

- **New sources**: **Kandji** (Apple MDM) and **Google Workspace / ChromeOS**
  (Admin SDK). Cairn now reads from 8 systems.
- **Asset typing** — devices carry an `asset_type` (computer / mobile / network /
  accessory / consumable / purchase_order), so non-laptop assets fit.
- **`cairn setup`** — an interactive wizard that connects Snipe-IT and each tool
  with plain-language prompts, **tests the connection live**, and writes your
  config. No YAML editing.
- **`cairn web`** — a local dashboard (opens in your browser): see your
  integrations, test connections, run a **dry-run with a results table**, and turn
  on the schedule, all with clicks.
- **`cairn doctor`** — one command that tests every configured connection and tells
  you what's healthy.
- **OS-keychain secret storage** — store tokens in macOS Keychain / Windows
  Credential Manager / libsecret instead of plaintext, referenced as
  `keyring:NAME` (install with `pip install 'cairn-sync[secrets]'`).

### For contributors

- Central `provider_meta.py` describes every integration's fields (powers the
  wizard, dashboard, and doctor). 53 tests total.

[1.1.0]: https://github.com/jsdosanj/cairn/releases/tag/v1.1.0

## [1.0.1] — 2026-06-10

**Relicensed to AGPL-3.0, repo renamed to `cairn`, and release downloads made stable.**

### Changed

- **License**: relicensed from MIT to **AGPL-3.0-or-later** to match Snipe-IT,
  which Cairn integrates with.
- **Repository** renamed to `github.com/jsdosanj/cairn` (the old URL redirects).

### Added

- `cairn --version` and `cairn init` (prints a starter config:
  `cairn init > cairn.yaml`).
- Releases now publish **stable, version-less asset names** (`cairn-macos.tar.gz`,
  `cairn-macos.pkg`, `cairn-linux.deb`, `cairn-linux.tar.gz`,
  `cairn-windows-x64.zip`) alongside the versioned ones, so
  `releases/latest/download/<name>` links always resolve.

[1.0.1]: https://github.com/jsdosanj/cairn/releases/tag/v1.0.1

## [1.0.0] — 2026-06-10

**GhostAssetSync becomes Cairn: one tool that reconciles your whole device fleet into Snipe-IT.**

The original tool synced one source (Jamf) to Snipe-IT for the machine it ran on.
Cairn turns that into a pluggable engine: point it at the MDM and EDR tools that
already manage your devices, and it keeps your asset system of record honest,
automatically, on a schedule.

### Added

- **Six MDM/EDR sources**: Jamf Pro, Microsoft Intune (Graph), JumpCloud,
  CrowdStrike Falcon, Sophos Central, and Microsoft Defender for Endpoint. Enable
  any combination in config.
- **Serial-number reconciliation** — a device seen by several tools becomes one
  asset, merged field-by-field in your trust order. MAC addresses are unioned and
  normalized across vendor formats.
- **Two run modes** — `fleet` (run centrally, pull and reconcile the whole estate)
  and `agent` (run on an endpoint, sync just that machine; the original behavior).
- **Incremental sync** — scheduled runs only write the devices that actually
  changed, using a per-device content hash. `last_seen` is excluded by default so
  a routine check-in doesn't cause churn. `cairn sync --full` forces a re-sync.
- **Native scheduling** — `cairn schedule install --interval 3600` sets up a
  background auto-sync using launchd (macOS), systemd `--user` timer with a cron
  fallback (Linux), or Task Scheduler (Windows). Jobs run at low I/O priority.
- **Notifications** — Microsoft Teams (Adaptive Card), Slack, and generic webhook.
- **Config-driven Snipe-IT field mapping** — map any device attribute to any
  Snipe-IT custom field without touching code.
- **Cross-platform installers** — macOS `.pkg`, Linux `.deb` + tarball, Windows
  `.zip` + Inno Setup installer, built by CI and attached to each release.
- **`cairn validate`** and **`cairn sync --dry-run`** to check wiring and preview
  changes before writing anything.

### Changed

- Configuration is now YAML (`config.yaml`) with environment-variable overrides
  for every secret. The legacy `settings.conf` and `GHOST_*` env vars still work.
- HTTPS is enforced on every API and webhook; all calls retry with backoff and
  honor `Retry-After`.

### Compatibility

- The `ghostsync` command and `settings.conf` continue to work, so existing
  Jamf/Intune/GPO deployments keep running unchanged.

### For contributors

- Plugin architecture: adding a source is one module implementing
  `DeviceSource.fetch_all()` plus one line in `registry.py`.
- 39 offline tests (`pytest`) covering models, config, sink, orchestrator,
  incremental state, scheduler unit generation, and provider normalization.

[1.0.0]: https://github.com/jsdosanj/cairn/releases/tag/v1.0.0

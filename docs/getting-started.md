# Getting started

[← Back to docs index](README.md)

This page takes you from nothing to a working sync. It assumes no prior
knowledge. If you have not yet, skim [Concepts](concepts.md) first.

---

## 1. Install

You have two options.

### Option A — download a release binary (recommended for non-developers)

Cairn ships as a single cross-platform binary, so **Python is not required on the
machine that runs it**. Download from the project's
[Releases](https://github.com/jsdosanj/cairn/releases) page:

- **macOS** — a `.pkg` installer, or `cairn-macos.tar.gz`.
- **Windows** — a `.zip`, or the Inno Setup `.exe` installer.
- **Linux** — a `.deb`, or `cairn-linux.tar.gz`.

After installing, confirm it works:

```bash
cairn --help
cairn --version
```

### Option B — install from source (for developers)

```bash
git clone https://github.com/jsdosanj/cairn.git
cd cairn
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
cairn --help
```

Some sources need optional dependencies (only install what you use):

```bash
pip install -e '.[google]'    # Google Workspace / ChromeOS (PyJWT, cryptography)
pip install -e '.[apple]'     # Apple Business Manager       (PyJWT, cryptography)
pip install -e '.[secrets]'   # OS keychain secret storage    (keyring)
pip install -e '.[dev]'       # test/build tooling
```

> `cairn` and `ghostsync` are the same program — both console commands are
> installed, so legacy GhostAssetSync invocations keep working.

---

## 2. Choose your path

### The easy path (no YAML, no terminal know-how)

```bash
cairn setup     # guided wizard: pick your tools, paste credentials, test live
cairn web       # opens a local dashboard: test connections, dry-run, schedule
```

- **`cairn setup`** walks you through Snipe-IT and each integration, tests every
  connection as you go, can store secrets in your OS keychain, and writes the
  config for you.
- **`cairn web`** launches a clickable local dashboard (bound to `127.0.0.1` by
  default) where you can test connections, preview a dry-run with a results
  table, and toggle the schedule. See [CLI reference → web](cli-reference.md#cairn-web).

When you're done with the wizard, jump to step 5 (validate and sync).

### The manual path (terminal)

Continue with steps 3–5 below.

---

## 3. Create a config file

Generate a starter config and lock it down:

```bash
cairn init > config.yaml     # prints a minimal starter config
chmod 600 config.yaml        # REQUIRED: Cairn refuses a world-readable config
```

Or copy the fully-annotated example that ships with the repo:

```bash
cp config.example.yaml config.yaml
chmod 600 config.yaml
```

Cairn auto-discovers `config.yaml` / `config.yml` in the current directory. Point
it elsewhere with `-c`:

```bash
cairn -c /etc/cairn/prod.yaml sync
```

> **Why `chmod 600`?** Your config can hold credentials. Cairn refuses to start
> on a **world-readable** config and warns on a **group-readable** one. See
> [Security](security.md).

---

## 4. Enable the sources you use

Open `config.yaml`. Set `mode`, your `source_priority`, enable each source you
use with `enabled: true`, and fill in credentials (or supply secrets via env
vars — see [Security](security.md#supplying-secrets-via-environment-variables)).
Minimal example:

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

Each connector's exact required fields and where to get its credentials are in
[Source connectors](sources.md) and [Sinks & CMDB readers](sinks-and-cmdb.md).
The full schema is in [Configuration](configuration.md).

---

## 5. Validate, test, dry-run, then sync

Always work up this ladder — each step is safer than the next:

```bash
cairn validate       # load config + build every provider; surfaces missing creds
cairn doctor         # actually contacts each system and confirms it's reachable
cairn drift          # read-only: show where your CMDB disagrees with your tools
cairn sync --dry-run # show what a sync WOULD create/update — writes nothing
cairn sync           # do it for real
```

A healthy `cairn doctor` looks like:

```
[OK  ] source:jamf — reachable
[OK  ] source:crowdstrike — reachable
[OK  ] sink:snipeit — reachable

3/3 healthy.
```

A `cairn sync` summary looks like:

```
Cairn fleet run
  devices reconciled: 412
  created: 7  updated: 38  skipped: 367  failed: 0
```

(`skipped` are unchanged devices that incremental sync didn't need to touch.)

---

## 6. Keep it current automatically

Install Cairn as a native scheduled job so it keeps your CMDB up to date without
you:

```bash
cairn schedule install --interval 3600    # sync every hour
cairn schedule status
cairn schedule uninstall                   # when you want to stop
```

See [Scheduling](scheduling.md) for per-OS details and the scheduled drift
digest.

---

## Where things live

| Thing | Location |
|---|---|
| Config | `config.yaml` in the working dir (or `-c PATH`); legacy `settings.conf` still read |
| Incremental sync state | `~/.cairn/state.json` (Windows: `%LOCALAPPDATA%\Cairn`); override with `state_path` or `CAIRN_STATE` |
| Scheduled-job logs (macOS) | `~/Library/Logs/cairn.log` |
| Scheduled-job logs (Linux/Win) | `~/.cairn/cairn.log` |

---

If something doesn't work, go straight to [Troubleshooting](troubleshooting.md) —
it's organized by symptom.

Next: [CLI reference](cli-reference.md).

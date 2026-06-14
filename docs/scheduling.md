# Scheduling (auto-sync & drift digest)

[← Back to docs index](README.md)

Install Cairn as a **native OS scheduled job** so it keeps your CMDB current (or
emails you drift) on its own — no daemon to babysit. Cairn uses the platform's own
scheduler under the hood.

---

## Commands

```bash
cairn schedule install                      # interval from config (or 3600s)
cairn schedule install --interval 3600      # every hour
cairn schedule install --interval 1800 --mode fleet
cairn schedule install --drift --interval 86400   # daily read-only DRIFT digest
cairn schedule status
cairn schedule uninstall
```

| Flag | Description |
|---|---|
| `--interval SECONDS` | Seconds between runs. Defaults to `schedule.interval` in config, else `3600`. |
| `--mode {agent,fleet}` | Mode for the scheduled **sync**. Ignored for `--drift`. |
| `--drift` | Schedule a **read-only drift digest** instead of a sync. |

See [CLI reference → schedule](cli-reference.md#cairn-schedule).

---

## What gets scheduled

The job runs `cairn sync` (or `cairn drift` with `--drift`) **headlessly** with
incremental state, so each scheduled sync only writes the devices that actually
changed. The invocation:

- prefers the installed `cairn` console binary; otherwise falls back to the
  current Python interpreter running the repo entrypoint;
- always uses an **absolute config path** (so it works regardless of the
  scheduler's working directory) — pass `-c` to `cairn schedule install` and that
  path is embedded;
- runs at **low priority** (niced / idle I/O) so it stays out of the way of
  interactive work.

> Because the config path is captured at install time, **re-run
> `cairn schedule install` if you move your config file.**

---

## Per-platform backends

### macOS — launchd LaunchAgent

- Installs `~/Library/LaunchAgents/com.cairn.sync.plist` and loads it.
- Runs at `StartInterval` seconds, background process type, low-priority I/O,
  `Nice 10`.
- Logs to `~/Library/Logs/cairn.log`.
- The plist is written owner-only (`0600`).

```bash
cairn schedule install --interval 3600
cairn schedule status     # "launchd agent at … — loaded"
cairn schedule uninstall
```

### Linux — systemd --user (with cron fallback)

- If `systemctl --user` is available, installs a `cairn.service` (oneshot,
  `Nice 10`, `IOSchedulingClass=idle`) + `cairn.timer` under
  `~/.config/systemd/user/`, and enables the timer.
- **Tip:** run `loginctl enable-linger $USER` so the timer keeps running while
  you're logged out.
- If systemd isn't available, Cairn falls back to a **cron** entry (tagged
  `# cairn-managed` so uninstall can find it). Sub-hour intervals become
  `*/N * * * *`; hour-or-more become `0 */H * * *`.
- Logs to `~/.cairn/cairn.log`.

```bash
cairn schedule install --interval 1800
cairn schedule status     # "systemd --user timer cairn.timer is active." or cron note
cairn schedule uninstall
```

### Windows — Task Scheduler

- Creates a scheduled task named **Cairn** via `schtasks`, running every N
  minutes (the interval is converted to minutes, minimum 1).
- Logs to `~/.cairn/cairn.log`.

```cmd
cairn schedule install --interval 3600
cairn schedule status
cairn schedule uninstall
```

---

## Scheduled drift digest

Instead of (or in addition to) a sync, schedule a **read-only** drift run so your
notifiers deliver a recurring "what's missing/stale/conflicting" digest:

```bash
cairn schedule install --drift --interval 86400    # daily
```

- Drift is always a read-only fleet pull (the `--mode` flag is ignored for
  `--drift`).
- Configure [notifiers](notifiers.md) (Teams/Slack/webhook) to receive the digest;
  without them, the run still happens but only writes to the log.
- The digest title looks like
  `Cairn drift: 7 missing, 3 stale, 2 conflicting, 1 duplicate`.

> `cairn schedule` manages **one** job at a time per platform (it installs/uninstalls
> the `com.cairn.sync` / `cairn.timer` / `Cairn` task). If you want **both** a
> scheduled sync **and** a scheduled drift digest, install one with Cairn and add
> the second with your OS scheduler manually (e.g. a second cron line / launchd
> plist / task) pointing at `cairn drift`.

---

## Verifying & logs

- `cairn schedule status` tells you whether the job exists and is loaded/active.
- Tail the log for the actual run output:
  - macOS: `~/Library/Logs/cairn.log`
  - Linux/Windows: `~/.cairn/cairn.log`
- For systemd you can also use `journalctl --user -u cairn.service`.

---

## See also

- [Configuration → schedule](configuration.md#schedule)
- [Notifiers](notifiers.md)
- [Troubleshooting → scheduling](troubleshooting.md#scheduling)

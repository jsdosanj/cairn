# Troubleshooting

[← Back to docs index](README.md)

Organized by **symptom**. For exact error strings, see the
[Error reference](errors.md). For conceptual questions, see the [FAQ](faq.md).

**First moves for almost any problem:**

```bash
cairn -v doctor      # debug logs + per-connection reachability test
cairn -v validate    # confirms config + credentials are wired correctly
```

`cairn doctor` makes one real call per provider and prints the exact upstream
error — it's the fastest way to localize a failure.

---

## Startup & config

### "is world-readable. Run: chmod 600 …"

Your config is readable by other users. Fix:

```bash
chmod 600 config.yaml
```

### "Config file not found: PATH"

The path you passed with `-c` doesn't exist. Check the path; or drop `-c` and put
`config.yaml` in the working directory (Cairn auto-discovers it).

### "No config file found; relying entirely on environment variables."

Not an error — just informational. Cairn found no `config.yaml`/`config.yml`/
`settings.conf` and will use env vars only. If that's unintended, `cd` to the
directory with your config or pass `-c`.

### "PyYAML is required to read YAML config."

Install it: `pip install pyyaml` (or reinstall Cairn with `pip install -e .`).

### "mode must be 'agent' or 'fleet'"

`mode:` in config is something else. Set it to exactly `agent` or `fleet`.

### "No sinks enabled — nothing to sync into."

You have no enabled sink. Enable the Snipe-IT sink (`sinks.snipeit.enabled: true`)
with a valid `url` + `token`.

### `cairn validate` prints "VALIDATION FAILED: …"

A provider couldn't be constructed — usually a missing required key. The message
names the provider and the missing config. Cross-check against
[Sources](sources.md) / [Sinks & CMDB readers](sinks-and-cmdb.md).

---

## Authentication failures (per connector)

A `401`/`403` or "no access_token" almost always means wrong credentials, wrong
region/URL, or missing API permissions/consent. Run `cairn -v doctor` to see which
connector and the upstream message.

### Jamf

- `must use HTTPS` → your `url` is `http://`. Use `https://`.
- `401` with client creds → the API role/client is wrong or lacks read scope.
  Confirm the **API Roles and Clients** entry has computer read permission.
- Using basic auth? Provide **both** `username` and `password`. Cairn requires
  *either* the client pair *or* the basic pair.

### Intune / Defender (Microsoft Graph & Security Center)

- "Token endpoint returned no access_token" / `401` → wrong `tenant_id`,
  `client_id`, or `client_secret`, or **admin consent not granted**.
- Empty results despite auth OK → the app registration is missing the right
  **application** permission:
  - Intune: `DeviceManagementManagedDevices.Read.All`.
  - Defender: WindowsDefenderATP `Machine.Read.All`.
  Grant the permission **and** admin consent, then retry.

### CrowdStrike

- `401`/empty results → **wrong region `base_url`** is the most common cause. Set
  it to your tenant's region, e.g. `https://api.us-2.crowdstrike.com`,
  `https://api.eu-1.crowdstrike.com`, or the GovCloud host. See
  [Sources → CrowdStrike](sources.md#crowdstrike-falcon--crowdstrike).
- `403` → the API client lacks the **Hosts: Read** scope.

### Sophos

- `401` → wrong `client_id`/`client_secret`. Create them in **Global Settings →
  API Credentials Management**. Cairn auto-discovers your tenant via `whoami`.

### JumpCloud

- `401` → bad `api_key`. Multi-tenant admins must also set `org_id`.

### Kandji

- `missing required config: api_url` / `api_token` → both are required.
- `must use HTTPS` → fix the `api_url` scheme.
- Wrong region → EU tenants use `...api.eu.kandji.io`.

### Google Workspace (ChromeOS)

- Import error / "needs the optional extra" → `pip install 'cairn-sync[google]'`.
- `401`/`403` → domain-wide delegation isn't authorized for the scope. Authorize
  `admin.directory.device.chromeos.readonly` for the service account's client id,
  and make sure `subject` is a real admin to impersonate.

### Apple Business Manager

- Import error → `pip install 'cairn-sync[apple]'`.
- Auth fails → check `client_id`, `key_id`, and that `private_key_file` points to
  the correct `.pem`.

### UniFi

- `must use HTTPS` → `host` must be `https://`.
- TLS error on a self-signed controller → set `verify_ssl: false` **and** export
  `CAIRN_ALLOW_INSECURE_TLS=1`, or better, set `ca_bundle`. See [Security](security.md#tls).

### Snipe-IT

- `401` → bad `token`. Regenerate under **Manage API Keys**.
- `url` issues → it must end in `/api/v1` and be HTTPS.

---

## Empty results / nothing syncs

### `cairn sync` reports 0 devices, no errors

- The source authenticated but returned nothing. Confirm there *are* devices in
  that tool's console for the credential's scope.
- Wrong region/instance (especially CrowdStrike) can authenticate but see an empty
  fleet — double-check `base_url`.
- For agent mode, confirm the local serial is detectable (`cairn -v sync` logs the
  masked local serial; `UNKNOWN` means it couldn't read it).

### Everything shows as "skipped"

That's **incremental sync working as designed** — those devices haven't changed
since the last successful run. To force a full re-sync (e.g. after editing
`field_map`):

```bash
cairn sync --full
```

### A device I expect isn't in the sink

- It may lack a serial (some Defender/Sophos endpoints) — those are synced but not
  merged; check the logs.
- Check `cairn drift` to see whether it's classified as missing/conflicting.

---

## Network discovery finds nothing

See also [Network discovery](network-discovery.md).

- "no ARP table available (tried `ip neigh` and `arp -a`)" → the host has neither
  tool or you lack permission. Run on a host where `arp -a`/`ip neigh` work.
- It only shows devices that recently talked on the segment (passive). Quiet hosts
  won't appear — and **active sweep is a no-op today**, so enabling it won't help.
- Run Cairn on a host **on the segment you care about**; passive discovery only
  sees the local segment.
- `'cidr' must look like 10.0.0.0/24` → fix the CIDR format (it's only needed for
  the future active sweep anyway).

---

## Drift

### Drift exits with code 1

That's **expected when drift exists** — it lets cron/CI alert. Exit `0` means a
clean CMDB. Only `--stale-days` < 0 gives exit `2`.

### "Drift needs a Snipe-IT sink (or a `cmdb:` block) …"

Drift has no system of record to read. Either enable the Snipe-IT sink or add a
`cmdb:` block. See [Sinks & CMDB readers](sinks-and-cmdb.md#choosing-the-cmdb-for-drift).

### "Unknown cmdb backend '<name>'."

`cmdb.backend` must be `snipeit`, `glpi`, or `netbox`. (There is no ServiceNow
backend.)

### Lots of false "stale" findings

The report warns when a source failed to pull — a missing source biases results
toward false stale hits (Cairn thinks those devices vanished). Fix the failing
source (see auth section), then re-run. You can also raise `--stale-days`.

### GLPI reader fails

- "initSession returned no session_token" → wrong `app_token`/`user_token`, or the
  REST API isn't enabled. Enable it in **GLPI → Setup → General → API** and verify
  both tokens.
- `url` must be the API base ending in `apirest.php`.

---

## Writeback

### "Writeback needs a Snipe-IT sink configured to read from."

Writeback reads assets from Snipe-IT. Enable the Snipe-IT sink.

### "No writebacks enabled."

Enable at least one target under `writebacks:` (`jamf` and/or `intune`).

### Devices show as "skipped"

Expected when: the value already matches, the policy is `only_if_empty` and the
field is non-blank, or the MDM has no device with that serial. Writeback never
creates devices.

### "conflict must be 'snipe_wins' or 'only_if_empty'"

Fix the `conflict` value on that writeback target.

### Intune writeback fails for a custom `target_field`

Some fields need the Graph **beta** endpoint / extra permissions. `notes` works on
v1.0. Ensure the app has **write** permission on managed devices.

---

## Scheduling

### `cairn schedule status` says "not scheduled" right after install

- **Linux/cron fallback:** if systemd wasn't available, check `crontab -l` for the
  `# cairn-managed` line.
- **macOS:** "installed but not loaded" means the plist exists but launchd didn't
  load it — try `cairn schedule uninstall && cairn schedule install …`.

### Scheduled job runs but uses the wrong config

The config path is captured at install time. If you moved the file, re-run
`cairn schedule install -c /new/path/config.yaml …`.

### Linux timer doesn't run when I'm logged out

Run `loginctl enable-linger $USER` so the `systemd --user` timer persists.

### Where are the scheduled-run logs?

macOS: `~/Library/Logs/cairn.log`. Linux/Windows: `~/.cairn/cairn.log`. systemd
also: `journalctl --user -u cairn.service`.

---

## Rate limits & flaky networks

Cairn already retries `429, 500, 502, 503, 504` with backoff and respects
`Retry-After`. If a source is **still** rate-limited:

- Increase the run interval (`cairn schedule install --interval …`).
- Rely on incremental sync so each run does less work.
- Lower `page_size` for the noisy source if its API penalizes large pages.

A persistent `HttpError … -> 429` after retries means the upstream limit is
tighter than the backoff window — slow down the cadence.

---

## TLS / certificate errors

`SSLError` / certificate verify failed against an internal instance:

1. **Preferred:** `ca_bundle: /path/to/internal-ca.pem` on that provider.
2. **Last resort:** `verify_ssl: false` **and** `export CAIRN_ALLOW_INSECURE_TLS=1`
   (logs a loud warning; exposes credentials to MITM).

See [Security → TLS](security.md#tls).

---

## Notifications

- No message arriving → check the notifier is `enabled: true` and the
  `webhook_url`/`url` is correct and **HTTPS**.
- Notifier errors are logged (`notifier <key> failed`) but never fail the run — run
  `cairn -v sync` to see them.

---

## "Unexpected failure: …" (exit 1)

An unhandled error. Re-run with `-v` for a full traceback, then check the
[Error reference](errors.md) or file an issue with the (masked) output.

---

Still stuck? See the [FAQ](faq.md) and [Error reference](errors.md).

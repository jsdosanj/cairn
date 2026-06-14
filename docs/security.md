# Security & privacy

[← Back to docs index](README.md)

Cairn handles credentials for every system it touches and emits device data, so it
defaults to the safe choice everywhere. This page documents exactly what it does.

---

## Credential handling

A config value can be supplied three ways, in this precedence:

1. **Environment variable** (highest) — keep secrets out of files entirely.
2. **`config.yaml`** value.
3. **`keyring:NAME`** reference — resolved from the OS keychain.

### Config file permissions

Because a config can hold credentials, Cairn checks its permissions on start
(POSIX):

- **World-readable** config ⇒ Cairn **refuses to start**:
  `… is world-readable. Run: chmod 600 …`
- **Group-readable** config ⇒ Cairn **warns** (`Consider chmod 600`).

Always `chmod 600 config.yaml`. (On Windows this check is skipped.)

### Supplying secrets via environment variables

**Any** value can be overridden by an env var, so production deployments need no
secrets on disk:

```bash
# Generic nested form — CAIRN_<section>__<provider>__<key>  (double underscores):
export CAIRN_sources__crowdstrike__client_secret=...
export CAIRN_sinks__snipeit__token=...
export CAIRN_sources__jamf__client_id=...

# Legacy GhostAssetSync vars (still honored, and they auto-enable that provider):
export GHOST_JAMF_URL=...
export GHOST_JAMF_USER=...
export GHOST_JAMF_PASSWORD=...
export GHOST_SNIPE_URL=...
export GHOST_SNIPE_TOKEN=...
export TEAMS_WEBHOOK_URL=...
```

The section/provider/key path is lowercased; the leaf is the config key.

### OS keychain (`keyring:`)

For desktop users who want secrets out of plaintext but not in env vars, set a
value to `keyring:NAME`; Cairn looks `NAME` up in the OS keychain (macOS Keychain,
Windows Credential Manager, libsecret on Linux) under the service `cairn`:

```yaml
sinks:
  snipeit:
    token: keyring:snipe_token
```

Requires the optional extra: `pip install 'cairn-sync[secrets]'`. The setup wizard
can store secrets here for you. If the keychain isn't available, use env vars.

### Masking in the web dashboard

`cairn web` masks secret fields (`********`) when echoing config back to the
browser, and guards API calls with a random per-session token. It is **localhost
protection, not authentication** — don't expose the dashboard to an untrusted
network (keep `--host 127.0.0.1`).

---

## Serial masking

Serial numbers identify a physical machine and seed warranty lookups, so Cairn
treats them as mildly sensitive: **only the last 4 characters appear** in logs,
the drift report, and notifier digests (`****9F2A`; short serials are fully
starred). Override only when you need to act on full serials:

```bash
cairn drift --show-serials
```

Full serials are of course written to your CMDB as the actual asset serial — the
masking is about *display* (logs/reports/chat), not storage.

---

## TLS

- **HTTPS is enforced** on every API and webhook URL. A plaintext URL is rejected
  (localhost is exempt so you can develop against a local instance).
- **TLS verification is on by default.** For internal/self-signed PKI, set
  `ca_bundle: /path/to/ca.pem` on the provider — the right way to trust a private
  CA.
- `verify_ssl: false` is **ignored** (verification stays on) **unless** you also
  set `CAIRN_ALLOW_INSECURE_TLS=1` in the environment, in which case Cairn logs a
  loud warning naming the host. Disabling verification exposes credentials to
  man-in-the-middle attacks — prefer `ca_bundle`.
- **Redirects are not followed.** A 3xx response is treated as an error, because
  following it would resend your `Authorization` header to whatever host the
  server names in `Location` (an SSRF / credential-leak vector). Retry/backoff
  respects `Retry-After`.
- **Server-supplied pagination URLs are origin-pinned.** The NetBox reader pages
  via the `next` URL in the response body; Cairn only follows it if it stays on
  the configured origin (same scheme + host + port), so a compromised CMDB can't
  redirect your API token to an attacker host.

---

## No-scan-by-default

The [network discovery](network-discovery.md) source never scans a network unless
you explicitly opt in:

- By default it only **reads the local ARP cache** (already populated by normal
  traffic) and sends **no packets of its own**.
- Active sweeping is **doubly gated** (requires both a `cidr` *and*
  `active_sweep: true`) — and is currently a **safe no-op TODO** that sends no
  packets regardless. So Cairn cannot accidentally scan or probe a network.

---

## Data handling & footprint

- **State** (`~/.cairn/state.json`) stores per-device content **hashes** (not
  device data) for incremental sync, and is written owner-only (`0600`).
  Override with `state_path` / `CAIRN_STATE`.
- **Scheduler artifacts** (plist / unit files) are written owner-only — they name
  your config path and invocation.
- `cairn drift` and `cairn sync --dry-run` are **read-only** — they never write to
  your CMDB or MDM.
- Cairn only talks to the endpoints you configure; there is no telemetry.

---

## Reporting vulnerabilities

Report security issues via a GitHub issue tagged `[SECURITY]`.

---

## License note

Cairn is **AGPL-3.0-or-later** (matching Snipe-IT). If you modify Cairn and run it
as a network service, you must make your modified source available to its users.
Running it internally to sync your own fleet changes nothing for you.

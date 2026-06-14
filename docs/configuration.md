# Configuration reference

[← Back to docs index](README.md)

This is the complete config schema with an annotated example. Per-connector
credential details are in [Source connectors](sources.md),
[Sinks & CMDB readers](sinks-and-cmdb.md), and [Notifiers](notifiers.md).

---

## File format & discovery

Configuration is YAML. Cairn looks for, in order, in the working directory:

1. `config.yaml`
2. `config.yml`
3. `settings.conf` (legacy GhostAssetSync INI — auto-translated)

Override with `-c PATH`. If no file is found, Cairn relies entirely on
environment variables.

The top level must be a **mapping** (a YAML dict). Any value can be overridden by
an environment variable — see [Security → secrets](security.md#supplying-secrets-via-environment-variables).

**Precedence (highest wins):** environment variables → `config.yaml` → legacy
`settings.conf`.

---

## Top-level keys

| Key | Type | Default | Purpose |
|---|---|---|---|
| `mode` | `agent` \| `fleet` | `fleet` | Run mode. See [Concepts → modes](concepts.md#run-modes-fleet-vs-agent). |
| `source_priority` | list of source keys | a built-in order | Trust order for [reconciliation](concepts.md#reconciliation-merging-by-serial). |
| `defaults` | mapping | `{}` | Org-level defaults applied to created assets (sinks read these). |
| `incremental` | bool | `true` | Enable incremental sync (skip unchanged devices). |
| `incremental_ignore_fields` | list of field names | `[last_seen]`* | Fields that don't count as a "change". |
| `state_path` | path | `~/.cairn/state.json` | Where incremental state lives. |
| `schedule` | mapping | `{interval: 3600}` | Default cadence for `cairn schedule install`. |
| `sources` | mapping | `{}` | Source connectors (keyed by source name). |
| `sinks` | mapping | `{}` | Sinks. Today: `snipeit`. **At least one sink must be enabled.** |
| `cmdb` | mapping | (uses the Snipe-IT sink) | Override which system of record `cairn drift` reads. See [Sinks & CMDB readers](sinks-and-cmdb.md#choosing-the-cmdb-for-drift). |
| `notifiers` | mapping | `{}` | Teams / Slack / webhook run summaries. |
| `writebacks` | mapping | `{}` | Reverse-sync targets for `cairn writeback`. |

\* `incremental_ignore_fields` defaults to excluding `last_seen` from the change
hash *(via the example/state defaults)*. Set it explicitly to be sure.

---

## Enabling / disabling entries

Inside any section (`sources`, `sinks`, `notifiers`, `writebacks`), each entry is
a mapping keyed by its provider name. An entry is **enabled unless it has
`enabled: false`**. Disabled entries are skipped entirely (and their optional
dependencies are never imported).

```yaml
sources:
  jamf:
    enabled: true        # processed
    url: ...
  sophos:
    enabled: false       # ignored
```

> If you supply a provider's secret via a legacy env var (e.g. `GHOST_JAMF_URL`),
> that provider is automatically marked enabled.

---

## `source_priority` and reconciliation

```yaml
source_priority: [intune, jamf, jumpcloud, crowdstrike, sophos, defender]
```

Earlier sources win field-by-field; empty fields are backfilled from later ones.
Sources not listed sort last. Tune this to your trust order — MDMs usually own
ownership/hardware metadata, EDRs usually have fresher last-seen and security
posture. Full mechanics: [Concepts → reconciliation](concepts.md#reconciliation-merging-by-serial).

The built-in default order (used when you omit `source_priority`) is:

```
intune, jamf, kandji, jumpcloud, google_workspace, apple_bm, crowdstrike,
sophos, defender, rudder, unifi, cdw, network_discovery
```

---

## `defaults` — created-asset defaults

These are applied by sinks to **newly created** assets:

```yaml
defaults:
  status_id: 2      # Snipe-IT status label id for new assets (e.g. "Deployed"/"Ready")
  company_id: 1     # Snipe-IT company id
  site_id: 1        # Snipe-IT site/location id
```

A sink reads these from `_defaults` and a same-named key in the sink block
overrides the default. The numeric ids must match your Snipe-IT instance.

---

## Efficiency — incremental sync

Cairn stores a per-device **content hash** and skips devices that haven't changed
since the last successful sync, so a scheduled run only writes real changes.

```yaml
incremental: true
# Where the state lives (default: ~/.cairn/state.json; Windows: %LOCALAPPDATA%\Cairn).
# state_path: /var/lib/cairn/state.json
# Fields that should NOT count as a change (they tick constantly).
incremental_ignore_fields: [last_seen]
```

- The hash is computed over the device's fields; `last_seen` is excluded by
  default so a routine check-in doesn't trigger a needless write.
- A device is only recorded as "synced" when **every** sink accepted it **and**
  it was a real (non-dry-run) write, so failures retry next run.
- Force a full re-sync with `cairn sync --full` (ignores the state).
- State path can also be set with the `CAIRN_STATE` environment variable.

State file is written owner-only (`0600`) on POSIX.

---

## `schedule`

```yaml
schedule:
  interval: 3600   # seconds; default cadence for `cairn schedule install`
```

Only the default interval lives here; the actual job is created by
[`cairn schedule install`](scheduling.md).

---

## `sources`

Each source has its own required keys — see [Source connectors](sources.md) for
exact credentials per connector. Common optional keys honored by HTTP-based
sources:

| Key | Meaning |
|---|---|
| `enabled` | `false` to skip the source. |
| `page_size` | Page size for paged APIs (provider-specific default). |
| `verify_ssl` | `false` to attempt to disable TLS verification (see caveat below). |
| `ca_bundle` | Path to a custom CA bundle for self-signed / internal PKI. |
| `asset_type` | Override the asset class this source emits (e.g. network discovery / CDW). |

> **TLS:** `verify_ssl: false` is **ignored** (verification stays ON) unless you
> also set `CAIRN_ALLOW_INSECURE_TLS=1` in the environment, in which case Cairn
> logs a loud warning. Prefer `ca_bundle`. See [Security](security.md#tls).

---

## `sinks`

Today there is one sink, Snipe-IT. **At least one sink must be enabled** or Cairn
raises `No sinks enabled — nothing to sync into.`

```yaml
sinks:
  snipeit:
    enabled: true
    url: https://your-snipe-it-instance/api/v1
    token: YOUR_SNIPEIT_API_TOKEN
    default_model_id: 1          # model id used for new assets when none matches
    status_id: 2                 # overrides defaults.status_id for this sink
    # company_id / site_id likewise override the defaults block
    field_map:                   # Snipe-IT custom-field label -> device attribute
      "Operating System": os_name
      "OS Version": os_version
      "OS Build": os_build
      "MAC Address": mac_addresses
      "Last Seen": last_seen
      "Source": source
```

Field mapping details: [Sinks & CMDB readers → field mapping](sinks-and-cmdb.md#snipe-it-custom-field-mapping).

---

## `notifiers`

```yaml
notifiers:
  teams:
    enabled: false
    webhook_url: https://outlook.office.com/webhook/your-webhook-url
  slack:
    enabled: false
    webhook_url: https://hooks.slack.com/services/XXXX/YYYY/ZZZZ
  webhook:
    enabled: false
    url: https://example.com/collector
    headers:
      X-Api-Key: optional-shared-secret
```

All notifier URLs must be HTTPS. Details: [Notifiers](notifiers.md).

---

## `writebacks`

Reverse-sync targets for `cairn writeback`. They read from the Snipe-IT sink
above and push the asset tag into the MDM:

```yaml
writebacks:
  jamf:
    enabled: false
    url: https://your.jamf.instance.com
    client_id: YOUR_JAMF_API_CLIENT_ID
    client_secret: YOUR_JAMF_API_CLIENT_SECRET
    conflict: snipe_wins              # writes Snipe-IT tag -> Jamf general.assetTag
  intune:
    enabled: false
    tenant_id: YOUR_AZURE_TENANT_ID
    client_id: YOUR_APP_REGISTRATION_CLIENT_ID
    client_secret: YOUR_APP_REGISTRATION_SECRET
    target_field: notes               # Intune managedDevice field to write
    conflict: only_if_empty
```

`conflict` is `snipe_wins` (overwrite) or `only_if_empty` (only fill blanks).
Details: [Writeback](writeback.md).

---

## `cmdb` — drift's system of record (optional)

By default `cairn drift` reads the system of record from your enabled Snipe-IT
sink, so existing setups need nothing. To point drift at GLPI or NetBox instead:

```yaml
cmdb:
  backend: netbox            # snipeit (default) | glpi | netbox
  url: https://netbox.example.com
  token: ...
```

Details and per-backend credentials: [Sinks & CMDB readers](sinks-and-cmdb.md#choosing-the-cmdb-for-drift).

---

## Complete annotated example

This mirrors the repo's `config.example.yaml`. Enable only the sources you use.

```yaml
# agent = run on one endpoint, sync only this machine.
# fleet = run centrally, pull every device from every source and sync the fleet.
mode: fleet

# Trust order for reconciliation. Earlier sources win field-by-field; empty
# fields are then filled from later sources.
source_priority: [intune, jamf, jumpcloud, crowdstrike, sophos, defender]

# Defaults applied to newly CREATED assets (sinks read these).
defaults:
  status_id: 2
  company_id: 1
  site_id: 1

# Incremental sync: skip devices that haven't changed since the last good run.
incremental: true
# state_path: /var/lib/cairn/state.json
incremental_ignore_fields: [last_seen]

# Default cadence used by `cairn schedule install` when --interval is omitted.
schedule:
  interval: 3600   # seconds (1 hour)

# ---------------- SOURCES (enable only what you use) ----------------
sources:
  jamf:
    enabled: false
    url: https://your.jamf.instance.com
    client_id: YOUR_JAMF_API_CLIENT_ID         # preferred: API role client creds
    client_secret: YOUR_JAMF_API_CLIENT_SECRET
    # username: YOUR_JAMF_API_USER             # OR basic auth (less preferred)
    # password: YOUR_JAMF_API_PASSWORD

  intune:
    enabled: false
    tenant_id: YOUR_AZURE_TENANT_ID
    client_id: YOUR_APP_REGISTRATION_CLIENT_ID
    client_secret: YOUR_APP_REGISTRATION_SECRET

  jumpcloud:
    enabled: false
    api_key: YOUR_JUMPCLOUD_API_KEY
    # org_id: YOUR_ORG_ID                       # only for multi-tenant admin

  crowdstrike:
    enabled: false
    client_id: YOUR_FALCON_CLIENT_ID
    client_secret: YOUR_FALCON_CLIENT_SECRET
    base_url: https://api.crowdstrike.com       # region-specific (us-2/eu-1/gov)

  sophos:
    enabled: false
    client_id: YOUR_SOPHOS_CLIENT_ID
    client_secret: YOUR_SOPHOS_CLIENT_SECRET

  defender:
    enabled: false
    tenant_id: YOUR_AZURE_TENANT_ID
    client_id: YOUR_APP_REGISTRATION_CLIENT_ID
    client_secret: YOUR_APP_REGISTRATION_SECRET

  kandji:
    enabled: false
    api_url: https://YOUR_SUBDOMAIN.api.kandji.io   # EU: ...api.eu.kandji.io
    api_token: YOUR_KANDJI_API_TOKEN

  google_workspace:
    enabled: false
    customer_id: my_customer
    subject: admin@yourdomain.com                   # admin email to impersonate
    service_account_file: /path/to/service-account.json

  apple_bm:
    enabled: false
    client_id: YOUR_ABM_CLIENT_ID
    key_id: YOUR_PRIVATE_KEY_ID
    private_key_file: /path/to/abm-key.pem

  unifi:
    enabled: false
    host: https://192.168.1.1                       # UniFi OS controller
    api_key: YOUR_UNIFI_API_KEY
    verify_ssl: true

  cdw:
    enabled: false
    csv_file: /path/to/cdw-orders.csv
    # columns:                                      # override to match your headers
    #   serial: "Serial Number"
    #   model: "Product Description"

  rudder:
    enabled: false
    url: https://rudder.example.com
    api_token: YOUR_RUDDER_API_TOKEN
    verify_ssl: true

  # Local network discovery (passive ARP). No credentials. See network-discovery.md.
  network_discovery:
    enabled: false
    # cidr: 10.0.0.0/24       # OPTIONAL, only to opt in to active sweep (no-op today)
    # active_sweep: false     # active sweep is a documented no-op TODO; passive only

# ---------------- SINKS (where reconciled devices are written) ----------------
sinks:
  snipeit:
    enabled: true
    url: https://your-snipe-it-instance/api/v1
    token: YOUR_SNIPEIT_API_TOKEN
    default_model_id: 1
    field_map:
      "Operating System": os_name
      "OS Version": os_version
      "OS Build": os_build
      "MAC Address": mac_addresses
      "Last Seen": last_seen
      "Source": source

# ---------------- NOTIFIERS (optional run summaries) ----------------
notifiers:
  teams:
    enabled: false
    webhook_url: https://outlook.office.com/webhook/your-webhook-url
  slack:
    enabled: false
    webhook_url: https://hooks.slack.com/services/XXXX/YYYY/ZZZZ
  webhook:
    enabled: false
    url: https://example.com/collector
    headers:
      X-Api-Key: optional-shared-secret

# ---------------- WRITEBACKS (reverse sync: Snipe-IT tag -> MDM) ----------------
writebacks:
  jamf:
    enabled: false
    url: https://your.jamf.instance.com
    client_id: YOUR_JAMF_API_CLIENT_ID
    client_secret: YOUR_JAMF_API_CLIENT_SECRET
    conflict: snipe_wins
  intune:
    enabled: false
    tenant_id: YOUR_AZURE_TENANT_ID
    client_id: YOUR_APP_REGISTRATION_CLIENT_ID
    client_secret: YOUR_APP_REGISTRATION_SECRET
    target_field: notes
    conflict: only_if_empty

# ---------------- CMDB for drift (OPTIONAL; defaults to the Snipe-IT sink) -------
# cmdb:
#   backend: netbox          # snipeit | glpi | netbox
#   url: https://netbox.example.com
#   token: ...
```

Next: [Source connectors](sources.md).

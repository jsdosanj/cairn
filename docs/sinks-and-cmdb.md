# Sinks & CMDB readers

[← Back to docs index](README.md)

This page covers:

1. The **Snipe-IT sink** — where `cairn sync` writes reconciled devices.
2. The **CMDB readers** — Snipe-IT, GLPI, and NetBox — which `cairn drift` reads
   as the system of record, and which writeback reads from.

---

## Snipe-IT sink — `snipeit`

Today there is one sink. `cairn sync` writes every reconciled device into
Snipe-IT, creating or updating by serial number. **At least one sink must be
enabled** or Cairn refuses to run.

### Configuration

```yaml
sinks:
  snipeit:
    enabled: true
    url: https://your-snipe-it-instance/api/v1
    token: YOUR_SNIPEIT_API_TOKEN
    default_model_id: 1          # model id for new assets when no match is found
    status_id: 2                 # status label id for new assets (overrides defaults)
    company_id: 1                # optional; overrides defaults.company_id
    site_id: 1                   # optional; overrides defaults.site_id
    field_map:
      "Operating System": os_name
      "OS Version": os_version
      "OS Build": os_build
      "MAC Address": mac_addresses
      "Logged In Users": logged_in_users
      "Last Seen": last_seen
      "Source": source
```

| Key | Required | Notes |
|---|---|---|
| `url` | ✅ | Snipe-IT API base, ending in `/api/v1`. Must be HTTPS. |
| `token` | ✅ | A Snipe-IT API token (a personal access token). Sent as `Authorization: Bearer …`. |
| `default_model_id` | — | Default `1`. Used for new assets when no matching model is found. |
| `status_id` | — | Status label id for new assets. Falls back to `defaults.status_id`, then `2`. |
| `company_id` / `site_id` | — | Attached to new assets when set (from here or `defaults`). |
| `field_map` | — | Snipe-IT custom-field label → device attribute (see below). |

**Get a token:** in Snipe-IT, **(your account) → Manage API Keys → Create New
Token**. The user owning the token needs create/update permission on hardware.

### How upsert works

For each device:

1. Cairn searches Snipe-IT for the **serial** and confirms an exact match.
2. **If found:** updates the asset's name and your mapped custom fields (keeps the
   existing asset tag).
3. **If not found:** creates a new asset — generates an asset tag, finds or
   defaults the model, applies `status_id`/`company_id`/`site_id`, and writes the
   custom fields.

Asset-tag generation for new assets: Cairn first tries to extract a 4+ digit
number embedded in the hostname; otherwise it builds `CASID-<last 6 of serial,
zero-padded>` (or `CASID-000000` for unknown serials).

> Snipe-IT sometimes returns `{"status":"error"}` with HTTP **200** on validation
> errors (e.g. a duplicate asset tag, a required custom field). Cairn detects this
> and reports the device as `failed` with Snipe-IT's message. See
> [Troubleshooting → Snipe-IT](troubleshooting.md#snipe-it).

### Snipe-IT custom-field mapping

`field_map` maps a Snipe-IT **custom-field label** (exactly as it appears in
Snipe-IT) to either a device attribute name or a nested `extra.<source>.<key>`
path. This lets you decide what lands where without touching code.

```yaml
field_map:
  "Operating System": os_name
  "OS Version": os_version
  "MAC Address": mac_addresses                       # lists are joined with ", "
  "Falcon Risk": extra.crowdstrike.reduced_functionality_mode
```

- The **label** on the left must match the custom field's name in Snipe-IT.
- The **path** on the right is resolved on the `NormalizedDevice`: a top-level
  attribute (`os_name`, `hostname`, `last_seen`, `source`, …) or a dotted path
  into `extra` (`extra.<source>.<key>`).
- List values (like `mac_addresses`) are joined with `", "`.
- Values are sanitized (control characters stripped) and truncated to 255 chars.

If you omit `field_map`, a sensible default map is used (OS / version / build /
MAC / logged-in users / last seen / source).

---

## CMDB readers (for drift and writeback)

The [drift report](drift.md) needs to read your **system of record** to compare
it against what your tools see. By default that's your Snipe-IT sink, but you can
point it at GLPI or NetBox instead. Each reader produces the same
`NormalizedDevice` list, so the engine doesn't care which backend you use.

### Choosing the CMDB for drift

By default, `cairn drift` reuses your enabled Snipe-IT **sink** credentials as the
reader — existing setups need no extra config. To use a different backend, add a
top-level `cmdb:` block:

```yaml
cmdb:
  backend: netbox            # snipeit (default) | glpi | netbox
  url: https://netbox.example.com
  token: ...
```

If `backend` is `snipeit` and you provide a `cmdb` block, it uses that block's
credentials instead of the sink's. If `backend` names an unknown reader, drift
fails with `Unknown cmdb backend '<name>'.` If neither a Snipe-IT sink nor a
`cmdb` block is configured, drift errors with a message telling you to add one.

---

### Snipe-IT (read) — `snipeit`

Reads hardware assets out of Snipe-IT into `NormalizedDevice`. Used as the
default drift CMDB and as the source for [writeback](writeback.md). Also usable as
a normal source if you want to copy one Snipe-IT into another sink.

| Key | Required | Notes |
|---|---|---|
| `url` | ✅ | Snipe-IT API base (`.../api/v1`). HTTPS. |
| `token` | ✅ | Snipe-IT API token. |
| `page_size` | — | Default `500`. |

Maps serial, asset tag, name → hostname, model, manufacturer.

---

### GLPI (read) — `glpi`

GLPI is the dominant open-source ITAM/ITSM outside Snipe-IT. Reads the `Computer`
itemtype.

| Key | Required | Notes |
|---|---|---|
| `url` | ✅ | The GLPI **API base**, e.g. `https://glpi.example.com/apirest.php`. HTTPS. |
| `app_token` | ✅ | The API client's **App-Token**. |
| `user_token` | ✅ | A **user API token** (exchanged for a short-lived session token). |
| `page_size` | — | Default `200`. |

```yaml
cmdb:
  backend: glpi
  url: https://glpi.example.com/apirest.php
  app_token: YOUR_APP_TOKEN
  user_token: YOUR_USER_TOKEN
```

**Auth flow:** GLPI uses session-token auth — Cairn exchanges your `app_token` +
`user_token` for a `Session-Token` via `/initSession`, then carries both on every
call. **Enable the REST API and create an App-Token** in **GLPI → Setup → General
→ API**, and generate a **personal API token** on your user profile. The GLPI
asset id is surfaced as `asset_tag` so drift can point you at the right record;
foreign keys (manufacturer/model/OS) are resolved to names via
`expand_dropdowns`.

---

### NetBox (read) — `netbox`

NetBox is the de-facto open-source source-of-truth for network/datacenter
inventory. Reads `/api/dcim/devices/`.

| Key | Required | Notes |
|---|---|---|
| `url` | ✅ | NetBox base URL, e.g. `https://netbox.example.com`. HTTPS. |
| `token` | ✅ | A NetBox API token (sent as `Authorization: Token …`). |
| `page_size` | — | Default `200`. |

```yaml
cmdb:
  backend: netbox
  url: https://netbox.example.com
  token: YOUR_NETBOX_TOKEN
```

The NetBox device **name** lands in both `asset_tag` and `hostname`; serial is the
join key when present; nested `device_type.manufacturer.name`, primary IP, status,
and site are flattened in.

---

## Not available

- **ServiceNow** — there is no ServiceNow sink or CMDB reader today.
- Sinks other than Snipe-IT — only Snipe-IT can be *written to* today; GLPI and
  NetBox are read-only CMDB readers (for drift), not sinks.

---

Next: [Drift & reconciliation report](drift.md).

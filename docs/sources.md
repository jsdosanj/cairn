# Source connectors

[← Back to docs index](README.md)

A **source** is a system Cairn reads device data out of. Enable the ones you use
under `sources:` in your config; disabled ones are ignored and their optional
dependencies are never loaded.

This page lists every source, its **required** and **optional** config keys, and
where to get its credentials. For the network discovery source (which has no
credentials but special safety gating), see its own page:
[Network discovery](network-discovery.md).

Snipe-IT, GLPI, and NetBox can also be sources (used by drift/writeback) — they
are documented in [Sinks & CMDB readers](sinks-and-cmdb.md).

---

## Common notes for all HTTP sources

- **HTTPS is enforced** on every URL (localhost exempt for dev). A plaintext URL
  raises an error.
- **Retry/backoff** is automatic on `429, 500, 502, 503, 504`, and `Retry-After`
  is respected.
- Optional per-source keys: `enabled`, `page_size`, `verify_ssl`, `ca_bundle`,
  `asset_type`. See [Configuration → sources](configuration.md#sources).
- Test any source live with `cairn doctor` (it pulls one device).

---

## Jamf Pro — `jamf`

macOS/iOS MDM. Pulls computer inventory.

**Auth (one of):**

- **API role client credentials (preferred):** `client_id` + `client_secret`.
- **Basic auth (less preferred):** `username` + `password`.

| Key | Required | Notes |
|---|---|---|
| `url` | ✅ | Your Jamf Pro base URL, e.g. `https://your.jamf.instance.com`. |
| `client_id` / `client_secret` | ✅* | API role client. Create under **Settings → API Roles and Clients**. |
| `username` / `password` | ✅* | Alternative to client creds; a Jamf API account. |
| `page_size` | — | Default `100`. |

\* Provide *either* the client pair *or* the basic pair.

```yaml
sources:
  jamf:
    enabled: true
    url: https://your.jamf.instance.com
    client_id: ...
    client_secret: ...
```

---

## Microsoft Intune (Graph) — `intune`

Windows/macOS/mobile MDM via Microsoft Graph. Pulls `managedDevices`.

| Key | Required | Notes |
|---|---|---|
| `tenant_id` | ✅ | Azure AD / Entra tenant id. |
| `client_id` | ✅ | App registration (client) id. |
| `client_secret` | ✅ | App registration secret. |
| `graph_base` | — | Default `https://graph.microsoft.com/v1.0`. |
| `login_base` | — | Default `https://login.microsoftonline.com`. |

**Setup:** register an app in Entra, grant **application** permission
`DeviceManagementManagedDevices.Read.All`, and grant admin consent. Cairn uses
OAuth2 client-credentials with scope `https://graph.microsoft.com/.default`.

---

## Microsoft Defender for Endpoint — `defender`

EDR. Pulls the machine list from the Security Center API.

| Key | Required | Notes |
|---|---|---|
| `tenant_id` | ✅ | Entra tenant id. |
| `client_id` | ✅ | App registration id. |
| `client_secret` | ✅ | App registration secret. |
| `api_base` | — | Default `https://api.securitycenter.microsoft.com`. |
| `login_base` | — | Default `https://login.microsoftonline.com`. |

**Setup:** grant the app the **WindowsDefenderATP** application permission
`Machine.Read.All` and admin consent. Scope used:
`https://api.securitycenter.microsoft.com/.default`.

> Some Defender endpoints have no serial; those records are still synced but not
> merged by serial. Primary/logged-on user is not pulled (it requires a separate
> per-machine call and is intentionally out of scope).

---

## CrowdStrike Falcon — `crowdstrike`

EDR. Pulls the device fleet. **Region-specific** base URL.

| Key | Required | Notes |
|---|---|---|
| `client_id` | ✅ | Falcon API client id. |
| `client_secret` | ✅ | Falcon API client secret. |
| `base_url` | — | Default `https://api.crowdstrike.com`. Set per region: `https://api.us-2.crowdstrike.com`, `https://api.eu-1.crowdstrike.com`, `https://api.laggar.gcw.crowdstrike.com` (GovCloud). |
| `page_size` | — | Defaults to the API max query limit. |

**Setup:** in the Falcon console create an **API client** with the **Hosts: Read**
scope. Using the wrong region `base_url` is the #1 cause of `401`/empty results —
see [Troubleshooting](troubleshooting.md#crowdstrike).

---

## Sophos Central — `sophos`

EDR. Pulls endpoints across your Sophos Central tenant.

| Key | Required | Notes |
|---|---|---|
| `client_id` | ✅ | Sophos Central API credential client id. |
| `client_secret` | ✅ | Sophos Central API credential secret. |

Token URL is `https://id.sophos.com/api/v2/oauth2/token` (scope `token`); Cairn
discovers your tenant via the Sophos `whoami` endpoint automatically. Create API
credentials in **Sophos Central → Global Settings → API Credentials Management**.

---

## JumpCloud — `jumpcloud`

Directory + device management. Pulls `/systems`.

| Key | Required | Notes |
|---|---|---|
| `api_key` | ✅ | A JumpCloud API key (user or admin). |
| `org_id` | — | Only for multi-tenant (MTP) admins; sent as `x-org-id`. |
| `base_url` | — | Default `https://console.jumpcloud.com/api`. |

---

## Kandji — `kandji`

Apple MDM. Pulls `/api/v1/devices`.

| Key | Required | Notes |
|---|---|---|
| `api_url` | ✅ | Your Kandji API base, e.g. `https://YOUR_SUBDOMAIN.api.kandji.io` (EU: `...api.eu.kandji.io`). |
| `api_token` | ✅ | API token from **Settings → Access → API Token**. |
| `page_size` | — | Defaults to the Kandji max. |

---

## Google Workspace (ChromeOS) — `google_workspace`

Pulls **ChromeOS** devices via the Admin SDK Directory API.

> Requires the optional extra: `pip install 'cairn-sync[google]'`.

| Key | Required | Notes |
|---|---|---|
| `subject` | ✅ | The admin email to impersonate (domain-wide delegation). |
| `service_account_file` **or** `service_account_info` | ✅ | Path to (or inline JSON of) a service-account key. |
| `customer_id` | — | Default `my_customer`. |
| `page_size` | — | Provider default. |

**Setup:** create a service account, enable **domain-wide delegation**, and in the
Workspace Admin console authorize the scope
`https://www.googleapis.com/auth/admin.directory.device.chromeos.readonly` for
its client id.

---

## Apple Business Manager — `apple_bm`

Pulls device records from Apple Business Manager (ABM).

> Requires the optional extra: `pip install 'cairn-sync[apple]'`.

| Key | Required | Notes |
|---|---|---|
| `client_id` | ✅ | ABM API client id. |
| `key_id` | ✅ | Private key id. |
| `private_key_file` **or** `private_key` | ✅ | Path to (or inline contents of) the `.pem` private key. |
| `api_base` | — | Default `https://api-business.apple.com`. |
| `token_url` | — | Default `https://account.apple.com/auth/oauth2/token`. |
| `scope` | — | Default `business.api`. |

Cairn signs a client-assertion JWT with your private key to obtain a token. Set
up an API account in **ABM → Preferences → API**.

---

## UniFi — `unifi`

Network gear from a UniFi OS controller.

| Key | Required | Notes |
|---|---|---|
| `host` | ✅ | Controller URL, e.g. `https://192.168.1.1`. Must be HTTPS. |
| `api_key` | ✅ | UniFi API key (sent as `X-API-KEY`). |
| `site` | — | Restrict to a specific site. |
| `verify_ssl` | — | `false` for self-signed certs (subject to the TLS opt-in — see [Security](security.md#tls)). |
| `page_size` | — | Provider default. |

Emits `asset_type: network` records.

---

## CDW (procurement CSV import) — `cdw`

Imports a **CDW order/invoice CSV export** so newly purchased gear lands in your
CMDB before it's ever enrolled. No network calls — reads a local file.

| Key | Required | Notes |
|---|---|---|
| `csv_file` | ✅ | Path to the CDW CSV export. |
| `delimiter` | — | Default `,`. |
| `asset_type` | — | Default `computer`. |
| `columns` | — | Map your export's headers to fields, e.g. `serial: "Serial Number"`, `model: "Product Description"`. |

```yaml
sources:
  cdw:
    enabled: true
    csv_file: /path/to/cdw-orders.csv
    columns:
      serial: "Serial Number"
      model: "Product Description"
```

---

## Rudder — `rudder`

RMM / configuration management. Pulls node inventory.

| Key | Required | Notes |
|---|---|---|
| `url` | ✅ | Your Rudder server URL. |
| `api_token` | ✅ | Rudder API token (sent as `X-API-Token`). |
| `api_version` | — | Default `latest`. |
| `verify_ssl` | — | `false` for self-signed (subject to the TLS opt-in). |

---

## Network discovery — `network_discovery`

Finds devices no MDM/EDR manages (printers, switches, IoT) by reading the local
ARP cache. **No credentials.** Has special safety gating — active sweeping is a
documented no-op TODO and **nothing is scanned by default**. See its dedicated
page: [Network discovery](network-discovery.md).

---

## Not available

- **ServiceNow** — there is **no ServiceNow source or CMDB reader** today. Don't
  configure one; it isn't implemented.

---

Next: [Network discovery](network-discovery.md) · [Sinks & CMDB readers](sinks-and-cmdb.md).

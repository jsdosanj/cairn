# Writeback (Snipe-IT → MDM)

[← Back to docs index](README.md)

Most of Cairn reads *from* your tools *into* your CMDB. **Writeback is the
reverse**: it reads assets from Snipe-IT and pushes the **asset tag** back into
the MDM device that manages the same machine (the `snipe2jamf` / Snipe-IT →
Intune direction), so the MDM matches your system of record.

> Writeback today writes exactly **one** thing: the Snipe-IT asset tag. It never
> creates devices and never deletes anything.

---

## Safety model

Writeback mutates a system you may not fully own, so it's conservative:

- **Dry-run by default.** `cairn writeback` previews; you must add `--apply` to
  write.
- **Conflict policy per target** — `snipe_wins` (overwrite) or `only_if_empty`
  (only fill blanks).
- **Never invents devices** — if the MDM has no device with that serial, the
  device is skipped. Assets without an asset tag or serial are skipped too.

---

## Running it

```bash
cairn writeback            # preview (dry-run): what would change in each MDM
cairn writeback --apply    # actually write the asset tags
```

**Requirements:** a Snipe-IT **sink** must be configured (writeback reads from
it), and at least one **writeback target** must be enabled. If either is missing,
writeback errors (`Writeback needs a Snipe-IT sink configured to read from.` /
`No writebacks enabled.`).

**Exit code:** `0` if nothing failed; `1` if any target write failed; `2` on a
config error. See [CLI reference → writeback](cli-reference.md#cairn-writeback).

Output (a per-target summary):

```
Cairn writeback (dry-run)
  Snipe-IT assets read: 388
  updated: 41  skipped: 340  failed: 7
    jamf: updated 30, skipped 210, failed 4
    intune: updated 11, skipped 130, failed 3

(dry-run — nothing was written. Re-run with --apply to write to your MDM.)
```

- `updated` — the asset tag was (or would be) written.
- `skipped` — already correct, policy declined, or the MDM has no matching device.
- `failed` — the MDM rejected the write.

---

## Configuration

Targets live under `writebacks:`. Each reads the Snipe-IT sink and writes the tag
into its MDM:

```yaml
writebacks:
  jamf:
    enabled: true
    url: https://your.jamf.instance.com
    client_id: YOUR_JAMF_API_CLIENT_ID
    client_secret: YOUR_JAMF_API_CLIENT_SECRET
    conflict: snipe_wins              # writes Snipe-IT tag -> Jamf general.assetTag
  intune:
    enabled: true
    tenant_id: YOUR_AZURE_TENANT_ID
    client_id: YOUR_APP_REGISTRATION_CLIENT_ID
    client_secret: YOUR_APP_REGISTRATION_SECRET
    target_field: notes               # Intune managedDevice field to write
    conflict: only_if_empty
```

### Jamf writeback — `jamf`

Sets a Jamf computer's `general.assetTag`.

| Key | Required | Notes |
|---|---|---|
| `url` | ✅ | Jamf Pro base URL. |
| `client_id` + `client_secret` **or** `username` + `password` | ✅ | API role client (preferred) or basic auth. Same credential model as the [Jamf source](sources.md#jamf-pro--jamf). |
| `conflict` | — | `snipe_wins` (default) or `only_if_empty`. |

### Intune writeback — `intune`

Writes the tag to a configurable `managedDevice` field (default `notes`).

| Key | Required | Notes |
|---|---|---|
| `tenant_id` | ✅ | Entra tenant id. |
| `client_id` | ✅ | App registration id. |
| `client_secret` | ✅ | App registration secret. |
| `target_field` | — | Default `notes`. The `managedDevice` property to write. |
| `conflict` | — | `snipe_wins` or `only_if_empty` (default in the example). |
| `graph_base` / `login_base` | — | Override the Graph / login endpoints. |

> Writing some fields may require the Graph **beta** endpoint and extra
> permissions. `notes` works on the v1.0 endpoint. If you point `target_field` at
> a property v1.0 won't accept, the PATCH will fail for that device (reported as
> `failed`). The app registration needs **write** permission on managed devices
> (e.g. `DeviceManagementManagedDevices.ReadWrite.All`).

---

## Conflict policy

When the target MDM field already has a value, the policy decides whether to
overwrite it:

| Policy | Behavior |
|---|---|
| `snipe_wins` | Overwrite the MDM value with the Snipe-IT asset tag (unless it's already identical). |
| `only_if_empty` | Only set the field when the MDM value is currently blank. Leaves existing values untouched. |

In all cases, if the value already matches, or the desired value is empty, the
device is skipped (no needless write). An invalid `conflict` value is a config
error.

---

## Recommended workflow

1. `cairn sync` so Snipe-IT is current and assets have tags.
2. `cairn writeback` (dry-run) — review the per-target counts and spot-check.
3. `cairn writeback --apply` once you're happy.

Run it on the same schedule as your sync if you want the MDM to track your CMDB
continuously (writeback is not auto-scheduled by `cairn schedule`; wrap it in your
own cron/launchd/Task Scheduler entry if you need that, or run it after each sync).

---

## See also

- [Sources → Jamf / Intune](sources.md) for credential setup details.
- [Sinks & CMDB readers → Snipe-IT (read)](sinks-and-cmdb.md#snipe-it-read--snipeit).
- [Troubleshooting → writeback](troubleshooting.md#writeback).

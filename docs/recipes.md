# How do I…? — recipe index

[← Back to docs index](README.md)

Fast answers to specific tasks. Each links to the full doc.

---

## Setup & install

**…install Cairn without Python?** Download a release binary (macOS/Windows/Linux).
→ [Getting started](getting-started.md#1-install)

**…set everything up without editing YAML?** `cairn setup` then `cairn web`.
→ [Getting started](getting-started.md#the-easy-path-no-yaml-no-terminal-know-how)

**…generate a starter config?** `cairn init > config.yaml && chmod 600 config.yaml`.
→ [CLI → init](cli-reference.md#cairn-init)

**…use a config somewhere else?** `cairn -c /etc/cairn/prod.yaml <cmd>`.
→ [CLI → global options](cli-reference.md#global-options)

**…see what providers exist?** `cairn list-providers`.
→ [CLI → list-providers](cli-reference.md#cairn-list-providers)

---

## Credentials & security

**…keep secrets out of the config file?** Use env vars
(`CAIRN_sources__crowdstrike__client_secret=…`) or the keychain (`keyring:NAME`).
→ [Security](security.md#supplying-secrets-via-environment-variables)

**…store a secret in the OS keychain?** `pip install 'cairn-sync[secrets]'`, then
set the value to `keyring:NAME`.
→ [Security → keychain](security.md#os-keychain-keyring)

**…connect to a self-signed/internal instance?** Set `ca_bundle: /path/ca.pem` on
that provider.
→ [Security → TLS](security.md#tls)

**…show full serials in a report?** `cairn drift --show-serials`.
→ [Drift → masking](drift.md#serial-masking--show-serials)

---

## Testing before you change anything

**…check my config is wired correctly?** `cairn validate`.
→ [CLI → validate](cli-reference.md#cairn-validate)

**…test that every connection actually works?** `cairn doctor`.
→ [CLI → doctor](cli-reference.md#cairn-doctor)

**…see what a sync would do without writing?** `cairn sync --dry-run`.
→ [CLI → sync](cli-reference.md#cairn-sync)

**…audit my CMDB read-only?** `cairn drift`.
→ [Drift](drift.md)

---

## Syncing

**…run a one-off sync?** `cairn sync`.
→ [CLI → sync](cli-reference.md#cairn-sync)

**…re-sync everything after changing field_map?** `cairn sync --full`.
→ [CLI → sync](cli-reference.md#cairn-sync)

**…sync only the machine I'm on?** `cairn sync --mode agent` (or set `mode: agent`).
→ [Concepts → modes](concepts.md#run-modes-fleet-vs-agent)

**…control which tool wins a field?** Order `source_priority`.
→ [Concepts → reconciliation](concepts.md#reconciliation-merging-by-serial)

**…map data into a Snipe-IT custom field?** Add it to `field_map` by the field's
exact label.
→ [Sinks → field mapping](sinks-and-cmdb.md#snipe-it-custom-field-mapping)

---

## Drift & the CMDB

**…find devices my MDM sees but Snipe-IT is missing?** `cairn drift` → "MISSING".
→ [Drift → categories](drift.md#the-four-drift-categories)

**…find retirement candidates?** `cairn drift --stale-days 60`.
→ [Drift](drift.md#running-it)

**…get drift as JSON for a dashboard?** `cairn drift --json -o drift.json`.
→ [Drift → JSON](drift.md#json-output)

**…run drift against GLPI or NetBox instead of Snipe-IT?** Add a `cmdb:` block.
→ [Sinks → choosing the CMDB](sinks-and-cmdb.md#choosing-the-cmdb-for-drift)

**…fail CI when the CMDB is wrong?** `cairn drift` exits non-zero on drift.
→ [CLI → exit codes](cli-reference.md#exit-codes)

---

## Finding unmanaged devices

**…catch printers/switches/IoT that no MDM manages?** Enable `network_discovery`
(passive ARP).
→ [Network discovery](network-discovery.md)

**…actively scan a subnet?** Not possible today — active sweep is a safe no-op
TODO; Cairn stays passive.
→ [Network discovery → passive vs active](network-discovery.md#passive-vs-active-the-safety-gating)

---

## Writeback (Snipe-IT → MDM)

**…push my Snipe-IT asset tags back into Jamf/Intune?** `cairn writeback`
(preview), then `cairn writeback --apply`.
→ [Writeback](writeback.md)

**…only fill blank MDM fields, never overwrite?** Set `conflict: only_if_empty`.
→ [Writeback → conflict policy](writeback.md#conflict-policy)

---

## Automation & scheduling

**…keep Snipe-IT current automatically?** `cairn schedule install --interval 3600`.
→ [Scheduling](scheduling.md)

**…get a recurring drift email/chat digest?**
`cairn schedule install --drift --interval 86400` + a notifier.
→ [Drift → digest](drift.md#scheduling-a-drift-digest)

**…stop the scheduled job?** `cairn schedule uninstall`.
→ [Scheduling](scheduling.md#commands)

**…keep the Linux timer running when logged out?** `loginctl enable-linger $USER`.
→ [Scheduling → Linux](scheduling.md#linux--systemd---user-with-cron-fallback)

**…send run summaries to Slack/Teams?** Enable a notifier.
→ [Notifiers](notifiers.md)

---

## Efficiency

**…make scheduled runs cheap?** Keep `incremental: true` (the default) — only
changed devices are written.
→ [Configuration → incremental](configuration.md#efficiency--incremental-sync)

**…move where state is stored?** Set `state_path` or `CAIRN_STATE`.
→ [Configuration → incremental](configuration.md#efficiency--incremental-sync)

---

## When things go wrong

**…debug an auth failure?** `cairn -v doctor`.
→ [Troubleshooting → auth](troubleshooting.md#authentication-failures-per-connector)

**…look up an exact error message?** → [Error reference](errors.md)

**…understand why everything is "skipped"?** Incremental sync; use `--full`.
→ [Troubleshooting](troubleshooting.md#everything-shows-as-skipped)

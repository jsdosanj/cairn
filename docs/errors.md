# Error & message reference

[← Back to docs index](README.md)

Look up an exact message Cairn printed. Grouped by where it comes from. Run with
`-v` for full context. See also [Troubleshooting](troubleshooting.md).

---

## Exit codes (recap)

| Code | Meaning |
|---|---|
| `0` | Success / no findings |
| `1` | An operation failed, OR a finding was reported (drift found; a connection/sink/target failed) |
| `2` | Config error or invalid argument |
| `130` | Interrupted (Ctrl-C) |

Full table in the [CLI reference](cli-reference.md#exit-codes).

---

## Config errors (exit 2)

| Message | Cause | Fix |
|---|---|---|
| `… is world-readable. Run: chmod 600 …` | Config readable by other users. | `chmod 600 config.yaml`. |
| `… is group-readable. Consider chmod 600.` (warning) | Group can read the config. | `chmod 600`. Non-fatal. |
| `Config file not found: PATH` | `-c PATH` doesn't exist. | Fix the path. |
| `Top-level config must be a mapping` | YAML root isn't a dict. | Make the file a YAML mapping. |
| `PyYAML is required to read YAML config.` | PyYAML not installed. | `pip install pyyaml`. |
| `mode must be 'agent' or 'fleet'` | Bad `mode:`. | Use `agent` or `fleet`. |
| `Config path conflict at a.b.c` | An env override collides with a non-dict node. | Fix the conflicting config/env key. |

---

## Orchestrator / run errors

| Message | Cause | Fix |
|---|---|---|
| `No sinks enabled — nothing to sync into.` | No enabled sink. | Enable `sinks.snipeit`. |
| `No sources enabled.` (warning) | No enabled source. | Enable at least one source. |
| `Failed to initialize <kind> '<key>': …` | A provider couldn't be built (bad/missing config). | Fix that provider's config. The run continues without it. |
| `VALIDATION FAILED: …` | `cairn validate` couldn't construct providers. | Read the trailing message; fix the named provider. |
| `Unexpected failure: …` (exit 1) | Unhandled error. | Re-run with `-v`; check this page / file an issue. |

---

## Provider / config-error messages

| Message | Meaning / fix |
|---|---|
| `<Provider> missing required config: a, b` | Those keys are required. Add them (see [Sources](sources.md)). |
| `<name> must use HTTPS: <url>` | A non-HTTPS URL (non-localhost). Use `https://`. |
| `Jamf Pro requires either client_id+client_secret or username+password` | Provide one complete auth pair. |
| `Network discovery: 'cidr' must look like 10.0.0.0/24, got …` | Fix the CIDR format. |
| `GLPI: initSession returned no session_token` | Bad GLPI tokens or API disabled. See [GLPI](sinks-and-cmdb.md#glpi-read--glpi). |

---

## HTTP errors (`HttpError`)

| Pattern | Meaning | Fix |
|---|---|---|
| `METHOD URL -> 401: …` | Auth rejected. | Wrong credentials / missing permission / wrong region. See [Troubleshooting → auth](troubleshooting.md#authentication-failures-per-connector). |
| `METHOD URL -> 403: …` | Authenticated but not authorized. | Grant the API scope/permission. |
| `METHOD URL -> 404: …` | Wrong URL/path. | Check `url`/`base_url`/region. |
| `METHOD URL -> 429: …` (after retries) | Rate-limited beyond the backoff window. | Slow the cadence / lower `page_size`. See [rate limits](troubleshooting.md#rate-limits--flaky-networks). |
| `… unexpected redirect to '…' (refusing to forward credentials)` | The server returned a 3xx; Cairn won't follow it (credential-leak protection). | Use the final/correct URL directly. |
| `… returned non-JSON body` | Endpoint returned non-JSON (often an HTML error/login page). | Wrong URL, captive portal, or proxy. |
| `Token endpoint returned no access_token: …` | OAuth client-credentials failed. | Check client id/secret/tenant + consent. |

---

## Drift messages

| Message | Meaning / fix |
|---|---|
| `error: --stale-days must be >= 0` (exit 2) | Negative `--stale-days`. Use ≥ 0. |
| `Drift needs a Snipe-IT sink (or a 'cmdb:' block) configured …` | No system of record to read. Enable the sink or add `cmdb:`. |
| `Unknown cmdb backend '<name>'.` | `cmdb.backend` must be `snipeit`/`glpi`/`netbox`. |
| `Warning: some sources failed to pull (results may be incomplete):` | A source errored; findings may be skewed toward false "stale". Fix the source. |

---

## Writeback messages

| Message | Meaning / fix |
|---|---|
| `Writeback needs a Snipe-IT sink configured to read from.` | Enable the Snipe-IT sink. |
| `No writebacks enabled.` | Enable a `writebacks:` target. |
| `<Target>: conflict must be 'snipe_wins' or 'only_if_empty'` | Fix the `conflict` value. |

---

## Sink (Snipe-IT) messages

| Message | Meaning / fix |
|---|---|
| `Snipe-IT rejected create: <messages>` | Validation error (Snipe-IT returns this with HTTP 200). Often a duplicate asset tag or a required custom field. Read the messages. |
| `Snipe-IT asset missing id/asset_tag` | An existing asset row lacked expected fields. Inspect that asset in Snipe-IT. |
| `Snipe-IT upsert failed for ****XXXX: …` | A device failed to write (reported as `failed` in the summary). The trailing detail says why. |

---

## Secrets / keychain

| Message | Meaning / fix |
|---|---|
| `Keychain storage needs the 'keyring' package: pip install 'cairn-sync[secrets]'` | You used `keyring:NAME` without keyring installed. Install the extra or use env vars. |
| `No keychain secret named 'NAME' (service 'cairn').` | The referenced secret isn't stored. Store it (wizard or `keyring`), or use a literal/env value. |

---

## TLS messages

| Message | Meaning / fix |
|---|---|
| `Ignoring verify_ssl=false for HOST: TLS verification stays ON. …` | You set `verify_ssl: false` without the opt-in. Set `ca_bundle`, or export `CAIRN_ALLOW_INSECURE_TLS=1` to force insecure. |
| `TLS verification DISABLED for HOST (CAIRN_ALLOW_INSECURE_TLS=1); credentials are exposed to MITM…` | Insecure mode is active. Prefer `ca_bundle`. |

---

## Network discovery messages

| Message | Meaning / fix |
|---|---|
| `… no ARP table available (tried 'ip neigh' and 'arp -a').` | No ARP tool / no permission. Run where `arp -a`/`ip neigh` work. |
| `… active sweep of <cidr> requested but not yet implemented; falling back to passive ARP-cache read only.` | Expected: active sweep is a no-op TODO. Passive only. |

---

Can't find a message? Re-run with `-v` and check
[Troubleshooting](troubleshooting.md).

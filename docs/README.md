# Cairn documentation

**Every device. One source of truth.**

Cairn is an open-source IT asset inventory, discovery, and reconciliation CLI. It
pulls device records from the MDM and EDR tools that already manage your fleet
(Jamf, Intune, CrowdStrike, …), merges records that describe the same physical
machine by serial number, and keeps your asset system of record (Snipe-IT, GLPI,
or NetBox) honest. It can also tell you exactly where your CMDB is wrong
(`cairn drift`) and push your asset tags back into the MDM (`cairn writeback`).

> Cairn is the evolution of **GhostAssetSync**. The `ghostsync` command and the
> legacy `settings.conf` still work, so existing deployments keep running.

This documentation is written so you never have to contact support. If you are
stuck, the [Troubleshooting](troubleshooting.md) and [FAQ](faq.md) pages cover
nearly every failure mode by symptom.

---

## Start here

| If you want to… | Read |
|---|---|
| Understand what Cairn is and how it works | [Concepts: the source → reconcile → sink model](concepts.md) |
| Install Cairn and run your first sync | [Getting started](getting-started.md) |
| Look up a command or flag | [CLI reference](cli-reference.md) |
| Connect a specific MDM/EDR | [Source connectors](sources.md) |
| Connect Snipe-IT / GLPI / NetBox | [Sinks & CMDB readers](sinks-and-cmdb.md) |
| Write your `config.yaml` | [Configuration reference](configuration.md) |
| Find devices nobody manages | [Network discovery](network-discovery.md) |
| Audit your CMDB for errors | [Drift & reconciliation report](drift.md) |
| Run Cairn automatically | [Scheduling](scheduling.md) |
| Push asset tags back to the MDM | [Writeback](writeback.md) |
| Understand credential handling, masking, TLS | [Security & privacy](security.md) |
| Fix a problem | [Troubleshooting](troubleshooting.md) · [FAQ](faq.md) · [Error reference](errors.md) |
| Do one specific thing fast | [How do I…? recipe index](recipes.md) |

---

## The 60-second version

```bash
# 1. Install (or download a release binary — see Getting started)
pip install -e .

# 2. Set it up the easy way…
cairn setup        # guided wizard: pick tools, paste creds, test live
cairn web          # …or a clickable local dashboard

# 3. …or the manual way
cairn init > config.yaml
chmod 600 config.yaml          # Cairn refuses a world-readable config
# edit config.yaml, then:
cairn doctor                   # test every configured connection
cairn drift                    # is your CMDB lying? (read-only)
cairn sync --dry-run           # show what would change, write nothing
cairn sync                     # do it
cairn schedule install --interval 3600   # keep it current automatically
```

---

## Document map

- [concepts.md](concepts.md) — what Cairn is, modes, the data model, reconciliation.
- [getting-started.md](getting-started.md) — install, first config, first sync.
- [cli-reference.md](cli-reference.md) — every command, every flag, exit codes.
- [configuration.md](configuration.md) — the full config schema, annotated.
- [sources.md](sources.md) — every MDM/EDR source connector + required credentials.
- [network-discovery.md](network-discovery.md) — the passive ARP source and active-sweep gating.
- [sinks-and-cmdb.md](sinks-and-cmdb.md) — Snipe-IT sink, and Snipe-IT/GLPI/NetBox CMDB readers.
- [drift.md](drift.md) — the reconciliation report, confidence scores, masking, digests.
- [writeback.md](writeback.md) — pushing asset tags back to Jamf/Intune.
- [scheduling.md](scheduling.md) — native schedulers per OS, scheduled drift digest.
- [notifiers.md](notifiers.md) — Teams, Slack, generic webhook.
- [security.md](security.md) — credentials, serial masking, TLS, no-scan-by-default.
- [troubleshooting.md](troubleshooting.md) — symptom-driven fixes.
- [faq.md](faq.md) — frequently asked questions.
- [errors.md](errors.md) — error/message reference.
- [recipes.md](recipes.md) — "How do I…?" task index.

> **Not yet implemented** (documented honestly throughout, never overclaimed):
> the network-discovery **active sweep** is a safe no-op TODO (passive ARP read
> only), and there is **no ServiceNow reader** today. See the relevant pages for
> details.

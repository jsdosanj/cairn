# Cairn Roadmap — Consolidate the Snipe-IT integration ecosystem

**Goal:** make Cairn the single tool a Snipe-IT admin installs instead of stitching
together a dozen one-off `X2snipe` scripts — and make it usable by someone who has
never opened a terminal.

Today Cairn already does the hard architectural part: a pluggable engine that pulls
from many sources, reconciles by serial, and writes to Snipe-IT, with incremental
sync, scheduling, and notifications. This roadmap extends that to cover the full
integration directory and adds a non-technical-friendly experience on top.

---

## 1. The landscape (Snipe-IT integration directory → Cairn)

Most listed integrations are single-purpose. Cairn absorbs them as plugins.

| Existing integration | Kind | Cairn mapping | Status |
|---|---|---|---|
| JAMF2Snipe | MDM → Snipe (inbound) | `sources/jamf` | ✅ shipped |
| (Intune, JumpCloud, CrowdStrike, Sophos, Defender) | MDM/EDR → Snipe | `sources/*` | ✅ shipped |
| Kandji2Snipe | MDM → Snipe | new `sources/kandji` | planned |
| axm2snipe | Apple Business/School Manager → Snipe | new `sources/apple_axm` | planned |
| retriever2snipe | Google Workspace / ChromeOS → Snipe | new `sources/google_workspace` | planned |
| UniFi to Snipe-IT | Network gear → Snipe | new `sources/unifi` | planned |
| cdw2snipe | Procurement (CDW orders) → Snipe | new `sources/cdw` | planned |
| Rudder.io ↔ Snipe-IT | RMM/config-mgmt ↔ Snipe | `sources/rudder` (+ writeback) | planned |
| snipe2jamf | Snipe → Jamf (outbound) | writeback capability | planned |
| Snipe-IT to InTune | Snipe → Intune (outbound) | writeback capability | planned |
| SnipeSharp / PowerShell / Python module / SAM cli | API wrappers | documented `cairn` Python client | optional |
| MCP server for Snipe-IT | AI access | `cairn mcp` server | optional |
| Asset Reservation/Checkout | Workflow app | out of scope (note as adjacent) | n/a |
| InQRy, JupiterOne, Python Module | archived | skip | n/a |

Net new connectors to reach parity: **Kandji, Apple ABM/ASM, Google/ChromeOS,
UniFi, CDW, Rudder**, plus **outbound writeback** to Jamf/Intune.

---

## 2. Architecture changes required

The current model is endpoint/computer-centric. To cover network gear, procurement,
and write-back, three additions:

1. **Asset typing.** Add `asset_type` to `NormalizedDevice` (or introduce a broader
   `NormalizedAsset`): `computer | mobile | network | accessory | consumable |
   purchase_order`. Snipe-IT distinguishes hardware/accessories/consumables and has
   purchase metadata; UniFi (network) and CDW (procurement) need this. Field mapping
   becomes type-aware.
2. **Bidirectional capability.** Generalize the registry so an integration can be a
   `source`, a `sink`, or both. Add a `Writeback` interface: read assets from
   Snipe-IT (a `SnipeITSource`) and push selected fields back to an MDM
   (`JamfWriteback`, `IntuneWriteback`). Direction and field ownership are config-
   driven, with conflict policy (`snipe_wins | mdm_wins | newest_wins`).
3. **Identity beyond serial.** Network devices and accessories often lack a serial.
   Add a configurable match strategy per source: `serial | mac | asset_tag |
   external_id`, falling back in order. (`merge_devices` already unions MACs;
   formalize the match key.)

These are additive; existing providers keep working unchanged.

---

## 3. Workstreams

### A. Inbound connector parity (fits the existing `DeviceSource` model)
One module + one registry line each, same pattern as the shipped six. Priority order
by demand:

1. **Kandji** — REST API, bearer token. Closest to existing MDM sources; quick win.
2. **Google Workspace / ChromeOS** — Admin SDK Directory API (OAuth2 service account,
   domain-wide delegation). Pulls Chromebooks + mobile. Asset type `computer/mobile`.
3. **Apple Business/School Manager (axm)** — Apple's API (OAuth2 + signed JWT client
   assertion). Procurement/enrollment truth for Apple fleets.
4. **UniFi** — UniFi Network/Site Manager API (API key). Asset type `network`.
   Drives the asset-typing work.
5. **CDW** — procurement feed (API or CSV/SFTP import). Creates assets + purchase
   metadata (PO, cost, order date). Introduces an import-file source kind.
6. **Rudder** — Rudder API (token). Inventory of managed nodes.

### B. Outbound writeback (snipe2jamf, snipe-to-intune)
- `SnipeITSource` to read assets/asset_tags.
- `JamfWriteback` / `IntuneWriteback` to push asset tag + chosen fields back.
- Config: which fields, which direction, conflict policy, dry-run parity.

### C. Non-technical UX (the headline requirement)
The plugin engine is solid but YAML+CLI is a wall for non-technical admins. Add:

1. **Setup wizard** — `cairn setup`: an interactive TUI (e.g. `questionary`/`rich`)
   that lists integrations, asks for credentials with inline help and links, **tests
   the connection live**, and writes config. No hand-editing YAML.
2. **Local web dashboard** — `cairn web` launches a small bundled web app
   (FastAPI + static UI, served from the same binary) to:
   - toggle integrations and edit field mappings with dropdowns (no YAML),
   - run a **dry-run and show a diff table** (what would be created/updated),
   - view run history + per-integration health (green/red),
   - set the schedule with a picker (wraps `cairn schedule`).
3. **Secret storage** — store credentials in the OS keychain via `keyring`
   (macOS Keychain / Windows Credential Manager / libsecret) instead of plaintext
   YAML. Config references a secret name; the wizard writes the secret.
4. **First-run experience** — installers launch `cairn setup` on first run; friendly,
   actionable errors ("Snipe-IT token rejected — check it has the right permissions",
   with a fix link).

### D. Robustness & operations
- **Connection self-tests** per integration (`cairn doctor`) with clear pass/fail.
- **Run reports**: structured JSON + a local run-history store, surfaced in the web UI.
- **Per-integration isolation** (already: one source failing doesn't kill the run) +
  circuit-breaker/health status surfaced to the UI.
- **Rate limits / pagination**: already centralized in `http.py`; add per-provider
  concurrency caps and a global "be gentle" mode.
- **Test matrix**: mocked-API unit tests per provider (pattern established with
  `responses`), plus a contract-test harness. Keep the suite offline.
- **Observability**: optional Prometheus metrics endpoint; notifications already exist.

### E. Ecosystem parity (optional, high-leverage)
- **`cairn mcp`** — a Model Context Protocol server exposing fleet/asset data so AI
  assistants can answer "where is asset 1042?" Covers the MCP item and reinforces
  "easy to use."
- **Documented Python client** — promote `sinks/snipeit` into a stable, importable
  `cairn.client` API (parity with SnipeSharp / the Python module).

---

## 4. Phasing

| Phase | Scope | Rough size (CC+gstack) |
|---|---|---|
| **P1 — Connector parity I** ✅ shipped (v1.1.0) | Kandji, Google/ChromeOS, asset-typing model | done |
| **P2 — Connector parity II** ✅ shipped (v1.2.0) | Apple ABM, UniFi, Rudder, CDW import | done |
| **P3 — Writeback** ✅ shipped (v1.3.0) | SnipeITSource + Jamf/Intune writeback + conflict policy | done |
| **P4 — Setup wizard + secrets** ✅ shipped (v1.1.0) | `cairn setup`, keyring, `cairn doctor` | done |
| **P5 — Web dashboard** ✅ shipped (v1.1.0) | `cairn web`: config, dry-run diff, schedule | done |
| **P6 — MCP + Python client** | optional | ~half a day |

Each phase ships independently, keeps the test suite green, and updates docs + the
site's integration list.

---

## 5. Key decisions & risks (need a human call)

- **Web UI scope** — P5 is the biggest lift and the biggest usability win. A local
  single-user dashboard is achievable; a multi-user hosted control plane is a
  different product. Recommend starting local-only.
- **Credentials per vendor** — ABM, Google, and some MDMs require the admin to create
  API apps / service accounts. The wizard can link to step-by-step guides but can't
  remove the vendor-side setup. Worth pre-writing those guides.
- **Asset-type model change** touches the sink and field mapping; do it early (P1) so
  later connectors build on it.
- **Writeback is higher-stakes** than read — it mutates the MDM. Ship it dry-run-first
  with explicit per-field opt-in.
- **Secret storage** in keychain is great on desktops; headless servers need a file or
  env fallback (keep the current env-var path as the server story).

---

## 6. Immediate next step

P1 is the natural start and a clean demo of the consolidation story: add **Kandji**
and **Google/ChromeOS** sources plus the **asset-type** field, with mocked-API tests,
behind the same `cairn sync` users already have. Say the word and I'll build P1.

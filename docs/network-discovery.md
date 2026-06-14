# Network discovery

[← Back to docs index](README.md)

The `network_discovery` source is Cairn's answer to *"but it only knows what my
MDM knows."* Printers, switches, IoT, and rogue boxes never enroll in
Jamf/Intune/CrowdStrike, so the managed sources are blind to them. Network
discovery surfaces every device that has recently talked on the local segment.

It is built to be **safe by default**: it reads the kernel ARP cache that normal
network traffic already populated, and it **sends no probe packets of its own**
unless you explicitly opt in (and even then, see the no-op note below).

---

## What it does

- Reads the local **ARP / neighbor cache** (`ip neigh` on Linux, then `arp -a` on
  macOS/BSD/Windows).
- Parses every resolved entry into one device per distinct **MAC address** —
  network gear rarely exposes a serial, so MAC is the identity here.
- Looks up the **manufacturer** from the MAC's OUI prefix (a curated built-in
  table of common vendors — Apple, Cisco, Ubiquiti, HP, Dell, Raspberry Pi,
  Brother, Google, Intel, etc.). Unknown prefixes are simply left blank.
- Emits `asset_type: network` records (override with `asset_type`). The IP
  becomes the `hostname` placeholder until something better enriches it. The
  serial is `UNKNOWN`, so these devices are correlated by MAC, not merged into
  serial-keyed assets.

Incomplete ARP entries (an IP with no resolved MAC) and broadcast/all-zero MACs
are dropped.

---

## Configuration

```yaml
sources:
  network_discovery:
    enabled: true
    # cidr: 10.0.0.0/24      # OPTIONAL — only needed to opt in to active sweep
    # active_sweep: false    # active sweep is a no-op TODO today (see below)
    # asset_type: network    # override the emitted asset class
```

| Key | Required | Default | Notes |
|---|---|---|---|
| `enabled` | — | `false` | Turn the source on. |
| `cidr` | — | (none) | A CIDR like `10.0.0.0/24`. **Only** used to opt in to active sweeping. Must look like a valid IPv4 CIDR or config validation fails. |
| `active_sweep` | — | `false` | Opt in to active probing. **Currently a safe no-op** (see below). |
| `asset_type` | — | `network` | Asset class for discovered devices. |

No credentials. No URL. Nothing to authenticate.

---

## Passive vs. active: the safety gating

This is the most important thing to understand about this source.

### Passive (the default, always safe)

By default, network discovery **only reads the ARP cache**. The cache is already
populated by ordinary traffic on the segment, so reading it sends **zero packets**
of Cairn's own. It is non-intrusive and won't trip an IDS. The trade-off: you only
see devices that have *recently talked* on the segment.

### Active sweep (opt-in, and currently a no-op)

An active sweep would probe a range of addresses (ARP-who-has / ICMP) to populate
the cache first, so even quiet hosts show up. Because an unscoped network scan is
intrusive and can trip intrusion detection, active sweeping is **doubly gated**:

1. you must set a `cidr`, **and**
2. you must set `active_sweep: true`.

Omit either and you stay in passive-only mode.

> **Not yet implemented.** The active-sweep probe is a **deliberate, documented
> no-op TODO**. Raw-socket ARP requires root and is platform-specific; rather than
> ship a fragile privileged scanner, Cairn leaves it unimplemented so that
> enabling `active_sweep` **never silently scans a network in a half-built way**.
> If you enable it today, Cairn logs that a sweep was requested but not
> implemented, and falls back to the passive ARP-cache read. No packets are sent.

So in practice: **today, network discovery is passive only**, regardless of
config. The `cidr`/`active_sweep` keys are validated and accepted so your config
is future-proof, but they don't change current behavior.

---

## Where to run it

Run it on a host that sits on the network segment you care about (passive
discovery only sees the local segment's ARP cache). For multiple VLANs/segments,
run Cairn on a host in each, or on a box that routes/sees them.

If the ARP tools aren't available or you lack permission, the source logs a
warning and yields **nothing** rather than crashing the run — discovery degrades
quietly.

---

## How discovered devices appear

- In `cairn sync`: written to your sink with `asset_type: network`, identified by
  MAC, `serial: UNKNOWN`, manufacturer from OUI when recognized, IP as the
  hostname placeholder.
- In `cairn drift`: because these have no serial, they don't appear as
  serial-keyed missing/stale findings. Network discovery's value is mainly in
  *populating* the inventory, not in serial reconciliation.

---

## See also

- [Sources](sources.md) for the managed MDM/EDR connectors.
- [Security](security.md#no-scan-by-default) for the no-scan-by-default policy.
- [Troubleshooting → network discovery finds nothing](troubleshooting.md#network-discovery-finds-nothing).

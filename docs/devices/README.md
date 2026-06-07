# Device setup guide

HSNC manages devices over **two planes**:

| Plane | Transport | Purpose |
| --- | --- | --- |
| **Configuration** | SSH (always) | Read the running config, push changes (VLANs, ports, SSIDs). |
| **Monitoring** | Pluggable | Poll *live* runtime data: device status, uptime, attached clients. |

Configuration is always done over SSH. Monitoring is selected **per device** in
[`config/devices.yaml`](../../config/devices.yaml.example) via a `monitoring`
block:

```yaml
monitoring:
  source: primary | secondary | none   # default: primary
  secondary:                           # only read when source: secondary
    type: prometheus | snmp
    endpoint: "http://10.0.0.5:9100/metrics"   # or snmp host[:port]
    port: 161                          # SNMP only (default 161)
```

* **`source: primary`** — poll over the same SSH plane used for configuration
  (OpenWrt `ubus`, JetStream interactive CLI). No extra device setup required.
* **`source: secondary`** — poll over the device's dedicated telemetry channel:
  a **Prometheus exporter** for OpenWrt devices, or **SNMPv3** for JetStream
  switches. Once a device has a working secondary connection, it is used for
  polling.
* **`source: none`** — disable live polling; the device reports `unknown`.

## Strict selection (no silent fallback)

Selection is **strict**: when `source: secondary` is set, HSNC never falls back
to SSH for polling. If the secondary connection is unreachable or misconfigured,
the device honestly reports **`unknown`** with no clients, rather than masking
the problem. This keeps the operational picture truthful.

If `source: secondary` is set but `secondary.type` is missing or unknown, the
device is treated as unmonitored (`unknown`) and a warning is logged.

## Secrets stay out of the inventory

`devices.yaml` only ever contains *non-secret* connection details. All
credentials — SSH passwords, SNMPv3 auth/priv keys, Prometheus bearer tokens —
come from the **environment** (`HSNC_*` variables), exactly like the SSH
passwords. See [`.env.example`](../../.env.example).

## Per-platform setup

| Platform | Kinds | Primary (SSH) | Secondary |
| --- | --- | --- | --- |
| [OpenWrt](openwrt.md) | gateway, access_point | `ubus` over SSH | Prometheus node-exporter |
| [JetStream](jetstream.md) | switch | interactive CLI | SNMPv3 |

Follow the per-platform guide to enable SSH and (optionally) the secondary
polling channel:

* [OpenWrt device setup](openwrt.md)
* [JetStream switch setup](jetstream.md)

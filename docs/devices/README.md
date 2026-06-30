# Device setup guide

HSNC manages devices over **two planes**:

| Plane | Transport | Purpose |
| --- | --- | --- |
| **Configuration** | SSH (always) | Read the running config, push changes (VLANs, ports, SSIDs). |
| **Monitoring** | Non-SSH, per platform | Poll *live* runtime data: device status, uptime, attached clients. |

Configuration is always done over SSH. The monitoring plane **never uses SSH**:
the transport is fixed by platform — a **Prometheus exporter** for OpenWrt
gateways/APs and **SNMPv3** for JetStream switches. There is nothing to select.
The optional per-device `monitoring` block in
[`config/devices.yaml`](../../config/devices.yaml.example) only toggles polling
and, if needed, overrides the endpoint:

```yaml
monitoring:
  enabled: true                              # default; false disables polling
  endpoint: "http://10.0.0.5:9100/metrics"   # optional; SNMP host[:port] for switches
  port: 161                                  # optional, SNMP only (default 161)
```

* **`enabled: true`** (default) — poll the device for live data over its
  platform transport (Prometheus for OpenWrt, SNMPv3 for JetStream).
* **`enabled: false`** — disable live polling; the device reports `unknown`.
* **`endpoint` / `port`** — optional. When omitted the endpoint is derived from
  the device's management IP (`http://<ip>:9100/metrics` for Prometheus,
  `<ip>:161` for SNMP).

## Honest unknown (no SSH fallback)

The monitoring plane never falls back to SSH. If a device's Prometheus exporter
or SNMPv3 endpoint is unreachable or misconfigured, the device honestly reports
**`unknown`** with no clients rather than masking the problem. This keeps the
operational picture truthful.

## Secrets stay out of the inventory

`devices.yaml` only ever contains *non-secret* connection details. All
credentials — SSH passwords, SNMPv3 auth/priv keys, Prometheus bearer tokens —
come from the **environment** (`HSNC_*` variables), exactly like the SSH
passwords. See [`.env.example`](../../.env.example).

## Per-platform setup

| Platform | Kinds | Config (SSH) | Monitoring |
| --- | --- | --- | --- |
| [OpenWrt](openwrt.md) | gateway, access_point | `uci` over SSH | Prometheus node-exporter |
| [JetStream](jetstream.md) | switch | interactive CLI | SNMPv3 |

Follow the per-platform guide to enable SSH (configuration) and the monitoring
transport:

* [OpenWrt device setup](openwrt.md)
* [JetStream switch setup](jetstream.md)

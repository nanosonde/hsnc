# ADR 0015 — Monitoring plane uses non-SSH transports per platform

**Status:** Accepted (supersedes [ADR 0010](0010-pluggable-secondary-monitoring.md))

## Context

ADR 0006 split a configuration plane (SSH) from a monitoring plane, and ADR 0010
made the monitoring source pluggable per device (`primary` SSH scrape vs a
`secondary` Prometheus/SNMPv3 channel). In practice SSH scraping is slow,
stresses devices when polled often, and reusing the configuration transport for
telemetry blurs the two planes. The per-device `monitoring.source` selector also
added configuration surface and a failure mode (a device silently left on the
SSH `primary`) for no real benefit, since each platform already has one obvious
non-SSH telemetry transport.

## Decision

The monitoring plane **never uses SSH**. SSH is exclusively the configuration
plane. The monitoring transport is fixed by device platform/kind:

- OpenWrt gateways and access points → a **Prometheus** node-exporter
  (e.g. `prometheus-node-exporter-lua`), read over HTTP.
- JetStream switches → **SNMPv3** (USM, `authPriv`).

There is no `primary`/`secondary` model and no SSH fallback. The per-device
`monitoring` block carries only an `enabled` flag (default `true`; `false`
disables polling and the device reports `UNKNOWN`) and an optional non-secret
`endpoint`/`port` override that otherwise defaults to the device's management IP
(`http://<ip>:9100/metrics` for Prometheus, `<ip>:161` for SNMP). An unreachable
or misconfigured endpoint reports `UNKNOWN` rather than masking the problem.
`pysnmp` remains an optional `[snmp]` extra, lazily imported; Prometheus uses
stdlib `urllib`.

## Consequences

- Lighter, faster polling that never touches the SSH configuration path.
- One transport per platform — no source selector, no hidden SSH fallback.
- Endpoints in YAML (optional, IP-derived by default), credentials in env
  (ADR 0009); tests use fake transports.
- The OpenWrt/JetStream SSH monitoring providers are removed; the SSH adapters
  keep owning the configuration plane only.
- Dev/test still use mock providers (ADR 0013); the fake device containers also
  serve the monitoring plane (OpenWrt a Prometheus exporter on `:9100`, JetStream
  an SNMPv3 agent on `161/udp`) so live polling can be exercised end to end.

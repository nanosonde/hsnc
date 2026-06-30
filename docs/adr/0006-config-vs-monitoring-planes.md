# ADR 0006 — Split config plane from monitoring plane

**Status:** Accepted

## Context

Reading live status/clients and reading/writing configuration have different
needs. Configuration must be exact and is naturally SSH (UCI / CLI). Monitoring
is high-frequency and could come from richer sources (exporters, SNMP). Forcing
both through one path coupled telemetry to SSH and slowed polling.

## Decision

Separate two ports. **Config plane:** `DeviceAdapter` (`supports` /
`fetch_config` / `push_config`) — SSH only. **Monitoring plane:**
`MonitoringProvider` (`fetch_status` / `fetch_clients`) selected per device by a
factory. A dedicated background poller drives monitoring; apply history is
recorded separately. SSH is used **only** for configuration; the monitoring
plane never uses SSH and reads over a per-platform non-SSH transport (ADR 0015).

## Consequences

- Telemetry sources evolve without touching configuration (ADR 0015).
- A device with no working monitor reports `UNKNOWN` instead of failing.
- Two ports and two factories to understand, but cleanly separated.

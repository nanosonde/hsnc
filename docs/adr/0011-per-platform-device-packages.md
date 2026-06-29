# ADR 0011 — Per-platform device packages

**Status:** Accepted

## Context

OpenWrt and JetStream code (config renderer, SSH adapter, primary/secondary
monitoring) had grown into flat sibling modules. Adding secondary transports
(Prometheus, SNMPv3) would multiply files and blur which code belonged to which
platform.

## Decision

Group platform code into packages under `hsnc/src/hsnc/devices/`: `openwrt/`
(adapter, config_renderer, ssh_monitoring, prometheus_monitoring) and
`jetstream/` (adapter, config_renderer, ssh_monitoring, snmp_monitoring). Shared
SSH transport stays at the parent; the config-adapter and monitoring-provider
factories select by kind/source.

## Consequences

- Each platform's code is cohesive and discoverable; adding one is a new folder.
- Factories remain the single routing point.
- Slightly deeper import paths.

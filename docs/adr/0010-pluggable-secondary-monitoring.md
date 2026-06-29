# ADR 0010 — Pluggable secondary monitoring with strict selection

**Status:** Accepted

## Context

SSH scraping works but is slow and stresses devices when polled often. OpenWrt
can expose a Prometheus node exporter; JetStream switches speak SNMPv3. The
monitoring plane (ADR 0006) was designed to accept richer sources, but the
channel must be explicit and never silently fall back.

## Decision

Add per-device `monitoring.source: primary | secondary | none`. `primary` scrapes
over SSH; `secondary` uses a per-device channel (`prometheus` for OpenWrt, `snmp`
for JetStream); `none` disables polling. Selection is **strict** — a `secondary`
device is never polled over SSH. Misconfig or unreachable secondary ⇒ `UNKNOWN`
with a warning. `pysnmp` is an optional `[snmp]` extra, lazily imported;
Prometheus uses stdlib `urllib`.

## Consequences

- Lighter, faster polling where exporters/SNMP exist; honest `UNKNOWN` otherwise.
- No hidden fallback masks misconfiguration.
- Endpoints in YAML, credentials in env (ADR 0009); tests use fake transports.

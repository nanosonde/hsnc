# ADR 0013 — Mock providers + fake device containers for dev/test

**Status:** Accepted

## Context

Developing and testing a hardware controller without hardware is hard. CI needs
deterministic, network-free unit tests; contributors need a way to try the full
UI; integration needs realistic SSH behavior without real switches.

## Decision

Two complementary aids. **Mock providers** (`HSNC_USE_MOCK_DEVICES=1`) serve a
seeded inventory so the whole UI and apply workflow run with no devices.
**Fakes** ([`fakes/`](../../fakes/)) are throwaway containers simulating OpenWrt
and JetStream on both planes — the SSH configuration plane and the non-SSH
monitoring plane (a Prometheus exporter for OpenWrt, an SNMPv3 agent for
JetStream) — used by the integration smoke test. Unit tests inject fakes
(fake SSH runner, fake monitoring providers) and never need optional deps.

## Consequences

- Fast, hands-off CI; easy hardware-free demos.
- Real adapters are exercised against realistic device simulators on both planes.
- Mock data and fakes must track real provider behavior as it evolves.
- "Fakes" (working simulators) are deliberately distinct from "mocks".

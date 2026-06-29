# ADR 0014 — AGPL-3.0-or-later license

**Status:** Accepted

## Context

The project is an open-source, self-hosted network controller. It is delivered
primarily as a network service (a web UI), so modifications could be offered to
users over a network without distributing source under weaker copyleft.

## Decision

License the project under **AGPL-3.0-or-later**. The AGPL's network-use clause
requires that users interacting with a modified instance over a network can
obtain the modified source.

## Consequences

- Modified, network-deployed forks must share source with their users.
- Strong protection for an open, self-hosted ecosystem.
- May deter closed/SaaS adopters who can't comply — an accepted trade-off.

# ADR 0001 — Clean Architecture with ports & adapters

**Status:** Accepted

## Context

The controller must talk to heterogeneous hardware (OpenWrt, JetStream) and
swap data sources (real SSH vs mock) without rewriting business logic. Coupling
domain rules to Flask, paramiko or SQLite would make the system rigid and hard to
test.

## Decision

Adopt Clean Architecture. Domain **entities**, **value objects** and **ports**
(`interfaces.py`) have no I/O. **Use cases** orchestrate them. **Adapters**
implement the ports (YAML, SQLite, device drivers, security). A single
composition root (`container.py`) wires concretes to ports and chooses mock vs
real. Dependencies point inward only.

A later refactor flattened the nested layer folders into a flat module layout
under `hsnc/src/hsnc/` while preserving the dependency direction — fewer folders,
same discipline.

## Consequences

- Use cases are unit-testable with fakes; no hardware or network needed.
- New device platforms or data sources slot in behind existing ports.
- One wiring location (`container.py`) keeps construction explicit.
- Contributors must respect the inward dependency rule; ruff import rules help.

# ADR 0008 — Read-only mode on by default

**Status:** Accepted

## Context

The controller writes to live network hardware. An accidental apply during setup,
demos or exploration could disrupt a production network.

## Decision

Start in **read-only mode**: applying configuration to devices is blocked, while
editing and reverting pending changes stay available. An admin disables it via a
top-bar toggle when ready to push. Read-only only gates applying, not editing.

## Consequences

- Safe-by-default; deliberate action required before any device is touched.
- Editing and review still work read-only, so changes can be staged ahead of a
  change window.
- Admins must remember to re-enable it afterward.
